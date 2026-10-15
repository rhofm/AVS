"""Tests voor src/db/queries.py, met echte (versleutelde) databases in een tijdelijke map.

Gebruikt een vaste testsleutel: raakt de sleutelkluis en data/ nooit aan.
Alleen nepgegevens. Werkt met pytest en ook los: `python tests/test_queries.py`.
Vereist: pip install sqlcipher3-wheels keyring
"""

import contextlib
import io
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from db.init_db import init_db, pseudoniem  # noqa: E402
from db.queries import Opslag, OpslagFout  # noqa: E402
from models import (  # noqa: E402
    Absentie, Atleet, Groep, Inschrijving, Leerlijn, LeerlijnStap, LeerlijnVoortgang,
    Onderdeel, Periodeplan, Prestatie, Test, Testresultaat, Training, Wedstrijd,
)

TESTSLEUTEL = "11" * 32


@contextlib.contextmanager
def opslag():
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):  # init_db print meldingen
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            yield db


def _verwacht(fout, fn) -> None:
    try:
        fn()
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


def _basis(db: Opslag):
    anna = db.atleet_opslaan(Atleet("Anna", "Voorbeeld", geslacht="V", geboortedatum="2010", atletieknu_id="123456"))
    tim = db.atleet_opslaan(Atleet("Tim", "Proefmans", geslacht="M"))
    sprint = db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
    ver = db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
    return anna, tim, sprint, ver


def test_atleten():
    with opslag() as db:
        anna, tim, _, _ = _basis(db)
        assert len(anna.master_id) == 32 and anna.aangemaakt_op
        assert db.atleet(anna.master_id).naam == "Anna Voorbeeld"
        assert db.atleet_op_atletieknu_id("123456").master_id == anna.master_id
        assert [a.voornaam for a in db.atleten_zoeken("proef")] == ["Tim"]

        tim.actief = False
        tim.specialisatie = "sprint"
        db.atleet_opslaan(tim)
        assert db.atleet(tim.master_id).specialisatie == "sprint"
        assert [a.voornaam for a in db.atleten()] == ["Anna"]
        assert len(db.atleten(alleen_actief=False)) == 2


def test_prestaties_geen_master_id_of_naam_in_prestaties_db():
    with opslag() as db:
        anna, _, sprint, _ = _basis(db)
        p = Prestatie("100m", date(2026, 6, 1), 13.2, bron="handmatig").gekoppeld(anna.master_id)
        assert db.prestatie_opslaan(p)
        rij = db.prestaties_db.execute("SELECT * FROM prestatie").fetchone()
        assert rij["atleet_ref"] == pseudoniem(anna.master_id, "prestaties", TESTSLEUTEL)
        assert anna.master_id not in [str(v) for v in tuple(rij)]


def test_prestaties_en_prs():
    with opslag() as db:
        anna, tim, sprint, ver = _basis(db)
        w = db.wedstrijd_opslaan(Wedstrijd("Clubkampioenschap", date(2026, 6, 1), bron="atletieknu",
                                           bron_url="https://example.org/wedstrijd/1"))
        # Dezelfde link nog eens: zelfde wedstrijd.
        assert db.wedstrijd_opslaan(Wedstrijd("x", date(2026, 6, 1), bron_url=w.bron_url)).id == w.id

        ps = [
            Prestatie("100m", date(2026, 6, 1), 13.2, wedstrijd_id=w.id, ronde="serie"),
            Prestatie("100m", date(2026, 6, 1), 12.9, wedstrijd_id=w.id, ronde="finale"),
            Prestatie("Verspringen", date(2026, 6, 1), 4.5, wedstrijd_id=w.id),
            Prestatie("Verspringen", date(2026, 7, 1), 4.8),
        ]
        assert db.prestaties_opslaan(p.gekoppeld(anna.master_id) for p in ps) == (4, 0)
        # Zelfde import nog eens: niets dubbel.
        assert db.prestaties_opslaan(p.gekoppeld(anna.master_id) for p in ps) == (0, 4)
        assert db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 13.5).gekoppeld(tim.master_id))

        assert len(db.prestaties(anna.master_id)) == 4
        assert sorted(p.waarde for p in db.prestaties(anna.master_id, sprint.id)) == [12.9, 13.2]
        assert db.prestaties(anna.master_id)[0].datum == date(2026, 7, 1)  # nieuwste eerst

        prs = {pr.onderdeel_id: pr.waarde for pr in db.prs(anna.master_id)}
        assert prs == {sprint.id: 12.9, ver.id: 4.8}

        groep = db.prs_van_groep([anna.master_id, tim.master_id], sprint.id)
        assert [(pr.atleet_id, pr.waarde) for pr in groep] == [(anna.master_id, 12.9), (tim.master_id, 13.5)]

        van_wedstrijd = db.prestaties_van_wedstrijd(w.id)
        assert len(van_wedstrijd) == 3 and {p.atleet_id for p in van_wedstrijd} == {anna.master_id}


