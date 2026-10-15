"""
Importeer alle prestaties van één atleet van zijn atletiek.nu-profiel in de AVS-databases.
De PR's volgen daarna vanzelf uit de opgeslagen prestaties (view `pr`).

Gebruik (vanuit de map AVS):
    python importeer_atletieknu.py 123456                 # atletiek.nu-id van de atleet
    python importeer_atletieknu.py https://www.atletiek.nu/atleet/profiel/123456/
    python importeer_atletieknu.py profiel.html --id 123456   # opgeslagen pagina (Ctrl+S)

De atleet moet al bestaan (beheer.nieuwe_atleet) met dit atletieknu_id.
Opnieuw importeren is veilig: prestaties die er al staan worden overgeslagen.

Vereist: pip install requests beautifulsoup4 curl_cffi sqlcipher3-wheels keyring
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.queries import Opslag  # noqa: E402
from importers.atletieknu_prs import AtletiekNuPRImporter, Resultaat, atleet_id_uit  # noqa: E402
from importers.base import ImportFout  # noqa: E402
from models import Onderdeel, Prestatie, Wedstrijd  # noqa: E402

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Importeer prestaties van een atletiek.nu-profiel.")
    parser.add_argument("bron", help="atletiek.nu-id, profiel-URL of opgeslagen HTML-bestand")
    parser.add_argument("--id", help="atletiek.nu-id, als dat niet uit de bron te halen is")
    args = parser.parse_args()

    try:
        importer = AtletiekNuPRImporter(log=print)
        html = importer.laad_html(args.bron)
    except ImportFout as fout:
        sys.exit(str(fout))
    from importers.atletieknu_prs import parse_results
    resultaten = parse_results(html)
    atletieknu_id = args.id or atleet_id_uit(args.bron, html)

    with Opslag() as db:
        atleet = db.atleet_op_atletieknu_id(atletieknu_id) if atletieknu_id else None
        if atleet is None:
            sys.exit(f"Geen atleet met atletiek.nu-id {atletieknu_id or '?'} in de database. "
                     "Maak hem eerst aan (of vul atletieknu_id in) met atleten.beheer.")
        nieuw, bekend, overgeslagen = importeer(db, atleet.master_id, resultaten)
        print(f"{atleet.naam}: {nieuw} nieuw, {bekend} stonden er al, "
              f"{overgeslagen} overgeslagen (DNF/DNS e.d.). PR's: {len(db.prs(atleet.master_id))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
