"""Nepgegevens voor ploegopstellingen (U14/U16-competitie), voor meerdere testbestanden. Geen tests."""

import contextlib
import random
from datetime import date

from atleten import beheer
from models import Atleet, Onderdeel, Prestatie
from ploeg import regels
from ploeg.vergelijk import Cel, Matrix, Rij
from hulp import lege_opslag

__all__ = ["BESTAND", "DAG", "JAAR", "REGELS", "RS", "opslag", "nep_matrix"]

DAG = date(2027, 5, 15)            # wedstrijddag (zaterdag)
JAAR = DAG.year
BESTAND = "u14_u16_2026-2027"
RS = regels.laad(BESTAND)
REGELS = RS.programma("U16-V", "wedstrijd_1")          # 80m, 800m, 80mH, 4x80m, hoog, ver, kogel, discus


@contextlib.contextmanager
def opslag():
    """(Opslag, map, ids). Atleten op de wedstrijddag: anna U16-V, bo U16-V, cato U14-V, dirk U16-M."""
    with lege_opslag() as (db, map):
        ids = {
            "anna": beheer.nieuwe_atleet(db, "Anna", "Proef", geslacht="V", geboortedatum=f"{JAAR - 15}-03-01"),
            "bo": beheer.nieuwe_atleet(db, "Bo", "Proef", geslacht="V", geboortedatum=f"{JAAR - 14}-06-01"),
            "cato": beheer.nieuwe_atleet(db, "Cato", "Proef", geslacht="V", geboortedatum=f"{JAAR - 13}"),
            "dirk": beheer.nieuwe_atleet(db, "Dirk", "Proef", geslacht="M", geboortedatum=f"{JAAR - 15}"),
        }
        ids = {k: a.master_id for k, a in ids.items()}
        o = {n: db.onderdeel_opslaan(Onderdeel(n, e, e == "tijd")) for n, e in (
            ("80 meter", "tijd"), ("80 meter Handtijd", "tijd"), ("800 meter", "tijd"),
            ("80 meter horden 76,2cm", "tijd"), ("Verspringen", "afstand"), ("Hoogspringen", "hoogte"),
            ("Kogelstoten 3kg", "afstand"), ("Kogelstoten 2kg", "afstand"), ("Discuswerpen 1kg", "afstand"))}

        def pr(wie, onderdeel, waarde, datum, wind=None):
            db.prestatie_opslaan(Prestatie(onderdeel, datum, waarde, atleet_id=ids[wie],
                                           onderdeel_id=o[onderdeel].id, wind=wind))

        pr("anna", "80 meter", 10.60, date(JAAR, 4, 20), wind=1.0)
        pr("anna", "80 meter", 10.20, date(JAAR, 4, 21), wind=3.1)       # te veel rugwind: telt niet
        pr("anna", "80 meter", 10.10, date(JAAR - 3, 6, 1), wind=0.0)    # te oud voor 'seizoen', wel PR
        pr("anna", "Verspringen", 5.10, date(JAAR - 1, 7, 1), wind=0.5)
        pr("bo", "80 meter", 10.90, date(JAAR, 4, 20), wind=0.0)
        pr("bo", "80 meter horden 76,2cm", 12.80, date(JAAR, 4, 20), wind=1.5)
        pr("cato", "80 meter Handtijd", 10.80, date(JAAR, 4, 20))        # handtijd: +0,24
        pr("cato", "Kogelstoten 2kg", 9.80, date(JAAR, 4, 20))           # U14-materiaal: hint
        pr("bo", "Kogelstoten 3kg", 10.50, date(JAAR, 5, 20))            # na de wedstrijddag: telt niet
        pr("anna", "Kogelstoten 3kg", 9.00, date(JAAR, 4, 1))
        yield db, map, ids


def nep_matrix(n: int, zaad: int = 1, leeg: float = 0.15) -> tuple[Matrix, list[str]]:
    """Matrix (U16-V, wedstrijd_1) met n atleten en willekeurige punten (soms geen prestatie)."""
    rnd = random.Random(zaad)
    ids = [f"{i:x}" * 32 for i in range(1, n + 1)]
    rijen = []
    for k, mid in enumerate(ids):
        rij = Rij(Atleet(f"A{k}", "Nep", geslacht="V", master_id=mid[:32]), "U16-V", True)
        for r in REGELS:
            c = Cel(r.sleutel, r.naam)
            if r.soort != "estafette" and rnd.random() > leeg:
                c.waarde, c.punten = 1.0, rnd.randint(200, 900)
            rij.cellen[r.sleutel] = c
        rijen.append(rij)
    return Matrix(RS, "U16-V", "wedstrijd_1", DAG, "seizoen", REGELS, rijen), [r.master_id for r in rijen]
