"""Tests voor leerlijnen.db (leerdoelen) en leerdoelscores.db, met echte versleutelde databases.

Alleen nepgegevens en een vaste testsleutel.
"""

import contextlib
import io
import tempfile
from datetime import date
from pathlib import Path

from db.init_db import init_db, pseudoniem, verbind
from db.queries import Opslag, OpslagFout
from models import CATEGORIEEN, Atleet, Leerdoel, LeerdoelScore
from hulp import TESTSLEUTEL, opslag


def _verwacht_fout(fout, functie, *args):
    try:
        functie(*args)
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


# ---------- catalogus ----------
def test_catalogus_gevuld_en_gesorteerd():
    with opslag() as db:
        alle = db.leerdoelen()
        assert len(alle) == 215
        assert {d.categorie for d in alle} == set(CATEGORIEEN)
        cats = [CATEGORIEEN.index(d.categorie) for d in alle]
        assert cats == sorted(cats)                                   # gesorteerd op leeftijd
        assert len({d.id for d in alle}) == len(alle)                 # unieke ids
        assert alle[0].id == "SPR-U10-01"
        assert {d.bron for d in alle} == {"NA", "AU"}
        assert sum(d.bron == "NA" for d in alle) == 98                # volledige clubleerlijn


def test_ids_volgen_leerlijn_en_categorie():
    with opslag() as db:
        for d in db.leerdoelen():
            assert d.id == f"{d.leerlijn}-{d.categorie}-{d.volgorde:02d}"


def test_filter_categorie_doorlopend_en_leerlijn():
    with opslag() as db:
        u12 = db.leerdoelen("U12")
        assert u12 and all(d.categorie == "U12" for d in u12)
        tot_u12 = db.leerdoelen("U12", doorlopend=True)
        assert len(tot_u12) == len(db.leerdoelen("U10")) + len(u12)
        sprint = db.leerdoelen(leerlijn="SPR")
        assert [d.id for d in sprint][:2] == ["SPR-U10-01", "SPR-U10-02"]
        _verwacht_fout(OpslagFout, db.leerdoelen, "U11")


def test_specialisten_en_scoreschaal():
    with opslag() as db:
        spec = [d.id for d in db.leerdoelen() if d.alleen_specialisten]
        assert spec == ["HOR-U16-02", "HOR-U16-03", "HOR-U16-04"]
        assert db.scoreschaal() == {1: "Nog niet", 2: "Beginnend", 3: "In ontwikkeling",
                                    4: "Zelfstandig", 5: "Beheerst"}
        assert db.leerdoel_leerlijnen()[0] == ("SPR", "Sprint")


def test_geldt_voor():
    d = Leerdoel("VER-U12-01", "VER", "U12", 1, "x")
    assert not d.geldt_voor("U10") and d.geldt_voor("U12") and d.geldt_voor("U18")


# ---------- scores ----------
def test_scores_lang_formaat_met_geschiedenis():
    with opslag() as db:
        anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
        db.leerdoelscores_opslaan([
            LeerdoelScore(anna.master_id, "SPR-U10-01", 2, date(2026, 9, 1)),
            LeerdoelScore(anna.master_id, "SPR-U10-01", 4, date(2026, 10, 1), "start nu vlot"),
            LeerdoelScore(anna.master_id, "HOO-U10-02", 3, date(2026, 9, 15)),
        ])
        geschiedenis = db.leerdoelscores(anna.master_id, "SPR-U10-01")
        assert [(s.datum, s.score) for s in geschiedenis] == [(date(2026, 9, 1), 2), (date(2026, 10, 1), 4)]
        laatste = db.laatste_leerdoelscores(anna.master_id)
        assert {k: (v.score, v.datum) for k, v in laatste.items()} == {
            "SPR-U10-01": (4, date(2026, 10, 1)), "HOO-U10-02": (3, date(2026, 9, 15))}
        assert laatste["SPR-U10-01"].notities == "start nu vlot"


def test_zelfde_dag_overschrijft():
    with opslag() as db:
        anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
        db.leerdoelscore_opslaan(LeerdoelScore(anna.master_id, "SPR-U10-01", 2, date(2026, 9, 1)))
        db.leerdoelscore_opslaan(LeerdoelScore(anna.master_id, "SPR-U10-01", 3, date(2026, 9, 1)))
        assert [s.score for s in db.leerdoelscores(anna.master_id)] == [3]
        db.leerdoelscore_verwijderen(anna.master_id, "SPR-U10-01", date(2026, 9, 1))
        assert db.leerdoelscores(anna.master_id) == []


def test_breed_overzicht():
    with opslag() as db:
        anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
        bas = db.atleet_opslaan(Atleet("Bas", "Bakker"))
        db.leerdoelscores_opslaan([
            LeerdoelScore(anna.master_id, "SPR-U10-01", 2, date(2026, 9, 1)),
            LeerdoelScore(anna.master_id, "SPR-U10-01", 5, date(2026, 10, 1)),
            LeerdoelScore(bas.master_id, "SPR-U10-02", 3, date(2026, 9, 1)),
        ])
        breed = db.leerdoelscores_breed([anna.master_id, bas.master_id])
        assert breed == {anna.master_id: {"SPR-U10-01": 5, "SPR-U10-02": None},
                         bas.master_id: {"SPR-U10-01": None, "SPR-U10-02": 3}}
        u10 = [d.id for d in db.leerdoelen("U10")]
        assert list(db.leerdoelscores_breed([bas.master_id], u10)[bas.master_id]) == u10


def test_ongeldige_scores_geweigerd():
    with opslag() as db:
        anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
        _verwacht_fout(ValueError, LeerdoelScore, anna.master_id, "SPR-U10-01", 6, date(2026, 9, 1))
        _verwacht_fout(ValueError, LeerdoelScore, anna.master_id, "SPR-U10-01", 0, date(2026, 9, 1))
        _verwacht_fout(OpslagFout, db.leerdoelscore_opslaan,
                       LeerdoelScore(anna.master_id, "XXX-U10-01", 3, date(2026, 9, 1)))
        _verwacht_fout(OpslagFout, db.leerdoelscore_opslaan,
                       LeerdoelScore("0" * 32, "SPR-U10-01", 3, date(2026, 9, 1)))


def test_privacy_alleen_pseudoniem_en_verwijderen():
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
            db.leerdoelscore_opslaan(LeerdoelScore(anna.master_id, "SPR-U10-01", 4, date(2026, 9, 1)))
        with contextlib.closing(verbind("leerdoelscores", Path(tmp), TESTSLEUTEL)) as conn:
            refs = [r[0] for r in conn.execute("SELECT atleet_ref FROM leerdoelscore")]
        assert refs == [pseudoniem(anna.master_id, "leerdoelscores", TESTSLEUTEL)]
        assert anna.master_id not in refs
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            db.atleet_verwijderen(anna.master_id)
        with contextlib.closing(verbind("leerdoelscores", Path(tmp), TESTSLEUTEL)) as conn:
            assert conn.execute("SELECT count(*) FROM leerdoelscore").fetchone()[0] == 0
