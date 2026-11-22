"""Nepgegevens rond één atleet (Anna Voorbeeld), voor meerdere testbestanden. Geen tests.

Rekent met hulp.VANDAAG (vr 16 okt 2026): een testbestand dat dit gebruikt zet
VASTE_VANDAAG = VANDAAG (zie conftest.py).
"""

import contextlib
from datetime import date, timedelta

from atleten import beheer, prestaties
from db.queries import Opslag
from models import (Absentie, Atleet, Groep, Notitie, Onderdeel, Test, Testresultaat, Training,
                    Trainingsschema)
from wedstrijden import planning
from hulp import TEMPLATES, TESTSLEUTEL, VANDAAG, app_client, lege_map, lege_opslag

__all__ = ["TEMPLATES", "VANDAAG", "opslag", "opslag_met_map", "voorbeeld", "client", "basis_atleten"]


def _onderdelen(db: Opslag) -> None:
    db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
    db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))


@contextlib.contextmanager
def opslag():
    """Opslag met de onderdelen 100m en Verspringen (nog zonder atleten)."""
    with lege_opslag() as (db, _):
        _onderdelen(db)
        yield db


@contextlib.contextmanager
def opslag_met_map(met_voorbeeld: bool = True):
    """(Opslag, map); met_voorbeeld: ook de onderdelen en Anna (voorbeeld())."""
    with lege_opslag() as (db, map):
        if met_voorbeeld:
            _onderdelen(db)
            voorbeeld(db)
        yield db, map


def voorbeeld(db: Opslag) -> str:
    """Een nep-atleet met van alles erbij. Geeft de master_id."""
    a = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2011-03-14",
                             specialisatie="Sprint & verspringen")
    mid = a.master_id
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(mid, ["dinsdag", "donderdag", "zaterdag"]))
    g = db.groep_opslaan(Groep("U16 sprint", "2026-2027", [mid]))
    maandag = VANDAAG - timedelta(days=VANDAAG.weekday())
    db.training_opslaan(Training(g.id, maandag + timedelta(days=1), "Startblok"))
    db.training_opslaan(Training(g.id, maandag + timedelta(days=8), "Volgende week"))   # valt buiten deze week
    oud = db.training_opslaan(Training(g.id, VANDAAG - timedelta(days=10), "Horden"))
    heel_oud = db.training_opslaan(Training(g.id, VANDAAG - timedelta(weeks=20), "Kracht"))
    db.absenties_opslaan([Absentie(oud.id, mid, "blessure", "enkel"),
                          Absentie(heel_oud.id, mid, "blessure", "knie")])
    for i in range(7):
        db.notitie_opslaan(Notitie(mid, VANDAAG - timedelta(days=i), f"Notitie {i}\ntweede regel"))
    w = planning.plan_wedstrijd(db, "Clubkampioenschappen", VANDAAG + timedelta(days=8), "Sportpark")
    planning.inschrijven(db, w.id, mid, ["100m", "Verspringen"])
    w2 = planning.plan_wedstrijd(db, "Indoor Cup", VANDAAG + timedelta(days=40))
    planning.inschrijven(db, w2.id, mid)
    oud_w = planning.plan_wedstrijd(db, "Vorig seizoen", VANDAAG - timedelta(days=30))
    planning.inschrijven(db, oud_w.id, mid, ["100m"])
    prestaties.handmatig_toevoegen(db, mid, "100m", date(2026, 6, 1), "13,20", wind=1.0)
    prestaties.handmatig_toevoegen(db, mid, "Verspringen", date(2026, 6, 1), "4,80", wind=0.5)
    t = db.test_opslaan(Test("30m vliegend", "s", True))
    db.testresultaat_opslaan(Testresultaat(mid, t.id, date(2026, 9, 1), 4.25))
    return mid


@contextlib.contextmanager
def client():
    """(Flask-testclient, master_id van Anna, map) met een tijdelijke database."""
    with lege_map() as map:
        with Opslag(map=map, hoofd=TESTSLEUTEL) as db:      # dicht voordat de app begint
            _onderdelen(db)
            mid = voorbeeld(db)
        yield app_client(map), mid, map


def basis_atleten(db: Opslag):
    """Anna (met atletieknu_id) en Tim, plus de onderdelen 100m en Verspringen."""
    anna = db.atleet_opslaan(Atleet("Anna", "Voorbeeld", geslacht="V", geboortedatum="2010", atletieknu_id="123456"))
    tim = db.atleet_opslaan(Atleet("Tim", "Proefmans", geslacht="M"))
    sprint = db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
    ver = db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
    return anna, tim, sprint, ver
