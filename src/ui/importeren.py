"""Importeerpagina: de keuzepagina achter 'Importeren' in de appbalk.

Drie grote tegels, één per soort import:
  * Atleet      – één atleet toevoegen van zijn atletiek.nu-profiel, met al zijn prestaties
                  (atleten/atleet_toevoegen_atletieknu.py);
  * Groep       – een hele groep atleten in één keer, uit een ledenlijst (CSV) met hun
                  atletiek.nu-nummers (groepen/atleten_uit_csv.py);
  * Wedstrijd   – de uitslagen van een wedstrijd van atletiek.nu of Seltec, gekoppeld aan
                  onze atleten (importers/).

Elke tegel gaat naar een eigen pagina (/importeren/<sleutel>). Zolang die pagina nog
niet gebouwd is, toont de app daar 'Deze pagina komt nog'.

Geen gegevens van atleten op deze pagina: alleen uitleg.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Importkeuze:
    sleutel: str        # pad en icoon: /importeren/atleet, ...
    titel: str
    uitleg: str         # wat er gebeurt
    bron: str           # waar de gegevens vandaan komen
    nodig: str          # wat je bij de hand moet hebben


KEUZES: tuple[Importkeuze, ...] = (
    Importkeuze("atleet", "Atleet",
                "Eén atleet toevoegen met al zijn prestaties. Staat de atleet er al, dan worden "
                "alleen de nieuwe prestaties toegevoegd.",
                "atletiek.nu", "de link naar het profiel of het atletiek.nu-nummer"),
    Importkeuze("groep", "Groep",
                "Een hele groep atleten in één keer, elk met al zijn prestaties. Bestaande "
                "atleten en prestaties worden herkend en niet dubbel opgeslagen.",
                "ledenlijst + atletiek.nu", "een CSV-bestand met naam, geboortedatum en atletiek.nu-nummer"),
    Importkeuze("wedstrijd", "Wedstrijd",
                "De uitslagen van een wedstrijd ophalen en koppelen aan onze atleten. Een geplande "
                "wedstrijd krijgt zo vanzelf zijn uitslagen.",
                "atletiek.nu of Seltec", "de link naar de wedstrijd of de uitslagen"),
)

#: sleutel → keuze, voor de routes.
PER_SLEUTEL: dict[str, Importkeuze] = {k.sleutel: k for k in KEUZES}
