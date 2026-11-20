"""Tests voor de controle op schema's en migraties (db/init_db.py) en InstallatieFout in de app.

Een .exe zonder (alle) SQL-bestanden mag niet crashen of stil migraties overslaan, en een
oudere AVS mag niet doorstarten op databases die hij niet kent. Alleen nepgegevens in een
tijdelijke map, vaste testsleutel. Werkt met pytest.
"""

import contextlib
import io
import shutil
import sys
from pathlib import Path

import pytest

from db import init_db as db_init
from db.init_db import DATABASES, InstallatieFout, controleer_sql_bestanden, init_db, verbind
from ui.app import maak_app
from hulp import TESTSLEUTEL


@pytest.fixture
def sql_kopie(tmp_path, monkeypatch):
    """Een kopie van de SQL-bestanden, zoals ze in de .exe staan (…/db); de module wijst ernaar."""
    kopie = tmp_path / "meegebouwd" / "db"
    kopie.mkdir(parents=True)
    for f in db_init.DB_DIR.glob("schema_*.sql"):
        shutil.copy(f, kopie / f.name)
    shutil.copytree(db_init.DB_DIR / "migrations", kopie / "migrations")
    monkeypatch.setattr(db_init, "SQL_DIR", kopie)
    monkeypatch.setattr(db_init, "MIGRATIONS_DIR", kopie / "migrations")
    return kopie


def _stil(f, *args, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*args, **kw)


def _versie(map: Path, database: str) -> int:
    with contextlib.closing(verbind(database, map, TESTSLEUTEL)) as c:
        return c.execute("SELECT MAX(versie) FROM schema_version").fetchone()[0]


def test_repo_is_compleet():
    controleer_sql_bestanden()                      # de echte bestanden in src/db


def test_kopie_werkt(sql_kopie, tmp_path):
    data = tmp_path / "data"
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    assert all((data / f"{d}.db").exists() for d in DATABASES)


@pytest.mark.parametrize("weg, melding", [
    ("schema_notities.sql", "schema_notities.sql ontbreekt"),
    ("migrations", "de map migrations/ ontbreekt"),
])
def test_ontbrekend_bestand(sql_kopie, tmp_path, weg, melding):
    pad = sql_kopie / weg
    shutil.rmtree(pad) if pad.is_dir() else pad.unlink()
    with pytest.raises(InstallatieFout, match=melding) as e:
        controleer_sql_bestanden()
    assert "Installeer AVS opnieuw" in str(e.value)

    data = tmp_path / "data"
    with pytest.raises(InstallatieFout):
        _stil(init_db, data, hoofd=TESTSLEUTEL)
    assert not data.exists() or not list(data.glob("*.db"))     # niets aangemaakt


def test_lege_of_dubbele_migratie(sql_kopie):
    (sql_kopie / "migrations" / "testen").mkdir(exist_ok=True)
    (sql_kopie / "migrations" / "testen" / "003_leeg.sql").write_text("  \n")
    with pytest.raises(InstallatieFout, match="003_leeg.sql is leeg"):
        controleer_sql_bestanden()
    (sql_kopie / "migrations" / "testen" / "003_leeg.sql").write_text("SELECT 1;")
    (sql_kopie / "migrations" / "testen" / "003_ook.sql").write_text("SELECT 1;")
    with pytest.raises(InstallatieFout, match="hetzelfde nummer"):
        controleer_sql_bestanden()


def _zet_versie(map: Path, database: str, versie: int) -> None:
    """Doe alsof een database op een andere versie staat (alleen schema_version)."""
    with contextlib.closing(verbind(database, map, TESTSLEUTEL)) as c, c:
        c.execute("DELETE FROM schema_version")
        c.execute("INSERT INTO schema_version (versie) VALUES (?)", (versie,))


def _nieuwe_migratie(sql_kopie: Path, database: str) -> int:
    """Een extra (onschuldige) migratie na de nieuwste versie. Geeft het nummer."""
    nummer = db_init.nieuwste_versie(database) + 1
    map_ = sql_kopie / "migrations" / database
    map_.mkdir(parents=True, exist_ok=True)
    (map_ / f"{nummer:03d}_test.sql").write_text("CREATE TABLE test_migratie (id INTEGER);")
    return nummer


def test_basisversie_uit_schema():
    """Elke database begint op de versie uit de laatste regel van zijn schema."""
    verwacht = {"personen": 11, "prestaties": 4, "testen": 2, "trainingsschema": 2,
                "absentie": 1, "leerlijnen": 1, "leerdoelscores": 1, "notities": 1}
    assert {d: db_init.basisversie(d) for d in DATABASES} == verwacht


def test_nieuwe_database_op_basisversie(sql_kopie, tmp_path):
    data = tmp_path / "data"
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    for d in DATABASES:
        assert _versie(data, d) == db_init.nieuwste_versie(d)
    _stil(init_db, data, hoofd=TESTSLEUTEL)           # nog een keer starten gaat ook goed
    assert _versie(data, "personen") == db_init.nieuwste_versie("personen")


