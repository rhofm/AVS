"""Tests voor starttijden van groepen (personen.db, migratie 003) en groepen/groep.py.

Een groep heeft per weekdag een starttijd of niets; leden staan in groep_lid
(lang formaat). Een atleet kan in meerdere groepen zitten. Alleen nepgegevens
en een vaste testsleutel. Werkt met pytest en los: `python tests/test_groep_starttijden.py`.
"""

import contextlib
import io
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atleten import trainingsschema as schema_pagina  # noqa: E402
from db.init_db import DB_DIR, huidige_versie, init_db, verbind  # noqa: E402
from db.queries import Opslag, OpslagFout  # noqa: E402
from groepen import groep as groepsbeheer  # noqa: E402
from models import Atleet, Groep, Trainingsschema, normaliseer_tijd  # noqa: E402

TESTSLEUTEL = "44" * 32


@contextlib.contextmanager
def opslag():
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            yield db


def _verwacht(fout, fn) -> None:
    try:
        fn()
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


def _basis(db):
    anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
    bas = db.atleet_opslaan(Atleet("Bas", "Bakker"))
    sprint = db.groep_opslaan(Groep("Sprintgroep", starttijden={"dinsdag": "18:30", "donderdag": "18:30"}))
    junioren = db.groep_opslaan(Groep("Junioren C", starttijden={"donderdag": "19:30", "zaterdag": "9:00"}))
    return anna, bas, sprint, junioren


def test_tijden_normaliseren():
    assert normaliseer_tijd("9:00") == "09:00" and normaliseer_tijd(" 18.30 ") == "18:30"
    assert normaliseer_tijd("") is None and normaliseer_tijd(None) is None
    for fout in ("24:00", "18:60", "half zeven", "1830"):
        _verwacht(ValueError, lambda f=fout: normaliseer_tijd(f))
    g = Groep("X", starttijden={"Zaterdag": "9:00", "dinsdag": "18:30", "woensdag": ""})
    assert g.starttijden == {"dinsdag": "18:30", "zaterdag": "09:00"}      # vaste volgorde, lege dag weg
    assert g.trainingsdagen == ["dinsdag", "zaterdag"] and g.starttijd("Dinsdag") == "18:30"
    _verwacht(ValueError, lambda: Groep("X", starttijden={"weekend": "10:00"}))


def test_opslaan_en_meerdere_groepen():
    with opslag() as db:
        anna, bas, sprint, junioren = _basis(db)
        assert db.groep(sprint.id).starttijden == {"dinsdag": "18:30", "donderdag": "18:30"}
        assert db.groep(junioren.id).starttijden == {"donderdag": "19:30", "zaterdag": "09:00"}
        # Een atleet in twee groepen.
        groepsbeheer.leden_opslaan(db, sprint.id, [anna.master_id])
        groepsbeheer.leden_opslaan(db, junioren.id, [anna.master_id, bas.master_id])
        assert sorted(g.naam for g in db.groepen_van_atleet(anna.master_id)) == ["Junioren C", "Sprintgroep"]
        assert db.personen.execute("SELECT count(*) FROM groep_lid").fetchone()[0] == 3   # lang: rij per lid
        # Tijden staan één keer per groep, niet per lid.
        assert db.personen.execute("SELECT count(*) FROM groep WHERE dinsdag = '18:30'").fetchone()[0] == 1
        # De database weigert een ongeldige tijd, ook buiten het model om.
        _verwacht(Exception, lambda: db.personen.execute("UPDATE groep SET maandag = '25:00' WHERE id = ?",
                                                         (sprint.id,)))


