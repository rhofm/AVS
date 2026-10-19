"""Startpagina: de pagina die opent als AVS start.

Vier grote tegels naar de hoofdonderdelen (Atleten, Groepen, Ploegen,
Wedstrijden), elk met een kort cijfer zodat je in één oogopslag ziet wat er is.
Importeren en Instellingen blijven bovenin de appbalk staan.

Alleen tellingen en de naam/datum van de eerstvolgende wedstrijd: geen namen
van atleten op deze pagina.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from db.queries import Opslag
from ui.opmaak import datum_kort


@dataclass(frozen=True, slots=True)
class Tegel:
    sleutel: str            # pad en icoon: /atleten, /groepen, ...
    titel: str
    uitleg: str             # wat je er kunt doen
    cijfer: str | None      # groot getal op de tegel, of None
    cijfer_label: str       # tekst onder het getal ('actieve atleten', 'binnenkort')
    extra: str | None = None


def _meervoud(n: int, enkel: str, meer: str) -> str:
    return enkel if n == 1 else meer


def tegels(db: Opslag, vandaag: date | None = None) -> list[Tegel]:
    """De vier tegels voor de startpagina, in vaste volgorde."""
    vandaag = vandaag or date.today()

    n_atleten = len(db.atleten(alleen_actief=True))
    n_groepen = len(db.groepen())
    komend = db.wedstrijden(van=vandaag)
    n_ploegen = sum(1 for p in db.ploegen() if p.datum >= vandaag)
    volgende = (f"Eerstvolgende: {komend[0].naam} · {datum_kort(komend[0].datum)}"
                if komend else None)

    return [
        Tegel("atleten", "Atleten", "Zoeken, profielen, PR's, notities en leerdoelen.",
              str(n_atleten), _meervoud(n_atleten, "actieve atleet", "actieve atleten")),
        Tegel("groepen", "Groepen", "Trainingsgroepen, trainingen en aanwezigheid.",
              str(n_groepen), _meervoud(n_groepen, "groep", "groepen")),
        Tegel("ploegen", "Ploegen", "Competitieploegen samenstellen en opstellingen maken.",
              str(n_ploegen), _meervoud(n_ploegen, "komende ploeg", "komende ploegen")),
        Tegel("wedstrijden", "Wedstrijden", "Komende wedstrijden plannen en inschrijven.",
              str(len(komend)), _meervoud(len(komend), "komende wedstrijd", "komende wedstrijden"), volgende),
    ]