def test_prestatie_fouten():
    with opslag() as db:
        anna, _, _, _ = _basis(db)
        _verwacht(OpslagFout, lambda: db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 13.0)))
        _verwacht(OpslagFout, lambda: db.prestatie_opslaan(
            Prestatie("Hamerslingeren", date(2026, 6, 1), 30.0).gekoppeld(anna.master_id)))
        _verwacht(OpslagFout, lambda: db.prestatie_opslaan(
            Prestatie("100m", date(2026, 6, 1), 13.0, wedstrijd_id=999).gekoppeld(anna.master_id)))


def test_inschrijvingen():
    with opslag() as db:
        anna, _, sprint, _ = _basis(db)
        w = db.wedstrijd_opslaan(Wedstrijd("Competitie", date(2026, 9, 1)))
        for _ in range(2):
            db.inschrijving_opslaan(Inschrijving(anna.master_id, w.id))
            db.inschrijving_opslaan(Inschrijving(anna.master_id, w.id, sprint.id))
        assert len(db.inschrijvingen(anna.master_id)) == 2
        _verwacht(OpslagFout, lambda: db.inschrijving_opslaan(Inschrijving(anna.master_id, 999)))


def test_testen():
    with opslag() as db:
        anna, _, _, _ = _basis(db)
        t = db.test_opslaan(Test("30m vliegend", "s", True))
        db.testresultaat_opslaan(Testresultaat(anna.master_id, t.id, date(2026, 10, 1), 3.9))
        db.testresultaat_opslaan(Testresultaat(anna.master_id, t.id, date(2026, 9, 1), 4.1))
        assert [r.waarde for r in db.testresultaten(anna.master_id, t.id)] == [4.1, 3.9]  # oudste eerst
        rij = db.testen_db.execute("SELECT atleet_ref FROM testresultaat").fetchone()
        # Ander pseudoniem dan in prestaties.db.
        assert rij[0] == pseudoniem(anna.master_id, "testen", TESTSLEUTEL)
        assert rij[0] != pseudoniem(anna.master_id, "prestaties", TESTSLEUTEL)


def test_groepen_trainingen_absentie():
    with opslag() as db:
        anna, tim, _, _ = _basis(db)
        g = db.groep_opslaan(Groep("Junioren C", "2026-2027", [anna.master_id, tim.master_id]))
        assert db.groep(g.id).leden == [tim.master_id, anna.master_id]  # op achternaam
        g.verwijder(tim.master_id)
        db.groep_opslaan(g)
        assert db.groep(g.id).leden == [anna.master_id]
        assert [x.naam for x in db.groepen_van_atleet(anna.master_id)] == ["Junioren C"]

        plan = db.periodeplan_opslaan(Periodeplan("AV", date(2026, 10, 1), date(2026, 11, 30), g.id))
        tr = db.training_opslaan(Training(g.id, date(2026, 10, 14), "Starts", periodeplan_id=plan.id))
        db.absentie_opslaan(Absentie(tr.id, anna.master_id, "afgemeld", "school"))
        db.absentie_opslaan(Absentie(tr.id, anna.master_id, "aanwezig"))  # bijwerken
        assert [(a.status, a.reden) for a in db.absenties(tr.id)] == [("aanwezig", None)]
        assert len(db.trainingen(g.id, van=date(2026, 10, 1))) == 1
        assert db.periodeplannen(g.id)[0].aantal_weken == 9


def test_leerlijnen():
    with opslag() as db:
        anna, _, _, _ = _basis(db)
        lijn = db.leerlijn_opslaan(Leerlijn("Sprint", stappen=[
            LeerlijnStap(1, "Armactie"), LeerlijnStap(2, "Blokstart")]))
        terug = db.leerlijn(lijn.id)
        assert [s.naam for s in terug.stappen] == ["Armactie", "Blokstart"]
        db.voortgang_opslaan(LeerlijnVoortgang(anna.master_id, terug.stappen[0].id, date(2026, 9, 1)))
        behaald = {v.stap_id for v in db.voortgang(anna.master_id) if v.behaald}
        assert terug.volgende_stap(behaald).naam == "Blokstart"


def test_atleet_verwijderen_wist_alles():
    with opslag() as db:
        anna, tim, sprint, _ = _basis(db)
        db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 12.9).gekoppeld(anna.master_id))
        db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 13.5).gekoppeld(tim.master_id))
        t = db.test_opslaan(Test("30m vliegend", "s", True))
        db.testresultaat_opslaan(Testresultaat(anna.master_id, t.id, date(2026, 10, 1), 3.9))
        g = db.groep_opslaan(Groep("C", leden=[anna.master_id, tim.master_id]))

        db.atleet_verwijderen(anna.master_id)
        assert db.atleet(anna.master_id) is None
        assert db.prestaties(anna.master_id) == []
        assert db.testresultaten(anna.master_id) == []
        assert db.groep(g.id).leden == [tim.master_id]
        assert len(db.prestaties(tim.master_id)) == 1  # Tim blijft


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
