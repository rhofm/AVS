"""
Voeg een atleet toe aan personen.db (als hij er nog niet in staat) en importeer
al zijn prestaties van atletiek.nu in prestaties.db.

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

from dataclasses import dataclass
from typing import Callable, Literal

from atleten import beheer
from atleten.importeer_atletieknu import importeer
from db.queries import Opslag
from importers.atletieknu_prs import AtletiekNuPRImporter, atleet_id_uit, parse_results
from importers.base import ImportFout
from models import Atleet

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