def test_lid_worden_vult_trainingsschema_aan():
    with opslag() as db:
        anna, bas, sprint, junioren = _basis(db)
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["maandag"]))   # eigen dag blijft
        w = groepsbeheer.leden_opslaan(db, sprint.id, [anna.master_id])
        assert [a.naam for a in w.schema_aangevuld] == ["Anna Aalbers"]
        assert "Trainingsschema aangevuld" in w.tekst
        assert db.trainingsschema(anna.master_id).dagen == ["maandag", "dinsdag", "donderdag"]

        groepsbeheer.leden_opslaan(db, junioren.id, [anna.master_id])
        assert db.trainingsschema(anna.master_id).dagen == ["maandag", "dinsdag", "donderdag", "zaterdag"]

        # Uit de groep: schema blijft staan (kan per atleet verschillen).
        w = groepsbeheer.leden_opslaan(db, junioren.id, [])
        assert w.schema_aangevuld == [] and "zaterdag" in db.trainingsschema(anna.master_id).dagen

        # Groep zonder tijden: niets aangevuld, melding zoals voorheen.
        leeg = db.groep_opslaan(Groep("Zonder tijden"))
        w = groepsbeheer.leden_opslaan(db, leeg.id, [bas.master_id])
        assert w.schema_aangevuld == [] and "Trainingsschema" not in w.tekst


def test_starttijden_wijzigen():
    with opslag() as db:
        anna, bas, sprint, _ = _basis(db)
        groepsbeheer.leden_opslaan(db, sprint.id, [anna.master_id, bas.master_id])
        w = groepsbeheer.starttijden_opslaan(db, sprint.id, {"dinsdag": "18:45", "vrijdag": "17:00"})
        assert (w.erbij, w.eraf, w.gewijzigd) == (["vrijdag"], ["donderdag"], ["dinsdag"])
        assert w.schema_aangevuld == 2 and "donderdag vervalt" in w.tekst
        assert db.groep(sprint.id).starttijden == {"dinsdag": "18:45", "vrijdag": "17:00"}
        assert db.trainingsschema(bas.master_id).dagen == ["dinsdag", "donderdag", "vrijdag"]   # niets eraf

        assert groepsbeheer.starttijden_opslaan(db, sprint.id, {"dinsdag": "18:45", "vrijdag": "17:00"}).leeg
        _verwacht(OpslagFout, lambda: groepsbeheer.starttijden_opslaan(db, sprint.id, {"dinsdag": "25:00"}))
        assert db.groep(sprint.id).starttijden["dinsdag"] == "18:45"                         # niets opgeslagen
        _verwacht(OpslagFout, lambda: groepsbeheer.starttijden_opslaan(db, 999, {}))


def test_rooster_en_schemapagina():
    with opslag() as db:
        anna, _, sprint, junioren = _basis(db)
        groepsbeheer.leden_opslaan(db, sprint.id, [anna.master_id])
        groepsbeheer.leden_opslaan(db, junioren.id, [anna.master_id])
        assert [(r.dag, r.tijd, r.groep) for r in groepsbeheer.rooster(db, anna.master_id)] == [
            ("dinsdag", "18:30", "Sprintgroep"),
            ("donderdag", "18:30", "Sprintgroep"),
            ("donderdag", "19:30", "Junioren C"),
            ("zaterdag", "09:00", "Junioren C"),
        ]
        per_dag = schema_pagina.groepsdagen(db, anna.master_id, date(2026, 10, 16))
        assert per_dag["donderdag"] == ["Junioren C 19:30", "Sprintgroep 18:30"]   # groepen op naam
        assert per_dag["maandag"] == []


def test_bestaande_groepen_krijgen_kolommen():
    """Een personen.db van vóór migratie 003: groepen blijven bestaan, zonder tijden."""
    with tempfile.TemporaryDirectory() as tmp:
        with verbind("personen", Path(tmp), TESTSLEUTEL) as c:
            c.executescript((DB_DIR / "schema_personen.sql").read_text(encoding="utf-8"))
            c.execute("INSERT INTO groep (naam, seizoen) VALUES ('Oude groep', '2025-2026')")
            c.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with verbind("personen", Path(tmp), TESTSLEUTEL) as c:
            assert huidige_versie(c) == 3
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            oud = db.groepen()[0]
            assert (oud.naam, oud.starttijden) == ("Oude groep", {})
            groepsbeheer.starttijden_opslaan(db, oud.id, {"woensdag": "18:00"})
            assert db.groep(oud.id).starttijden == {"woensdag": "18:00"}


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
