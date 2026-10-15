"""Tests voor src/atleten/, met echte (versleutelde) databases in een tijdelijke map.

Gebruikt een vaste testsleutel: raakt de sleutelkluis en data/ nooit aan.
Alleen nepgegevens. Werkt met pytest en ook los: `python tests/test_atleten.py`.
"""

import contextlib
import io
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atleten import beheer, koppelen, prestaties, profiel, testen  # noqa: E402
from db.init_db import init_db  # noqa: E402
from db.queries import Opslag, OpslagFout  # noqa: E402
from models import (  # noqa: E402
    Groep, Inschrijving, Leerlijn, LeerlijnStap, LeerlijnVoortgang, Onderdeel, Prestatie, Test, Wedstrijd,
)

TESTSLEUTEL = "22" * 32


@contextlib.contextmanager
def opslag():
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
            db.onderdeel_opslaan(Onderdeel("800m", "tijd", True, "midden"))
            db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
            yield db


def _verwacht(fout, fn):
    try:
        fn()
    except fout as e:
        return e
    raise AssertionError(f"{fout.__name__} verwacht")


# ---------------- beheer ----------------
def test_beheer():
    with opslag() as db:
        anna = beheer.nieuwe_atleet(db, " Anna ", "Voorbeeld", geslacht="V", geboortedatum="2010-05-01")
        assert anna.voornaam == "Anna"
        fout = _verwacht(beheer.DubbeleAtleet, lambda: beheer.nieuwe_atleet(db, "anna", "VOORBEELD"))
        assert fout.bestaande[0].master_id == anna.master_id
        # Zelfde naam, ander geboortejaar: geen dubbele.
        anna2 = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geboortedatum="2012")
        assert anna2.master_id != anna.master_id
        _verwacht(ValueError, lambda: beheer.nieuwe_atleet(db, "", "Leeg"))

        beheer.zet_specialisatie(db, anna.master_id, " sprint ")
        beheer.zet_actief(db, anna2.master_id, False)
        assert [a.specialisatie for a in beheer.zoeken(db, "voorb", alleen_actief=True)] == ["sprint"]
        assert len(beheer.zoeken(db)) == 2

        _verwacht(ValueError, lambda: beheer.verwijderen(db, anna2.master_id))
        beheer.verwijderen(db, anna2.master_id, bevestigd=True)
        assert db.atleet(anna2.master_id) is None


# ---------------- koppelen ----------------
def test_normaliseer():
    assert koppelen.normaliseer("Proefhuis, Pim van 't") == "pim van 't proefhuis"
    assert koppelen.normaliseer("  Zoë   Ëxample-Test ") == "zoe example test"
    assert koppelen.normaliseer(None) == ""


