"""Tests voor het automatisch aanmaken van trainingen op de vaste trainingsdagen van een groep
(groepen.trainingen.trainingen_aanvullen / trainingen_opruimen) en waar de app dat doet.

Tijdelijke map met versleutelde databases, vaste testsleutel, alleen nepgegevens.
Werkt met pytest en los: `python tests/test_trainingen_automatisch.py`.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_groep_landingspagina import TESTSLEUTEL, VANDAAG, opslag  # noqa: E402

from atleten import beheer  # noqa: E402
from groepen import groep as groepsbeheer  # noqa: E402
from groepen import trainingen  # noqa: E402
from models import Absentie, Groep, Training  # noqa: E402

D = lambda m, d: date(2026, m, d)   # noqa: E731


def _groep(db, dagen, leden=(), naam=None):
    g = db.groep_opslaan(Groep(naam or f"Groep {len(db.groepen()) + 1}", "2026-2027", list(leden)))
    db.groep_trainingsdagen_opslaan(g.id, dagen)
    return db.groep(g.id)


def test_aanvullen_vooruit():
    with opslag() as (db, _):
        g = _groep(db, {"dinsdag": "18:30", "donderdag": "19:00"})
        nieuw = trainingen.trainingen_aanvullen(db, g, peildatum=VANDAAG)          # vrijdag 16 okt
        assert [t.datum for t in nieuw] == [D(10, 20), D(10, 22), D(10, 27), D(10, 29),
                                            D(11, 3), D(11, 5), D(11, 10), D(11, 12)]
        assert all(t.onderwerp is None and t.groep_id == g.id for t in nieuw)
        # Nog eens: niets dubbel.
        assert trainingen.trainingen_aanvullen(db, g, peildatum=VANDAAG) == []
        # Een week later: alleen de nieuwe week erbij.
        assert [t.datum for t in trainingen.trainingen_aanvullen(db, g, peildatum=VANDAAG + timedelta(days=7))] \
            == [D(11, 17), D(11, 19)]
        # Vandaag is een trainingsdag: die telt mee.
        g2 = _groep(db, {"vrijdag": "17:00"})
        assert trainingen.trainingen_aanvullen(db, g2, peildatum=VANDAAG)[0].datum == VANDAAG


def test_gemiste_dagen_en_grenzen():
    with opslag() as (db, _):
        g = _groep(db, {"dinsdag": "18:30"})
        # Een handmatige training van 6 okt: gemiste dinsdag 13 okt wordt alsnog aangemaakt.
        db.training_opslaan(Training(g.id, D(10, 6), "Starts"))
        datums = [t.datum for t in trainingen.trainingen_aanvullen(db, g, peildatum=VANDAAG)]
        assert datums[:2] == [D(10, 13), D(10, 20)] and D(10, 6) not in datums
        assert [t.onderwerp for t in db.trainingen(g.id, van=D(10, 6), tot=D(10, 6))] == ["Starts"]  # niet aangepast
        # Nooit verder terug dan MAX_DAGEN_TERUG, ook als de eerste training lang geleden is.
        oud = _groep(db, {"dinsdag": "18:30"})
        db.training_opslaan(Training(oud.id, D(8, 4)))
        datums = [t.datum for t in trainingen.trainingen_aanvullen(db, oud, peildatum=VANDAAG)]
        assert min(datums) >= VANDAAG - timedelta(days=trainingen.MAX_DAGEN_TERUG) and D(10, 6) in datums
        # Zonder vaste dagen: niets.
        leeg = db.groep_opslaan(Groep("Zonder dagen"))
        assert trainingen.trainingen_aanvullen(db, leeg, peildatum=VANDAAG) == []
        assert trainingen.alle_trainingen_aanvullen(db, peildatum=VANDAAG) == 0          # alles al gedaan


def test_opruimen_na_wijzigen():
    with opslag() as (db, _):
        a = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld").master_id
        g = _groep(db, {"dinsdag": "18:30", "donderdag": "19:00"}, [a])
        trainingen.trainingen_aanvullen(db, g, peildatum=VANDAAG)
        do = {t.datum: t for t in db.trainingen(g.id) if t.datum.weekday() == 3}
        do[D(10, 22)].onderwerp = "Horden"
        db.training_opslaan(do[D(10, 22)])                                               # met onderwerp: blijft
        db.absenties_opslaan([Absentie(do[D(10, 29)].id, a, "afgemeld", "school")])      # met afmelding: blijft
        verleden = db.training_opslaan(Training(g.id, D(10, 15)))                        # verleden: blijft

        g = db.groep(g.id)
        g.trainingsdagen = {"dinsdag": "18:30"}
        weg = trainingen.trainingen_opruimen(db, g, peildatum=VANDAAG)
        assert sorted(t.datum for t in weg) == [D(11, 5), D(11, 12)]
        over = {t.datum for t in db.trainingen(g.id) if t.datum.weekday() == 3}
        assert over == {D(10, 15), D(10, 22), D(10, 29)} and verleden.id


def test_opruimen_laat_ingevulde_onderdelen_en_varianten_staan():
    """Een training met warming-up/kern/cooling-down/notities of een afwijkende variant is niet 'leeg'."""
    with opslag() as (db, _):
        a = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld").master_id
        g = _groep(db, {"dinsdag": "18:30", "donderdag": "19:00"}, [a])
        trainingen.trainingen_aanvullen(db, g, peildatum=VANDAAG)
        do = sorted((t for t in db.trainingen(g.id) if t.datum.weekday() == 3), key=lambda t: t.datum)
        do[0].warming_up = "ABC-loopscholing"
        db.training_opslaan(do[0])
        do[1].notities = "Hal is bezet, buiten"
        db.training_opslaan(do[1])
        db.training_opslaan(Training(g.id, do[2].datum, "Alleen voor Anna", hoofdtraining_id=do[2].id, atleten=[a]))
        g = db.groep(g.id)
        g.trainingsdagen = {"dinsdag": "18:30"}
        weg = trainingen.trainingen_opruimen(db, g, peildatum=VANDAAG)
        assert [t.datum for t in weg] == [do[3].datum]                                   # alleen de lege
        assert {t.datum for t in db.trainingen(g.id) if t.datum.weekday() == 3} == {t.datum for t in do[:3]}


def test_via_groep_aanmaken_en_wijzigen():
    """Maken en wijzigen in groepen.groep zetten de trainingen meteen klaar (met de echte datum)."""
    with opslag() as (db, _):
        vandaag = date.today()
        g = groepsbeheer.groep_aanmaken(db, "Nieuw", None, [], {"maandag": "18:00", "woensdag": "18:00"})
        datums = [t.datum for t in db.trainingen(g.id)]
        assert datums and min(datums) >= vandaag and all(d.weekday() in (0, 2) for d in datums)
        w = groepsbeheer.trainingsdagen_opslaan(db, g.id, {"maandag": "18:00", "vrijdag": "17:00"})
        assert w.trainingen_erbij >= 4 and w.trainingen_weg >= 4                       # woensdagen weg, vrijdagen erbij
        assert {t.datum.weekday() for t in db.trainingen(g.id, van=vandaag)} == {0, 4}


def test_app():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        g = _groep(db, {"dinsdag": "18:30", "donderdag": "19:00"})                     # nog geen trainingen
        assert db.trainingen(g.id) == []
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        tekst = c.get(f"/groep/{g.id}").get_data(as_text=True)                         # eerste pagina: aanvullen
        assert len(db.trainingen(g.id)) >= 8
        assert "Geen trainingen gepland" not in tekst and "Invullen" in tekst
        assert app.config["AVS_AANGEVULD_OP"] == date.today()
        # Daarna niet elke pagina opnieuw (één keer per dag).
        nieuw = db.groep_opslaan(Groep("Later"))
        db.groep_trainingsdagen_opslaan(nieuw.id, {"zaterdag": "09:00"})
        c.get("/groepen")
        assert db.trainingen(nieuw.id) == []
        # Wijzigen via de pagina: meteen ingepland, met melding.
        r = c.post(f"/groep/{nieuw.id}/trainingsdagen", data={"tijd-zaterdag": "09:30"})
        assert db.trainingen(nieuw.id) and "ingepland" in c.get(r.headers["Location"]).get_data(as_text=True)


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
