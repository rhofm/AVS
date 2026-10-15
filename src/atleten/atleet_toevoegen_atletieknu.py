"""
Voeg een atleet toe aan personen.db (als hij er nog niet in staat) en importeer
al zijn prestaties van atletiek.nu in prestaties.db.

Gebruik (vanuit de map AVS):
    python src/atleten/atleet_toevoegen_atletieknu.py Jan Vries -t de 123456
    python src/atleten/atleet_toevoegen_atletieknu.py Jan Jansen https://www.atletiek.nu/atleet/profiel/123456/
    python src/atleten/atleet_toevoegen_atletieknu.py Jan Jansen 123456 --html profiel.html
    python src/atleten/atleet_toevoegen_atletieknu.py          # vraagt alles zelf

Werkwijze:
  1. Staat er al een atleet met dit atletiek.nu-id?        -> die wordt gebruikt.
  2. Staat er een atleet met dezelfde naam zónder id?       -> na bevestiging krijgt
                                                               die atleet het id.
  3. Anders                                                 -> nieuwe atleet.
Daarna worden de prestaties geïmporteerd met importeer_atletieknu.importeer().
Opnieuw draaien is veilig: bestaande prestaties worden overgeslagen.

Het tussenvoegsel wordt apart opgeslagen (kolom `tussenvoegsel`); de
achternaam zonder tussenvoegsel ('Vries'). Atleet.naam geeft 'Jan de Vries'.

Vereist: pip install requests beautifulsoup4 curl_cffi sqlcipher3-wheels keyring
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atleten import beheer  # noqa: E402
from atleten.importeer_atletieknu import importeer  # noqa: E402
from atleten.koppelen import normaliseer  # noqa: E402
from db.queries import Opslag  # noqa: E402
from importers.atletieknu_prs import AtletiekNuPRImporter, atleet_id_uit, parse_results  # noqa: E402
from importers.base import ImportFout  # noqa: E402
from models import GESLACHTEN, Atleet  # noqa: E402

Status = Literal["bestond", "id_toegevoegd", "nieuw"]


@dataclass
class Uitkomst:
    atleet: Atleet
    status: Status
    nieuw: int = 0          # nieuwe prestaties
    bekend: int = 0         # stonden er al
    overgeslagen: int = 0   # DNF, DNS, ... (geen waarde)


def atletieknu_id_uit(bron: str) -> str:
    """atletiek.nu-id uit een id of profiel-URL. Gooit ValueError als dat niet lukt."""
    atletieknu_id = atleet_id_uit(bron.strip())
    if not atletieknu_id:
        raise ValueError(f"Geen atletiek.nu-id gevonden in {bron!r}. "
                         "Geef het nummer of een link als https://www.atletiek.nu/atleet/profiel/123456/")
    return atletieknu_id


def zoek_of_maak_atleet(db: Opslag, voornaam: str, achternaam: str, atletieknu_id: str, *,
                        bevestig: Callable[[Atleet], bool] | None = None,
                        **gegevens) -> tuple[Atleet, Status]:
    """Zoek de atleet bij dit atletiek.nu-id; maak hem aan als hij er nog niet is.

    `bevestig(kandidaat)` wordt gevraagd als er al een atleet met dezelfde naam
    maar zonder atletiek.nu-id bestaat. True: die atleet krijgt het id. Zonder
    bevestig-functie (of bij False voor alle kandidaten) wordt een nieuwe atleet
    aangemaakt. Extra gegevens: tussenvoegsel, geslacht, geboortedatum, club.
    """
    bestaand = db.atleet_op_atletieknu_id(atletieknu_id)
    if bestaand is not None:
        return bestaand, "bestond"

    gegevens = {k: v for k, v in gegevens.items() if v}
    kandidaten = [a for a in beheer.mogelijke_dubbelen(db, voornaam, achternaam, gegevens.get("geboortedatum"),
                                                       tussenvoegsel=gegevens.get("tussenvoegsel"))
                  if not a.atletieknu_id]
    if bevestig is not None:
        for kandidaat in kandidaten:
            if bevestig(kandidaat):
                kandidaat.atletieknu_id = atletieknu_id
                for veld, waarde in gegevens.items():       # alleen lege velden aanvullen
                    if getattr(kandidaat, veld) is None:
                        setattr(kandidaat, veld, waarde)
                return db.atleet_opslaan(kandidaat), "id_toegevoegd"

    # Atleten met dezelfde naam maar een ánder atletiek.nu-id zijn andere personen.
    atleet = beheer.nieuwe_atleet(db, voornaam, achternaam, toch_aanmaken=True,
                                  atletieknu_id=atletieknu_id, **gegevens)
    return atleet, "nieuw"


def laad_profiel(atletieknu_id: str, html_bestand: str | None = None) -> str:
    """HTML van het profiel: van atletiek.nu, of uit een opgeslagen bestand (Ctrl+S)."""
    importer = AtletiekNuPRImporter(log=print)
    if html_bestand:
        html = importer.laad_html(html_bestand)
        id_in_pagina = atleet_id_uit(html_bestand, html)
        if id_in_pagina and id_in_pagina != atletieknu_id:
            raise ImportFout(f"Het bestand is het profiel van atletiek.nu-id {id_in_pagina}, "
                             f"niet van {atletieknu_id}.")
        return html
    return importer.laad_html(atletieknu_id)


def voeg_toe(db: Opslag, voornaam: str, achternaam: str, bron: str, *,
             tussenvoegsel: str | None = None, html: str | None = None,
             bevestig: Callable[[Atleet], bool] | None = None, **gegevens) -> Uitkomst:
    """Alles in één: atleet zoeken/aanmaken en zijn prestaties importeren.

    `bron` is een atletiek.nu-id of profiel-URL. `html` is de profielpagina zelf
    (dan wordt niets opgehaald). De pagina wordt eerst gelezen; lukt dat niet,
    dan verandert er niets in de databases.
    """
    voornaam, achternaam = voornaam.strip(), achternaam.strip()
    if not voornaam or not achternaam:
        raise ValueError("Voor- en achternaam zijn verplicht.")
    atletieknu_id = atletieknu_id_uit(bron)

    if html is None:
        html = laad_profiel(atletieknu_id)
    resultaten = parse_results(html)            # ValueError als het geen profielpagina is

    atleet, status = zoek_of_maak_atleet(db, voornaam, achternaam, atletieknu_id, bevestig=bevestig,
                                         tussenvoegsel=tussenvoegsel, **gegevens)
    nieuw, bekend, overgeslagen = importeer(db, atleet.master_id, resultaten)
    return Uitkomst(atleet, status, nieuw, bekend, overgeslagen)


# --------------------------------------------------------------------------- opdrachtregel

def _vraag(tekst: str, verplicht: bool = True) -> str:
    while True:
        antwoord = input(f"{tekst}: ").strip()
        if antwoord or not verplicht:
            return antwoord
        print("  Dit is verplicht.")


def _bevestig_via_toetsenbord(altijd_ja: bool) -> Callable[[Atleet], bool]:
    def bevestig(kandidaat: Atleet) -> bool:
        extra = ", ".join(str(x) for x in (kandidaat.geboortejaar, kandidaat.club) if x)
        beschrijving = f"{kandidaat.naam}" + (f" ({extra})" if extra else "")
        if altijd_ja:
            print(f"Bestaande atleet zonder atletiek.nu-id gevonden: {beschrijving}; id wordt toegevoegd.")
            return True
        if not sys.stdin.isatty():
            raise SystemExit(f"Er bestaat al een atleet {beschrijving} zonder atletiek.nu-id. "
                             "Draai opnieuw met --ja om het id aan deze atleet toe te voegen, "
                             "of met --nieuw om toch een nieuwe atleet te maken.")
        antwoord = input(f"Er bestaat al een atleet {beschrijving} zonder atletiek.nu-id.\n"
                         "Is dit dezelfde persoon? [j/n]: ").strip().lower()
        return antwoord in ("j", "ja", "y", "yes")
    return bevestig


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Voeg een atleet toe (als die nog niet bestaat) en importeer zijn prestaties van atletiek.nu.")
    parser.add_argument("voornaam", nargs="?")
    parser.add_argument("achternaam", nargs="?", help="achternaam zonder tussenvoegsel")
    parser.add_argument("bron", nargs="?", help="atletiek.nu-id of link naar het profiel (PR-pagina)")
    parser.add_argument("-t", "--tussenvoegsel", help="bv. 'de', 'van der'")
    parser.add_argument("--html", metavar="BESTAND",
                        help="opgeslagen profielpagina gebruiken i.p.v. ophalen (bij een browsercontrole)")
    parser.add_argument("--geslacht", choices=GESLACHTEN)
    parser.add_argument("--geboortedatum", help="'YYYY-MM-DD' of alleen 'YYYY'")
    parser.add_argument("--club")
    keuze = parser.add_mutually_exclusive_group()
    keuze.add_argument("--ja", action="store_true",
                       help="bestaande atleet met dezelfde naam (zonder id) zonder vragen gebruiken")
    keuze.add_argument("--nieuw", action="store_true",
                       help="altijd een nieuwe atleet maken als het id nog niet bekend is")
    parser.add_argument("--map", type=Path, help="map met de databases (standaard data/)")
    args = parser.parse_args()

    if not args.voornaam:                       # zonder argumenten: alles vragen
        args.voornaam = _vraag("Voornaam")
        args.tussenvoegsel = _vraag("Tussenvoegsel (leeg laten als er geen is)", verplicht=False)
        args.achternaam = _vraag("Achternaam")
    elif not args.achternaam:
        args.achternaam = _vraag("Achternaam")
    if not args.bron:
        args.bron = _vraag("atletiek.nu-id of link naar het profiel")

    try:
        atletieknu_id = atletieknu_id_uit(args.bron)
        html = laad_profiel(atletieknu_id, args.html)
    except (ValueError, ImportFout) as fout:
        print(fout, file=sys.stderr)
        return 1

    bevestig = None if args.nieuw else _bevestig_via_toetsenbord(args.ja)
    try:
        with Opslag(map=args.map) as db:
            u = voeg_toe(db, args.voornaam, args.achternaam, atletieknu_id, tussenvoegsel=args.tussenvoegsel,
                         html=html, bevestig=bevestig, geslacht=args.geslacht,
                         geboortedatum=args.geboortedatum, club=args.club)
            aantal_prs = len(db.prs(u.atleet.master_id))
    except ValueError as fout:
        print(fout, file=sys.stderr)
        return 1

    if u.status == "bestond":
        opgegeven = Atleet(args.voornaam.strip(), args.achternaam.strip(), tussenvoegsel=args.tussenvoegsel).naam
        print(f"{u.atleet.naam} stond al in de database met atletiek.nu-id {atletieknu_id}.")
        if normaliseer(opgegeven) != normaliseer(u.atleet.naam):
            print(f"  Let op: opgegeven naam was '{opgegeven}'. Controleer of het id klopt.")
    elif u.status == "id_toegevoegd":
        print(f"atletiek.nu-id {atletieknu_id} toegevoegd aan bestaande atleet {u.atleet.naam}.")
    else:
        print(f"Nieuwe atleet aangemaakt: {u.atleet.naam}.")
    print(f"Prestaties: {u.nieuw} nieuw, {u.bekend} stonden er al, "
          f"{u.overgeslagen} overgeslagen (DNF/DNS e.d.). PR's: {aantal_prs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