def test_koppelen():
    with opslag() as db:
        anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geboortedatum="2010", atletieknu_id="123456")
        tim = beheer.nieuwe_atleet(db, "Tim", "Proefmans", geboortedatum="2011", club="AV Test")
        lotte = beheer.nieuwe_atleet(db, "Lotte", "Testerink")
        tim2 = beheer.nieuwe_atleet(db, "Tim", "Proefmans", geboortedatum="2013", toch_aanmaken=True)

        def p(**kw):
            return Prestatie("100m", date(2026, 6, 1), 13.0, bron="atletieknu", **kw)

        ps = [
            p(bron_naam="Iemand Anders", bron_atletieknu_id="123456"),            # id -> Anna
            p(bron_naam="Proefmans, Tim", bron_geboortejaar=2011),                # naam + jaar -> tim
            p(bron_naam="Tim Proefmans", bron_club="AV Test"),                    # naam + club -> tim
            p(bron_naam="Lotte Testerink"),                                       # alleen naam -> controleren
            p(bron_naam="Tim Proefmans"),                                         # twee Tims -> controleren
            p(bron_naam="Lotte Testerink", bron_atletieknu_id="999"),             # Lotte heeft nog geen id -> controleren
            p(bron_naam="Anna Voorbeeld", bron_geboortejaar=2009),                # jaar klopt niet -> onbekend
            p(bron_naam="Bas Proefstra"),                                         # niet van de club
        ]
        r = koppelen.koppel(db, ps)
        assert [x.atleet_id for x in r.gekoppeld] == [anna.master_id, tim.master_id, tim.master_id]
        assert all(x.bron_naam is None and x.bron_club is None for x in r.gekoppeld)
        assert [(k.manier, len(k.kandidaten)) for _, k in r.te_controleren] == \
               [("naam", 1), ("meerdere", 2), ("naam", 1)]
        assert {x.bron_naam for x in r.onbekend} == {"Anna Voorbeeld", "Bas Proefstra"}
        assert tim2.master_id in {a.master_id for a in r.te_controleren[1][1].kandidaten}

        # Bevestigen bewaart het atletiek.nu-id; daarna is de koppeling zeker.
        bevestigd = koppelen.bevestig(db, p(bron_naam="Lotte Testerink", bron_atletieknu_id="555"), lotte.master_id)
        assert bevestigd.atleet_id == lotte.master_id and bevestigd.bron_atletieknu_id is None
        assert db.atleet(lotte.master_id).atletieknu_id == "555"
        k = koppelen.Koppelaar(db)
        assert k.zoek("Wie Dan Ook", "555").manier == "atletieknu_id"
        # Nu Lotte een id heeft, is een Lotte met een ánder id iemand anders.
        assert k.zoek("Lotte Testerink", "999").manier == "geen"

        assert db.prestaties_opslaan(r.gekoppeld) == (2, 1)  # Anna en Tim nieuw; Tim's tweede regel is dezelfde


# ---------------- prestaties ----------------
def test_waarden_lezen_en_tonen():
    assert prestaties.lees_waarde("12,93", "tijd") == 12.93
    assert prestaties.lees_waarde("1:58,21", "tijd") == 118.21
    assert prestaties.lees_waarde("1:02:03", "tijd") == 3723
    assert prestaties.lees_waarde("4,80 m", "afstand") == 4.8
    _verwacht(ValueError, lambda: prestaties.lees_waarde("snel", "tijd"))
    assert prestaties.toon_waarde(12.93, "tijd") == "12,93"
    assert prestaties.toon_waarde(118.21, "tijd") == "1:58,21"
    assert prestaties.toon_waarde(65.0, "tijd") == "1:05,00"
    assert prestaties.toon_waarde(3723, "tijd") == "1:02:03,00"
    assert prestaties.toon_waarde(4.8, "afstand") == "4,80 m"
    assert prestaties.toon_waarde(4500, "punten") == "4500 pnt"


def test_handmatig_pr_historie_seizoensbesten():
    with opslag() as db:
        anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld")
        _, pr = prestaties.handmatig_toevoegen(db, anna.master_id, "100m", date(2025, 6, 1), "13,40")
        assert pr
        _, pr = prestaties.handmatig_toevoegen(db, anna.master_id, "100m", date(2025, 7, 1), "13,60")
        assert not pr
        _, pr = prestaties.handmatig_toevoegen(db, anna.master_id, "100m", date(2026, 5, 1), "13,10", wind=2.6)
        assert not pr  # te veel rugwind
        _, pr = prestaties.handmatig_toevoegen(db, anna.master_id, "100m", date(2026, 6, 1), "13,20", wind=1.1)
        assert pr
        _verwacht(OpslagFout, lambda: prestaties.handmatig_toevoegen(db, anna.master_id, "Kogel", date(2026, 1, 1), 9))

        sprint = db.onderdeel("100m")
        assert [p.waarde for p in prestaties.pr_historie(db, anna.master_id, sprint.id)] == [13.4, 13.2]
        assert [p.waarde for p in prestaties.pr_historie(db, anna.master_id, sprint.id, False)] == [13.4, 13.1]
        assert prestaties.seizoensbesten(db, anna.master_id, 2025)[sprint.id].waarde == 13.4
        assert prestaties.seizoensbesten(db, anna.master_id, 2026)[sprint.id].waarde == 13.2