def test_migratie_niet_na_basisversie(sql_kopie):
    """Een migratie met een nummer t/m de basisversie zou nergens draaien: weigeren."""
    map_ = sql_kopie / "migrations" / "personen"
    map_.mkdir(exist_ok=True)
    basis = db_init.basisversie("personen")
    (map_ / f"{basis:03d}_oude_branch.sql").write_text("SELECT 1;")
    with pytest.raises(InstallatieFout, match=f"{basis:03d}_oude_branch.sql heeft nummer {basis}"):
        controleer_sql_bestanden()
    (map_ / f"{basis:03d}_oude_branch.sql").rename(map_ / f"{basis + 1:03d}_nieuw.sql")
    controleer_sql_bestanden()                      # één hoger is goed


def test_geen_oude_migraties_meer():
    """De oude migraties zitten in de basisschema's; in de repo staan alleen nieuwere."""
    for d in DATABASES:
        assert all(n > db_init.basisversie(d) for n, _ in db_init._migraties(d)), d


def test_schema_zonder_versieregel(sql_kopie):
    schema = sql_kopie / "schema_testen.sql"
    schema.write_text(schema.read_text(encoding="utf-8").replace("INSERT INTO schema_version", "-- weg"),
                      encoding="utf-8")
    with pytest.raises(InstallatieFout, match="schema_testen.sql moet precies één regel"):
        controleer_sql_bestanden()


def test_database_nieuwer_dan_avs(sql_kopie, tmp_path):
    """Oudere AVS op nieuwere databases: weigeren vóór er iets wordt bijgewerkt."""
    data = tmp_path / "data"
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    prestaties_voor = _versie(data, "prestaties")
    _nieuwe_migratie(sql_kopie, "prestaties")       # prestaties.db kan nog worden bijgewerkt, maar
    te_nieuw = db_init.nieuwste_versie("personen") + 1
    _zet_versie(data, "personen", te_nieuw)         # personen.db komt van een nieuwere AVS
    with pytest.raises(InstallatieFout, match=f"personen.db is versie {te_nieuw}, maar deze AVS kent"):
        _stil(init_db, data, hoofd=TESTSLEUTEL)
    assert _versie(data, "prestaties") == prestaties_voor           # niet half bijgewerkt


def test_database_ouder_dan_basisversie(sql_kopie, tmp_path):
    """Een database van vóór het samenvoegen van de migraties: weigeren, niet stil overslaan."""
    data = tmp_path / "data"
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    prestaties_voor = _versie(data, "prestaties")
    _nieuwe_migratie(sql_kopie, "prestaties")
    te_oud = db_init.basisversie("personen") - 1
    _zet_versie(data, "personen", te_oud)
    with pytest.raises(InstallatieFout) as e:
        _stil(init_db, data, hoofd=TESTSLEUTEL)
    melding = str(e.value)
    assert f"personen.db is versie {te_oud}" in melding
    assert f"vanaf versie {db_init.basisversie('personen')}" in melding
    assert "vorige versie van AVS" in melding and "niet aangeraakt" in melding
    assert _versie(data, "prestaties") == prestaties_voor           # niets bijgewerkt
    assert _versie(data, "personen") == te_oud


def test_database_op_basisversie_krijgt_nieuwe_migratie(sql_kopie, tmp_path):
    """Precies de basisversie is goed: latere migraties worden gewoon toegepast."""
    data = tmp_path / "data"
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    nummer = _nieuwe_migratie(sql_kopie, "personen")
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    assert _versie(data, "personen") == nummer
    with contextlib.closing(verbind("personen", data, TESTSLEUTEL)) as c:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name = 'test_migratie'").fetchone()


def test_leeg_bestand_is_niet_te_oud(sql_kopie, tmp_path):
    """Versie 0 (bestand bestaat, nog geen tabellen) krijgt gewoon het basisschema."""
    data = tmp_path / "data"
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    db_init.db_pad("notities", data).unlink()
    verbind("notities", data, TESTSLEUTEL).close()  # lege, versleutelde database
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    assert _versie(data, "notities") == db_init.basisversie("notities")


def test_sql_map_in_de_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert db_init._sql_map() == tmp_path / "db"
    monkeypatch.delattr(sys, "frozen")
    assert db_init._sql_map() == db_init.DB_DIR


def test_app_bij_installatiefout():
    app = maak_app(startfout="AVS is niet volledig geïnstalleerd: de map migrations/ ontbreekt.",
                   sleutelfout=False)
    c = app.test_client()
    r = c.get("/atleten")
    html = r.get_data(as_text=True)
    assert r.status_code == 500 and "niet volledig geïnstalleerd" in html
    assert "Sleutel herstellen" not in html and "Naar atleten" in html
    html = c.get("/instellingen").get_data(as_text=True)
    assert "niet volledig geïnstalleerd" in html
    assert '<details class="sleutel__herstellen">' in html          # dicht: sleutel is het probleem niet


def test_start_bij_installatiefout(monkeypatch, tmp_path):
    from ui import app as app_mod
    gezien = {}

    def nep_init_db(map=None, hoofd=None):
        raise InstallatieFout("AVS is niet volledig geïnstalleerd: test.")

    def nep_maak_app(map=None, hoofd=None, startfout=None, sleutelfout=True):
        gezien.update(startfout=startfout, sleutelfout=sleutelfout)
        raise SystemExit                            # geen echte server starten

    monkeypatch.setattr(app_mod, "init_db", nep_init_db)
    monkeypatch.setattr(app_mod, "maak_app", nep_maak_app)
    with pytest.raises(SystemExit):
        _stil(app_mod.start, map=tmp_path, browser=False)
    assert gezien == {"startfout": "AVS is niet volledig geïnstalleerd: test.", "sleutelfout": False}
