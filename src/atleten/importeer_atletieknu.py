"""
Importeer alle prestaties van één atleet van zijn atletiek.nu-profiel in de AVS-databases.
De PR's volgen daarna vanzelf uit de opgeslagen prestaties (view `pr`).

De atleet moet al bestaan (beheer.nieuwe_atleet) met dit atletieknu_id.
Opnieuw importeren is veilig: prestaties die er al staan worden overgeslagen.

Vereist: pip install requests beautifulsoup4 curl_cffi sqlcipher3-wheels keyring
"""

from __future__ import annotations

import re
from datetime import date

from db.queries import Opslag
from importers.atletieknu_prs import Resultaat
from models import Onderdeel, Prestatie, Wedstrijd

HOOGTE = ("hoog", "polsstok")
AFSTAND = ("ver", "hinkstap", "stoten", "werpen", "slingeren", "kogel", "discus", "speer", "bal")
PUNTEN = ("kamp",)


def eenheid_van(naam: str) -> str:
    n = naam.lower()
    if any(w in n for w in PUNTEN):
        return "punten"
    if any(w in n for w in HOOGTE):
        return "hoogte"
    if any(w in n for w in AFSTAND):
        return "afstand"
    return "tijd"


def onderdeel_naam(r: Resultaat) -> str:
    """'60 meter horden' + '76.2cm' -> '60 meter horden 76,2cm'."""
    return f"{r.onderdeel} {r.specificatie.replace('.', ',')}".strip()


def wind_van(tekst: str) -> float | None:
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", tekst or "")
    return float(m.group().replace(",", ".")) if m else None


def importeer(db: Opslag, master_id: str, resultaten: list[Resultaat]) -> tuple[int, int, int]:
    """Sla de resultaten op bij deze atleet. Geeft (nieuw, al_bekend, overgeslagen)."""
    onderdelen: dict[str, Onderdeel] = {}
    wedstrijden: dict[str, int] = {}
    nieuw = bekend = overgeslagen = 0
    for r in resultaten:
        if r.waarde is None or not r.datum:          # DNF, DNS, NM, ...
            overgeslagen += 1
            continue
        naam = onderdeel_naam(r)
        o = onderdelen.get(naam) or db.onderdeel(naam)
        if o is None:
            eenheid = eenheid_van(naam)
            o = db.onderdeel_opslaan(Onderdeel(naam, eenheid, lager_is_beter=(eenheid == "tijd")))
        onderdelen[naam] = o

        datum = date.fromisoformat(r.datum)
        wedstrijd_id = None
        if r.wedstrijd_url:
            if r.wedstrijd_url not in wedstrijden:
                w = db.wedstrijd_opslaan(Wedstrijd(r.wedstrijd or "Onbekende wedstrijd", datum,
                                                   locatie=r.plaats or None, bron="atletieknu",
                                                   bron_url=r.wedstrijd_url))
                wedstrijden[r.wedstrijd_url] = w.id
            wedstrijd_id = wedstrijden[r.wedstrijd_url]

        p = Prestatie(naam, datum, r.waarde, atleet_id=master_id, onderdeel_id=o.id,
                      wedstrijd_id=wedstrijd_id, wind=wind_van(r.wind), bron="atletieknu")
        if db.prestatie_opslaan(p):
            nieuw += 1
        else:
            bekend += 1
    return nieuw, bekend, overgeslagen
