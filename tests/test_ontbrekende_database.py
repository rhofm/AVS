"""Een ontbrekend databasebestand (verloren, niet meegekopieerd) mag nooit stil een lege database worden.

init_db() weigert met OntbrekendeDatabase; de foutpagina biedt 'Toch leeg beginnen' (met vinkje).
verbind() maakt alleen een bestand als init_db() daarom vraagt. Alleen nepgegevens, vaste testsleutel.
"""

import contextlib
import io

import pytest

from db import init_db as db_init
from db.init_db import InstallatieFout, OntbrekendeDatabase, db_pad, init_db, verbind
from db.queries import Opslag
from hulp import SLEUTEL, TESTSLEUTEL, app_zonder_sleutel, lege_databases
from ui.app import maak_app


@pytest.fixture
def map_met_anna(tmp_path):
    lege_databases(tmp_path)
    from atleten import beheer
    with Opslag(map=tmp_path, hoofd=TESTSLEUTEL) as db:
        beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2011-03-14")
    return tmp_path


def _init(map, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return init_db(map, hoofd=TESTSLEUTEL, **kw)


# ---------------- init_db ----------------
def test_eerste_start_maakt_alles(tmp_path):
    _init(tmp_path)
    assert all(db_pad(d, tmp_path).exists() for d in db_init.DATABASES)


@pytest.mark.parametrize("weg", ["prestaties", "personen", "notities"])
def test_ontbrekend_bestand_wordt_geweigerd(map_met_anna, weg):
    db_pad(weg, map_met_anna).unlink()
    with pytest.raises(OntbrekendeDatabase) as e:
        _init(map_met_anna)
    assert e.value.ontbrekend == [weg] and f"{weg}.db" in str(e.value) and "reservekopie" in str(e.value)
    assert not db_pad(weg, map_met_anna).exists()                  # niets stil aangemaakt


def test_bewust_leeg_beginnen(map_met_anna):
    db_pad("prestaties", map_met_anna).unlink()
    db_pad("testen", map_met_anna).unlink()
    with pytest.raises(OntbrekendeDatabase) as e:
        _init(map_met_anna, lege_toestaan=["prestaties"])          # testen ontbreekt ook nog
    assert e.value.ontbrekend == ["testen"] and not db_pad("prestaties", map_met_anna).exists()
    _init(map_met_anna, lege_toestaan=["prestaties", "testen"])
    with Opslag(map=map_met_anna, hoofd=TESTSLEUTEL) as db:
        assert [a.naam for a in db.atleten()] == ["Anna Voorbeeld"]   # de rest is er nog
        assert db.testen() == []


def test_oude_installatie_hoort_eerst_over_de_versie(map_met_anna):
    """Een installatie van vóór de samenvoeging mist misschien een database die toen nog niet
    bestond. Dan geldt 'start eerst de vorige AVS', niet 'bestand verloren'."""
    from hulp import zet_versie
    zet_versie(map_met_anna, "personen", db_init.basisversie("personen") - 1)
    db_pad("trainingsschema", map_met_anna).unlink()
    with pytest.raises(InstallatieFout) as e:
        _init(map_met_anna)
    assert not isinstance(e.value, OntbrekendeDatabase) and "vorige versie van AVS" in str(e.value)


def test_nieuwe_database_na_een_update_mag_ontbreken(map_met_anna, monkeypatch):
    monkeypatch.setattr(db_init, "NIEUW_NA_BASIS", frozenset({"notities"}))
    db_pad("notities", map_met_anna).unlink()
    _init(map_met_anna)
    assert db_pad("notities", map_met_anna).exists()


@pytest.fixture
def onderbroken_eerste_start(tmp_path, monkeypatch):
    """Een datamap waarin de allereerste start halverwege leerlijnen.db stopte: personen ...
    absentie zijn er, leerlijnen is leeg, leerdoelscores en notities zijn er nog niet."""
    import shutil
    echt = db_init.SQL_DIR
    kapot = tmp_path / "sql"
    shutil.copytree(echt, kapot)
    schema = kapot / "schema_leerlijnen.sql"
    schema.write_text(schema.read_text(encoding="utf-8").replace(
        "INSERT INTO schema_version", "SELECT * FROM bestaat_niet;\nINSERT INTO schema_version"), encoding="utf-8")
    monkeypatch.setattr(db_init, "SQL_DIR", kapot)
    data = tmp_path / "data"
    with pytest.raises(Exception, match="bestaat_niet"):
        _init(data)
    monkeypatch.setattr(db_init, "SQL_DIR", echt)
    assert db_pad("personen", data).exists() and not db_pad("notities", data).exists()
    assert (data / db_init.EERSTE_START).exists()
    return data


def test_onderbroken_eerste_start_maakt_de_volgende_start_af(onderbroken_eerste_start):
    """Geen 'databases verloren' (er waren nog geen gegevens), en geen halve leerlijnen.db: het
    basisschema gaat in één transactie (anders 'UNIQUE constraint failed' op de catalogus)."""
    data = onderbroken_eerste_start
    assert db_init.ontbrekende_databases(data) == []
    _init(data)
    assert all(db_pad(d, data).exists() for d in db_init.DATABASES)
    assert not (data / db_init.EERSTE_START).exists()
    with Opslag(map=data, hoofd=TESTSLEUTEL) as db:
        assert db.leerdoel("SPR-U10-01") is not None


def test_eerste_start_laat_geen_markering_achter(tmp_path):
    _init(tmp_path)
    assert not (tmp_path / db_init.EERSTE_START).exists()
    db_pad("notities", tmp_path).unlink()           # daarna is een ontbrekend bestand wél verloren
    with pytest.raises(OntbrekendeDatabase):
        _init(tmp_path)


# ---------------- verbind ----------------
def test_verbind_maakt_niets_aan(map_met_anna):
    db_pad("absentie", map_met_anna).unlink()
    with pytest.raises(InstallatieFout, match="absentie.db ontbreekt"):
        verbind("absentie", map_met_anna, TESTSLEUTEL)
    assert not db_pad("absentie", map_met_anna).exists()
    with pytest.raises(InstallatieFout):
        Opslag(map=map_met_anna, hoofd=TESTSLEUTEL)               # ook niet halverwege het gebruik
    verbind("absentie", map_met_anna, TESTSLEUTEL, aanmaken=True).close()
    assert db_pad("absentie", map_met_anna).exists()


# ---------------- de foutpagina en de knop ----------------
def _app_met_ontbrekend(map):
    try:
        _init(map)
        raise AssertionError("init_db had moeten weigeren")
    except OntbrekendeDatabase as e:
        app = maak_app(map=map, hoofd=TESTSLEUTEL, startfout=str(e), sleutelfout=False, ontbrekend=e.ontbrekend)
    app.config["TESTING"] = True
    return app.test_client()


def test_foutpagina_en_toch_leeg_beginnen(map_met_anna):
    db_pad("prestaties", map_met_anna).unlink()
    c = _app_met_ontbrekend(map_met_anna)
    r = c.get("/atleten")
    html = r.get_data(as_text=True)
    assert r.status_code == 500 and "prestaties.db" in html and "Toch leeg beginnen" in html

    r = c.post("/databases/leeg-beginnen")                          # zonder vinkje: niets
    assert r.status_code == 400 and "Vink eerst aan" in r.get_data(as_text=True)
    assert not db_pad("prestaties", map_met_anna).exists()

    r = c.post("/databases/leeg-beginnen", data={"zeker": "1"}, follow_redirects=True)
    tekst = r.get_data(as_text=True)
    assert r.status_code == 200 and "Anna" in tekst and "een lege prestaties.db" in tekst
    assert db_pad("prestaties", map_met_anna).exists()
    assert c.get("/wedstrijden").status_code == 200


def test_knop_alleen_bij_ontbrekend_bestand(tmp_path):
    app = maak_app(map=tmp_path, startfout="iets anders", sleutelfout=False)
    app.config["TESTING"] = True
    c = app.test_client()
    assert "Toch leeg beginnen" not in c.get("/atleten").get_data(as_text=True)
    assert c.post("/databases/leeg-beginnen", data={"zeker": "1"}).status_code == 302   # doet niets
    assert not any(tmp_path.iterdir())


def test_sleutel_herstellen_en_dan_ontbrekend_bestand(kluis, data):
    db_pad("leerdoelscores", data).unlink()
    c = app_zonder_sleutel(data)
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": SLEUTEL})
    assert r.status_code == 302 and kluis["sleutel"] == bytes.fromhex(SLEUTEL)
    html = c.get("/atleten").get_data(as_text=True)
    assert "leerdoelscores.db" in html and "Toch leeg beginnen" in html
    assert not db_pad("leerdoelscores", data).exists()
