"""Nepgegevens rond wedstrijden en tijdschema's, voor meerdere testbestanden. Geen tests.

Er wordt niets van internet gehaald: NepImporter en nep_site lezen opgeslagen, geanonimiseerde
pagina's uit fixtures/atletieknu_tijdschema/ (zie de README daar).
De wedstrijd van opslag() is op DAG, 8 dagen na hulp.VANDAAG: een testbestand dat dit gebruikt
zet VASTE_VANDAAG = VANDAAG (zie conftest.py), zodat 'komend' niet van de echte datum afhangt.
"""

import contextlib
from datetime import timedelta
from pathlib import Path

from atleten import beheer
from importers.atletieknu_tijdschema import AtletiekNuTijdschemaImporter
from models import Onderdeel, ProgrammaOnderdeel
from wedstrijden import planning, tijdschema_import
from hulp import VANDAAG, lege_opslag

__all__ = ["BROWSERCONTROLE", "DAG", "MAP", "MEERKAMP", "TEAMS", "VANDAAG", "NepImporter", "nep_site",
           "opslag", "opslag_met_100m"]

MAP = Path(__file__).resolve().parent / "fixtures" / "atletieknu_tijdschema"
MEERKAMP, TEAMS = MAP / "meerkamp.html", MAP / "teams.html"
BROWSERCONTROLE = "<html><body>Checking your browser</body></html>"
DAG = VANDAAG + timedelta(days=8)


@contextlib.contextmanager
def opslag():
    """(Opslag, map, ids) met een wedstrijd op DAG, een tijdschema en drie nep-atleten."""
    with lege_opslag() as (db, map):
        honderd = db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
        ver = db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
        kogel = db.onderdeel_opslaan(Onderdeel("Kogelstoten", "afstand", False, "werpen"))
        jaar = DAG.year - 15                                         # U16 op de wedstrijddag
        anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum=f"{jaar}-03-14").master_id
        bram = beheer.nieuwe_atleet(db, "Bram", "Test", geslacht="M", geboortedatum=f"{jaar}-05-01").master_id
        cees = beheer.nieuwe_atleet(db, "Cees", "Nep", geslacht="M", geboortedatum=f"{DAG.year - 11}").master_id  # U12
        w = planning.plan_wedstrijd(db, "Clubkampioenschappen", DAG, "Sportpark",
                                    link="https://www.atletiek.nu/wedstrijd/main/45678/")
        regels = [
            ProgrammaOnderdeel(w.id, DAG, "10:00", honderd.id, categorie="Meisjes U16", ronde="serie", duur=30),
            ProgrammaOnderdeel(w.id, DAG, "10:15", ver.id, categorie="MU16", groep=1, duur=45),
            ProgrammaOnderdeel(w.id, DAG, "10:30", honderd.id, categorie="Jongens U16", duur=30),
            ProgrammaOnderdeel(w.id, DAG, "11:00", kogel.id, categorie="Jongens U12"),
            ProgrammaOnderdeel(w.id, DAG, "11:30", onderdeel_tekst="Hoogspringen", categorie="U14"),
        ]
        db.programma_vervangen(w.id, regels)
        planning.inschrijven(db, w.id, anna, ["100m", "Verspringen"])     # 100m 10:00 en ver 10:15: botsing
        planning.inschrijven(db, w.id, bram, ["100m", "Verspringen"])     # ver is alleen voor meisjes
        ids = dict(w=w.id, anna=anna, bram=bram, cees=cees, honderd=honderd.id, ver=ver.id, kogel=kogel.id,
                   regels=[r.id for r in regels])
        yield db, map, ids


@contextlib.contextmanager
def opslag_met_100m():
    """(Opslag, map) met alleen het onderdeel 100m: voor een nieuwe wedstrijd."""
    with lege_opslag() as (db, map):
        db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
        yield db, map


class NepImporter(AtletiekNuTijdschemaImporter):
    """Geeft een opgeslagen pagina terug in plaats van atletiek.nu op te halen."""

    def __init__(self, pagina: Path, inhoud: str | None = None):
        super().__init__()
        self.pagina, self.inhoud, self.opgehaald = pagina, inhoud, []

    def haal_op(self, url: str) -> str:
        self.opgehaald.append(url)
        html = self.inhoud if self.inhoud is not None else self.pagina.read_text(encoding="utf-8")
        self.controleer_pagina(html, url)
        return html


@contextlib.contextmanager
def nep_site(inhoud: str | None = None):
    """Laat tijdschema_import de opgeslagen pagina lezen in plaats van atletiek.nu."""
    echt = tijdschema_import._ophalen

    def nep(bron, wedstrijd=None, importer=None):
        return echt(bron, wedstrijd, importer or NepImporter(MEERKAMP, inhoud))
    tijdschema_import._ophalen = nep
    try:
        yield
    finally:
        tijdschema_import._ophalen = echt
