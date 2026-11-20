"""Tests voor de datamap (db/init_db.standaard_map) en het eenmalig overnemen van data/ naast de .exe.

Nagebootste .exe in een tijdelijke map (sys.frozen, sys.executable, LOCALAPPDATA). Alleen
nepgegevens, vaste testsleutel; de echte sleutelkluis en data/ worden niet aangeraakt.
Werkt met pytest.
"""

import contextlib
import io
import shutil
import sys
from pathlib import Path

import pytest

import instellingen
from db import init_db as db_init
from db.init_db import DATABASES, OvernameFout, init_db, oude_data_overnemen, standaard_map
from db.queries import Opslag
from hulp import TESTSLEUTEL

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def geen_eigen_datamap(monkeypatch):
    monkeypatch.delenv("AVS_DATA", raising=False)


@pytest.fixture
def exe(tmp_path, monkeypatch):
    """(map van de .exe, nieuwe datamap) van een nagebootste .exe."""
    programma = tmp_path / "Programma"
    programma.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(programma / "AVS.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    return programma, tmp_path / "Local" / "AVS" / "data"


def _stil(f, *args, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*args, **kw)


def _oude_data(map_: Path) -> None:
    """Echte (versleutelde) databases met één nep-atleet, en instellingen."""
    _stil(init_db, map_, hoofd=TESTSLEUTEL)
    from atleten import beheer
    with Opslag(map=map_, hoofd=TESTSLEUTEL) as db:
        beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2011-03-14")
    (map_ / "instellingen.json").write_text('{"thema": "donker"}', encoding="utf-8")


# ---------------- standaard_map ----------------
def test_in_de_exe(exe):
    _, nieuw = exe
    assert standaard_map() == nieuw


def test_in_de_exe_zonder_localappdata(exe, monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "thuis"))
    assert standaard_map() == tmp_path / "thuis" / "AppData" / "Local" / "AVS" / "data"


def test_eigen_datamap_gaat_voor(exe, monkeypatch, tmp_path):
    monkeypatch.setenv("AVS_DATA", str(tmp_path / "ergens"))
    assert standaard_map() == tmp_path / "ergens"
    monkeypatch.delattr(sys, "frozen")
    assert standaard_map() == tmp_path / "ergens"
    monkeypatch.setenv("AVS_DATA", "   ")                        # leeg telt niet
    assert standaard_map() == REPO / "data"


def test_instellingen_volgen_de_datamap(exe):
    _, nieuw = exe
    instellingen.opslaan(instellingen.Instellingen(thema="donker"))
    assert (nieuw / "instellingen.json").is_file()
    assert instellingen.laad().thema == "donker"


# ---------------- oude_data_overnemen ----------------
def test_overnemen(exe):
    programma, nieuw = exe
    oud = programma / "data"
    _oude_data(oud)
    (oud / "personen.db-journal").write_bytes(b"journal")      # achtergebleven journal gaat mee
    (oud / "iets_anders.txt").write_text("blijft")              # alleen AVS-bestanden

    namen = _stil(oude_data_overnemen)
    assert set(namen) == {f"{d}.db" for d in DATABASES} | {"personen.db-journal", "instellingen.json"}
    assert not (nieuw / "iets_anders.txt").exists() and not (nieuw / ".overnemen").exists()
    assert all((oud / n).is_file() for n in namen)               # kopiëren: de oude map blijft staan
    (nieuw / "personen.db-journal").unlink()                    # nep-journal: niet laten 'terugdraaien'

    with Opslag(map=nieuw, hoofd=TESTSLEUTEL) as db:            # dezelfde sleutel opent de kopie
        assert [a.naam for a in db.atleten()] == ["Anna Voorbeeld"]
    assert instellingen.laad().thema == "donker"

    assert _stil(oude_data_overnemen) == []                     # tweede keer: niets meer te doen


def test_nooit_overschrijven(exe):
    programma, nieuw = exe
    _oude_data(programma / "data")
    nieuw.mkdir(parents=True)
    (nieuw / "personen.db").write_bytes(b"bestaand")
    assert _stil(oude_data_overnemen) == []
    assert (nieuw / "personen.db").read_bytes() == b"bestaand"
    assert not (nieuw / "prestaties.db").exists()


