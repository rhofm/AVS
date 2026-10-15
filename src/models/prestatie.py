"""Dataclasses Prestatie, Onderdeel, Wedstrijd, Inschrijving, PR, Test, Testresultaat.

Horen bij prestaties.db en testen.db. In de database staat een atleet daar als
pseudoniem (atleet_ref); in deze modellen altijd als master_id (`atleet_id`).
db/ rekent het een om naar het ander bij lezen en schrijven.

Importers kennen de master_id nog niet als ze een pagina lezen. Zij vullen
`bron_naam` / `bron_atletieknu_id` om de atleet in personen.db te kunnen
vinden. Die velden zijn tijdelijk: na het koppelen gaan ze weg (zie
`gekoppeld()`) en ze worden nooit opgeslagen.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Iterable, Literal

Bron = Literal["atletieknu", "seltec", "handmatig"]
BRONNEN: tuple[str, ...] = ("atletieknu", "seltec", "handmatig")

Eenheid = Literal["tijd", "afstand", "hoogte", "punten"]
EENHEDEN: tuple[str, ...] = ("tijd", "afstand", "hoogte", "punten")


def _controleer_bron(bron: str | None) -> None:
    if bron is not None and bron not in BRONNEN:
        raise ValueError(f"Onbekende bron {bron!r}; kies uit {BRONNEN}.")


@dataclass(slots=True)
class Onderdeel:
    naam: str                       # bijv. '100m', 'Verspringen', '60m horden 76,2cm'
    eenheid: Eenheid
    lager_is_beter: bool            # True voor looponderdelen, False voor technische
    categorie: str | None = None    # sprint, horden, midden, springen, werpen, meerkamp
    id: int | None = None

    def __post_init__(self) -> None:
        if self.eenheid not in EENHEDEN:
            raise ValueError(f"Onbekende eenheid {self.eenheid!r}; kies uit {EENHEDEN}.")

    def is_beter(self, a: float, b: float) -> bool:
        """Is waarde a beter dan waarde b op dit onderdeel?"""
        return a < b if self.lager_is_beter else a > b

    def beste(self, waarden: Iterable[float]) -> float | None:
        waarden = list(waarden)
        if not waarden:
            return None
        return min(waarden) if self.lager_is_beter else max(waarden)


@dataclass(slots=True)
class Wedstrijd:
    naam: str
    datum: date
    locatie: str | None = None
    bron: Bron | None = None
    bron_url: str | None = None     # uitslagpagina van de wedstrijd, nooit van een atleet
    id: int | None = None

    def __post_init__(self) -> None:
        _controleer_bron(self.bron)


@dataclass(slots=True)
class Prestatie:
    onderdeel: str                  # naam van het onderdeel, zoals de bron hem geeft
    datum: date
    waarde: float                   # seconden / meters / punten
    atleet_id: str | None = None    # master_id; None zolang de importer nog niet heeft gekoppeld
    onderdeel_id: int | None = None
    wedstrijd_id: int | None = None
    wind: float | None = None
    ronde: str = ""                 # serie, finale, ... ('' en niet None, zie schema)
    bron: Bron | None = None
    id: int | None = None

    # Alleen voor importers, om de atleet te vinden. Nooit opslaan.
    bron_naam: str | None = field(default=None, repr=False)
    bron_atletieknu_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _controleer_bron(self.bron)
        if self.ronde is None:
            self.ronde = ""

    @property
    def is_gekoppeld(self) -> bool:
        return self.atleet_id is not None

    def gekoppeld(self, master_id: str) -> Prestatie:
        """Kopie met de atleet ingevuld en de tijdelijke bron-gegevens gewist."""
        return replace(self, atleet_id=master_id, bron_naam=None, bron_atletieknu_id=None)


@dataclass(slots=True)
class Inschrijving:
    """Een geplande wedstrijd voor een atleet (tabel `inschrijving`)."""
    atleet_id: str
    wedstrijd_id: int
    onderdeel_id: int | None = None


@dataclass(slots=True, frozen=True)
class PR:
    """Persoonlijk record, afgeleid uit de view `pr`. Wordt nooit zelf opgeslagen."""
    atleet_id: str
    onderdeel_id: int
    waarde: float


@dataclass(slots=True)
class Test:
    naam: str                       # bijv. '30m vliegend', 'Kogelstoten achterwaarts'
    eenheid: str
    lager_is_beter: bool
    id: int | None = None

    def is_beter(self, a: float, b: float) -> bool:
        return a < b if self.lager_is_beter else a > b


@dataclass(slots=True)
class Testresultaat:
    atleet_id: str                  # master_id
    test_id: int
    datum: date
    waarde: float
    notities: str | None = None
    id: int | None = None
