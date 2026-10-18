"""Importeerpagina: de keuzepagina achter 'Importeren' in de appbalk.

Drie grote tegels, één per soort import:
  * Atleet      – een nieuwe atleet toevoegen: gaat naar het formulier 'Nieuwe atleet'
                  (/atleten/nieuw, atleten/nieuw.py);
  * Groep       – een hele groep atleten in één keer: gaat naar 'Groep importeren'
                  (/importeren/groep, groepen/groep_importeren.py): een tabel invullen of uit
                  Excel plakken, en de atleten in een bestaande of een nieuwe groep zetten;
  * Wedstrijd   – een wedstrijd toevoegen vanaf de link op atletiek.nu of Seltec: gaat naar
                  het formulier 'Nieuwe wedstrijd' (/wedstrijden/nieuw, wedstrijden/tijdschema_import.py).

Elke tegel gaat naar de pagina van zijn `endpoint`. De oude adressen
/importeren/atleet en /importeren/wedstrijd sturen door naar die formulieren.

Geen gegevens van atleten op deze pagina: alleen uitleg.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Importkeuze:
    sleutel: str        # pad en icoon: /importeren/atleet, ...
    titel: str
    uitleg: str         # wat er gebeurt
    bron: str           # waar de gegevens vandaan komen (hele zin: 'Van atletiek.nu')
    nodig: str          # wat je bij de hand moet hebben
    endpoint: str | None = None     # bestaande pagina (Flask-endpoint) waar de tegel naartoe gaat


KEUZES: tuple[Importkeuze, ...] = (
    Importkeuze("atleet", "Atleet",
                "Een nieuwe atleet toevoegen, meteen met groepen en trainingsdagen. "
                "Staat er al iemand met dezelfde naam, dan vraagt AVS eerst om bevestiging.",
                "Met de hand invullen", "naam, geboortedatum en eventueel het atletiek.nu-nummer",
                endpoint="atleet_nieuw"),
    Importkeuze("groep", "Groep",
                "Een hele groep atleten in één keer, elk met al zijn prestaties, in een bestaande "
                "of een nieuwe groep. Wie er al is, wordt herkend.",
                "Van atletiek.nu", "per atleet de naam en het atletiek.nu-nummer (plakken uit Excel kan)",
                endpoint="importeren_groep"),
    Importkeuze("wedstrijd", "Wedstrijd",
                "Een wedstrijd toevoegen vanaf de link: naam, datum, plaats en tijdschema worden "
                "opgehaald. Daarna schrijf je de atleten in.",
                "Van atletiek.nu of Seltec", "de link naar de wedstrijd",
                endpoint="wedstrijd_nieuw"),
)

#: sleutel → keuze.
PER_SLEUTEL: dict[str, Importkeuze] = {k.sleutel: k for k in KEUZES}

#: /importeren/<sleutel> die doorsturen naar een formulier elders (oude adressen blijven werken).
DOORSTUREN: dict[str, str] = {k.sleutel: k.endpoint for k in KEUZES
                              if k.endpoint and not k.endpoint.startswith("importeren_")}
