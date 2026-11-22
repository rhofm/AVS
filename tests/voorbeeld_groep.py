"""Nepgegevens rond een trainingsgroep, voor meerdere testbestanden. Geen tests.

Rekent met hulp.VANDAAG (vr 16 okt 2026): een testbestand dat dit gebruikt zet
VASTE_VANDAAG = VANDAAG (zie conftest.py).
"""

import contextlib
from datetime import timedelta

from atleten import beheer
from db.queries import Opslag
from models import Absentie, Fase, Groep, LeerdoelScore, Mesocyclus, Onderdeel, Training, Trainingsschema
from wedstrijden import planning
from hulp import TEMPLATES, VANDAAG, lege_opslag

__all__ = ["MAANDAG", "TEMPLATES", "VANDAAG", "opslag", "voorbeeldgroep"]

MAANDAG = VANDAAG - timedelta(days=VANDAAG.weekday())


@contextlib.contextmanager
def opslag():
    """(Opslag, map) met de onderdelen 100m en Verspringen."""
    with lege_opslag() as (db, map):
        db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
        db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
        yield db, map


def voorbeeldgroep(db: Opslag) -> dict:
    """Een nepgroep (di + do) met drie atleten en van alles erbij. Geeft ids."""
    anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2011-03-14",
                                specialisatie="Sprint").master_id
    bram = beheer.nieuwe_atleet(db, "Bram", "Test", geslacht="M", geboortedatum="2012").master_id
    cas = beheer.nieuwe_atleet(db, "Cas", "Proef", geslacht="M", geboortedatum="2013",
                               specialisatie="Werpen").master_id
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna, ["dinsdag", "donderdag", "zaterdag"]))
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(bram, ["dinsdag", "donderdag"]))
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(cas, ["maandag", "dinsdag", "donderdag"]))

    g = db.groep_opslaan(Groep("U16 sprint", "2026-2027", [anna, bram, cas]))
    werp = db.groep_opslaan(Groep("Werpgroep", "2026-2027", [cas]))
    db.training_opslaan(Training(werp.id, MAANDAG, "Kogel"))

    # Periodisering: V1 sinds twee weken (tot over zes weken), mesocyclus van 4 weken -> vandaag week 3 'Piek'.
    db.groep_fasen_opslaan(g.id, [Fase(MAANDAG - timedelta(weeks=2), "V1"), Fase(MAANDAG + timedelta(weeks=6), "V2")])
    db.mesocycli_opslaan(g.id, [Mesocyclus(MAANDAG - timedelta(weeks=2), 4, ["Opbouw", "Opbouw", "Piek", "Herstel"])])
    di_oud = db.training_opslaan(Training(g.id, MAANDAG - timedelta(days=6), "Starts"))     # vorige week di
    do_oud = db.training_opslaan(Training(g.id, MAANDAG - timedelta(days=4), "Horden"))     # vorige week do
    db.training_opslaan(Training(g.id, MAANDAG + timedelta(days=1), "Niet ingevuld"))       # deze week di
    db.training_opslaan(Training(g.id, MAANDAG + timedelta(days=8), "Startblok"))
    db.training_opslaan(Training(g.id, MAANDAG + timedelta(days=10), None))
    db.training_opslaan(Training(g.id, MAANDAG - timedelta(weeks=20), "Te oud"))
    db.absenties_opslaan([Absentie(di_oud.id, anna, "aanwezig"), Absentie(di_oud.id, bram, "afwezig"),
                          Absentie(do_oud.id, anna, "aanwezig"), Absentie(do_oud.id, bram, "aanwezig"),
                          Absentie(do_oud.id, cas, "afgemeld")])

    spr = [d.id for d in db.leerdoelen("U16", leerlijn="SPR")]
    db.leerdoelscores_opslaan([LeerdoelScore(anna, spr[0], 4, VANDAAG), LeerdoelScore(anna, spr[1], 2, VANDAAG),
                               LeerdoelScore(bram, spr[0], 5, VANDAAG)])

    w = planning.plan_wedstrijd(db, "Clubkampioenschappen", VANDAAG + timedelta(days=8), "Sportpark")
    planning.inschrijven(db, w.id, anna, ["100m"])
    planning.inschrijven(db, w.id, bram)
    oud = planning.plan_wedstrijd(db, "Vorige maand", VANDAAG - timedelta(days=30))
    planning.inschrijven(db, oud.id, anna, ["100m"])
    ander = beheer.nieuwe_atleet(db, "Dirk", "Buiten").master_id
    w3 = planning.plan_wedstrijd(db, "Zonder groep", VANDAAG + timedelta(days=3))
    planning.inschrijven(db, w3.id, ander)
    return {"groep": g.id, "werp": werp.id, "anna": anna, "bram": bram, "cas": cas, "spr": spr}
