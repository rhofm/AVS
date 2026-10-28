"""Tests voor src/zelftest.py en de opties van src/__main__.py.

De zelftest mag nooit de echte gegevens of de sleutelkluis aanraken; dat wordt hier
afgedwongen door beide te laten ontploffen als ze toch worden gebruikt. Werkt met pytest.
"""

import importlib.util
import io
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import zelftest
from db import init_db as db_init


def _main_module():
    spec = importlib.util.spec_from_file_location("avs_main", SRC / "__main__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def niets_echts(monkeypatch, tmp_path):
    """Sleutelkluis en datamap verboden terrein; geeft de (verboden) datamap."""
    def verboden(*a, **kw):
        raise AssertionError("de zelftest raakte de sleutelkluis aan")
    monkeypatch.setattr(db_init, "_lees_hoofdsleutel", verboden)
    monkeypatch.setattr(db_init, "_bewaar_hoofdsleutel", verboden)
    datamap = tmp_path / "echte_data"
    monkeypatch.setenv("AVS_DATA", str(datamap))
    return datamap


def _draai(**kw) -> tuple[int, str]:
    uit = io.StringIO()
    code = zelftest.zelftest(uitvoer=uit, **kw)
    return code, uit.getvalue()


def test_eigen_modules():
    namen = zelftest.eigen_modules()
    assert {"db.init_db", "ploeg.regels", "ploeg.strategieen.max_punten", "ui.app", "db", "ploeg"} <= set(namen)
    assert not any(n in ("__main__", "zelftest") or "__pycache__" in n or n.endswith("__init__") for n in namen)
    assert namen == sorted(namen)


def test_modulelijst(tmp_path):
    pad = zelftest.schrijf_modulelijst(tmp_path / zelftest.MODULELIJST)
    assert pad.read_text(encoding="utf-8").split() == zelftest.eigen_modules()


def test_alles_in_orde(niets_echts):
    code, tekst = _draai()
    assert code == 0, tekst
    assert "Alles in orde." in tekst and "FOUT" not in tekst
    assert tekst.count("  ok    ") == len(zelftest.controles(Path(".")))
    assert not niets_echts.exists()                       # datamap niet aangeraakt


def test_een_fout_en_de_rest_gaat_door(niets_echts, monkeypatch):
    def kapot():
        raise ImportError("No module named 'fpdf'")
    monkeypatch.setattr(zelftest, "_pdf", kapot)
    code, tekst = _draai()
    assert code == 1
    assert "  FOUT  PDF: ImportError: No module named 'fpdf'" in tekst
    assert "  ok    webinterface" in tekst                 # na de fout gewoon verder
    assert "1 controle(s) mislukt." in tekst


def test_details_toont_traceback(niets_echts, monkeypatch):
    monkeypatch.setattr(zelftest, "_pdf", lambda: 1 / 0)
    _, tekst = _draai(details=True)
    assert "Traceback" in tekst and "ZeroDivisionError" in tekst


def test_in_de_exe_zonder_modulelijst(niets_echts, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(RuntimeError, match="zelftest_modules.txt ontbreekt"):
        zelftest._modules()


def test_in_de_exe_ontbrekende_module(niets_echts, monkeypatch, tmp_path):
    (tmp_path / zelftest.MODULELIJST).write_text("ploeg.regels\nploeg.bestaat_niet\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(RuntimeError, match=r"ploeg\.bestaat_niet \(ModuleNotFoundError"):
        zelftest._modules()


def test_onversleutelde_database_valt_op(niets_echts, monkeypatch, tmp_path):
    echte_init_db = db_init.init_db

    def zonder_sleutel(map=None, hoofd=None):
        echte_init_db(map, hoofd=hoofd)
        (Path(map) / "personen.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    class NepOpslag:                                       # openen weigert een kale database al;
        def __init__(self, **kw): ...                      # hier gaat het om de extra controle erna
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def atleten(self): return []
    monkeypatch.setattr(db_init, "init_db", zonder_sleutel)
    monkeypatch.setattr("db.queries.Opslag", NepOpslag)
    with pytest.raises(RuntimeError, match="NIET versleuteld"):
        zelftest._databases(tmp_path / "d")


# ---------------- __main__ ----------------
def test_main_opties(monkeypatch):
    main = _main_module()
    gestart = []
    monkeypatch.setattr("ui.app.start", lambda browser=True, map=None: gestart.append(browser))
    assert main.main([]) == 0 and main.main(["--geen-browser"]) == 0
    assert gestart == [True, False]

    monkeypatch.setattr(zelftest, "zelftest", lambda details=False: 7 if details else 3)
    assert main.main(["--zelftest"]) == 3 and main.main(["--zelftest", "--details"]) == 7
    assert gestart == [True, False]                       # zelftest start geen server

    with pytest.raises(SystemExit):
        main.main(["--onbekend"])


# ---------------- sleutelkluis niet bruikbaar ----------------
def test_kapotte_sleutelkluis_geeft_nette_fout(monkeypatch, tmp_path):
    """Zonder bruikbare sleutelkluis: InstallatieFout met uitleg, geen traceback; geen 'Sleutel herstellen'."""
    import contextlib
    import keyring
    from keyring.errors import NoKeyringError
    from db.init_db import SleutelFout, SleutelkluisFout, init_db
    from ui import app as app_mod

    def kapot(*a, **kw):
        raise NoKeyringError("geen backend; interne details")
    monkeypatch.setattr(keyring, "get_password", kapot)
    monkeypatch.setattr(keyring, "set_password", kapot)
    with pytest.raises(SleutelkluisFout, match="Referentiebeheer") as e, contextlib.redirect_stdout(io.StringIO()):
        init_db(tmp_path)
    assert not isinstance(e.value, SleutelFout) and "interne details" not in str(e.value)

    gezien = {}

    def nep_maak_app(map=None, hoofd=None, startfout=None, sleutelfout=True):
        gezien.update(startfout=startfout, sleutelfout=sleutelfout)
        raise SystemExit
    monkeypatch.setattr(app_mod, "maak_app", nep_maak_app)
    with pytest.raises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
        app_mod.start(map=tmp_path, browser=False)
    assert "Referentiebeheer" in gezien["startfout"] and gezien["sleutelfout"] is False


def test_kapotte_sleutelkluis_tijdens_gebruik(monkeypatch, tmp_path):
    import contextlib
    import keyring
    from keyring.errors import KeyringError
    from db.init_db import init_db
    from ui.app import maak_app
    with contextlib.redirect_stdout(io.StringIO()):
        init_db(tmp_path, hoofd="6e" * 32)

    def kapot(*a, **kw):
        raise KeyringError("weg")
    monkeypatch.setattr(keyring, "get_password", kapot)
    app = maak_app(map=tmp_path)                          # geen testsleutel: elke pagina leest de kluis
    r = app.test_client().get("/atleten")
    tekst = r.get_data(as_text=True)
    assert r.status_code == 500 and "AVS kan je gegevens niet openen" in tekst and "Referentiebeheer" in tekst