def test_eigen_instellingen_blijven(exe):
    programma, nieuw = exe
    _oude_data(programma / "data")
    nieuw.mkdir(parents=True)
    (nieuw / "instellingen.json").write_text('{"thema": "licht"}', encoding="utf-8")
    namen = _stil(oude_data_overnemen)
    assert "instellingen.json" not in namen and "personen.db" in namen
    assert instellingen.laad().thema == "licht"


@pytest.mark.parametrize("inhoud", [None, "alleen_instellingen"])
def test_niets_over_te_nemen(exe, inhoud):
    programma, nieuw = exe
    if inhoud:
        (programma / "data").mkdir()
        (programma / "data" / "instellingen.json").write_text("{}", encoding="utf-8")
    assert _stil(oude_data_overnemen) == []
    assert not nieuw.exists() or not list(nieuw.iterdir())


def test_zelfde_map_en_broncode(exe, monkeypatch, tmp_path):
    programma, _ = exe
    _oude_data(programma / "data")
    monkeypatch.setenv("AVS_DATA", str(programma / "data"))   # datamap ís de oude map
    assert _stil(oude_data_overnemen) == []
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.delenv("AVS_DATA")
    assert db_init._oude_datamap() is None
    assert _stil(oude_data_overnemen, doel=tmp_path / "doel") == []


def test_mislukt_kopieren_laat_niets_half_achter(exe, monkeypatch):
    programma, nieuw = exe
    oud = programma / "data"
    _oude_data(oud)
    echte_copy2 = shutil.copy2
    teller = {"n": 0}

    def kapot(bron, doel, *a, **kw):
        teller["n"] += 1
        if teller["n"] == 3:
            raise OSError(28, "No space left on device")
        return echte_copy2(bron, doel, *a, **kw)

    monkeypatch.setattr(db_init.shutil, "copy2", kapot)
    with pytest.raises(OvernameFout, match="niets gewist") as e:
        _stil(oude_data_overnemen)
    assert str(oud) in str(e.value) and str(nieuw) in str(e.value)
    assert not list(nieuw.glob("*.db")) and not (nieuw / ".overnemen").exists()
    assert all((oud / f"{d}.db").is_file() for d in DATABASES)


# ---------------- start() en de pagina Instellingen ----------------
def _start_met(monkeypatch, init_db_stub):
    from ui import app as app_mod
    gezien = {}

    def nep_maak_app(map=None, hoofd=None, startfout=None, sleutelfout=True):
        gezien.update(startfout=startfout, sleutelfout=sleutelfout)
        raise SystemExit

    monkeypatch.setattr(app_mod, "init_db", init_db_stub)
    monkeypatch.setattr(app_mod, "maak_app", nep_maak_app)
    with pytest.raises(SystemExit):
        _stil(app_mod.start, browser=False)
    return gezien


def test_start_neemt_eerst_over(exe, monkeypatch):
    programma, nieuw = exe
    _oude_data(programma / "data")
    gezien_bij_init = []
    gezien = _start_met(monkeypatch, lambda map=None: gezien_bij_init.append(sorted(p.name for p in nieuw.glob("*.db"))))
    assert gezien_bij_init == [sorted(f"{d}.db" for d in DATABASES)]   # overgenomen vóór init_db
    assert gezien["startfout"] is None


def test_start_bij_mislukte_overname(exe, monkeypatch):
    def kapot(*a, **kw):
        raise OvernameFout("Je gegevens konden niet worden overgenomen.")
    from ui import app as app_mod
    monkeypatch.setattr(app_mod, "oude_data_overnemen", kapot)
    aangeroepen = []
    gezien = _start_met(monkeypatch, lambda map=None: aangeroepen.append(map))
    assert aangeroepen == []                                      # géén lege databases aanmaken
    assert gezien == {"startfout": "Je gegevens konden niet worden overgenomen.", "sleutelfout": False}


def test_instellingen_toont_datamap(tmp_path):
    from ui.app import maak_app
    _stil(init_db, tmp_path, hoofd=TESTSLEUTEL)
    app = maak_app(map=tmp_path, hoofd=TESTSLEUTEL)
    html = app.test_client().get("/instellingen").get_data(as_text=True)
    assert 'id="gegevens"' in html and f"<code>{tmp_path}</code>" in html