# ---------------- testen ----------------
def test_testen():
    with opslag() as db:
        anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld")
        db.test_opslaan(Test("30m vliegend", "s", True))
        db.test_opslaan(Test("Sargent jump", "cm", False))
        testen.resultaat_toevoegen(db, anna.master_id, "30m vliegend", date(2026, 9, 1), 4.10)
        testen.resultaat_toevoegen(db, anna.master_id, "30m vliegend", date(2026, 10, 1), 3.95)
        testen.resultaat_toevoegen(db, anna.master_id, "Sargent jump", date(2026, 9, 1), 40)
        testen.resultaat_toevoegen(db, anna.master_id, "Sargent jump", date(2026, 10, 1), 38)
        _verwacht(OpslagFout, lambda: testen.resultaat_toevoegen(db, anna.master_id, "Bestaat niet", date(2026, 1, 1), 1))

        assert [r.waarde for r in testen.verloop(db, anna.master_id, "30m vliegend")] == [4.10, 3.95]
        assert testen.beste(db, anna.master_id, "30m vliegend").waarde == 3.95
        assert testen.beste(db, anna.master_id, "Sargent jump").waarde == 40
        assert testen.vooruitgang(db, anna.master_id, "30m vliegend") == 0.15   # sneller = beter
        assert testen.vooruitgang(db, anna.master_id, "Sargent jump") == -2     # lager gesprongen
        assert len(testen.laatste_per_test(db, anna.master_id)) == 2


# ---------------- profiel ----------------
def test_profiel():
    with opslag() as db:
        anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geboortedatum="2010-05-01")
        prestaties.handmatig_toevoegen(db, anna.master_id, "100m", date(2026, 6, 1), "13,20")
        prestaties.handmatig_toevoegen(db, anna.master_id, "Verspringen", date(2026, 6, 1), "4,80")
        oud = db.wedstrijd_opslaan(Wedstrijd("Voorbij", date(2026, 6, 1)))
        straks = db.wedstrijd_opslaan(Wedstrijd("Straks", date(2026, 11, 1)))
        db.inschrijving_opslaan(Inschrijving(anna.master_id, oud.id))
        db.inschrijving_opslaan(Inschrijving(anna.master_id, straks.id, db.onderdeel("800m").id))
        db.test_opslaan(Test("30m vliegend", "s", True))
        testen.resultaat_toevoegen(db, anna.master_id, "30m vliegend", date(2026, 10, 1), 3.95)
        lijn = db.leerlijn_opslaan(Leerlijn("Sprint", stappen=[LeerlijnStap(1, "Armactie"), LeerlijnStap(2, "Blokstart")]))
        db.leerlijn_opslaan(Leerlijn("Werpen", stappen=[LeerlijnStap(1, "Stand")]))
        db.voortgang_opslaan(LeerlijnVoortgang(anna.master_id, lijn.stappen[0].id, date(2026, 9, 1)))
        db.groep_opslaan(Groep("Junioren C", "2026-2027", [anna.master_id]))

        prof = profiel.profiel(db, anna.master_id, peildatum=date(2026, 10, 15))
        assert prof.leeftijd == 16
        assert [(r.onderdeel.naam, r.waarde) for r in prof.prs] == [("Verspringen", 4.8), ("100m", 13.2)]
        assert len(prof.recente_prestaties) == 2
        assert [(g.wedstrijd.naam, g.onderdeel.naam) for g in prof.geplande_wedstrijden] == [("Straks", "800m")]
        assert prof.testen[0].laatste.waarde == 3.95
        assert [(s.leerlijn.naam, s.behaald, s.totaal, s.volgende.naam) for s in prof.leerlijnen] == \
               [("Sprint", 1, 2, "Blokstart")]
        assert [g.naam for g in prof.groepen] == ["Junioren C"]
        assert "Anna" not in repr(prof.atleet)
        assert profiel.profiel(db, "f" * 32) is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
