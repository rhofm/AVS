"""Dataclasses Groep, Training, Absentie, Periodeplan.

Horen bij personen.db. Atleten worden aangeduid met hun master_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

AbsentieStatus = Literal["aanwezig", "afgemeld", "afwezig", "blessure"]
ABSENTIE_STATUSSEN: tuple[str, ...] = ("aanwezig", "afgemeld", "afwezig", "blessure")


@dataclass(slots=True)
class Groep:
    naam: str
    seizoen: str | None = None                       # bijv. '2026-2027'
    leden: list[str] = field(default_factory=list)   # master_ids (tabel groep_lid)
    id: int | None = None

    def voeg_toe(self, master_id: str) -> None:
        if master_id not in self.leden:
            self.leden.append(master_id)

    def verwijder(self, master_id: str) -> None:
        if master_id in self.leden:
            self.leden.remove(master_id)


@dataclass(slots=True)
class Periodeplan:
    naam: str                       # bijv. 'Algemene voorbereiding'
    startdatum: date
    einddatum: date
    groep_id: int | None = None
    doel: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.einddatum < self.startdatum:
            raise ValueError("einddatum ligt voor startdatum.")

    def bevat(self, datum: date) -> bool:
        return self.startdatum <= datum <= self.einddatum

    @property
    def aantal_weken(self) -> int:
        return (self.einddatum - self.startdatum).days // 7 + 1


@dataclass(slots=True)
class Training:
    groep_id: int
    datum: date
    onderwerp: str | None = None
    inhoud: str | None = None
    periodeplan_id: int | None = None
    id: int | None = None


@dataclass(slots=True)
class Absentie:
    training_id: int
    atleet_id: str                  # master_id
    status: AbsentieStatus
    reden: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ABSENTIE_STATUSSEN:
            raise ValueError(f"Onbekende status {self.status!r}; kies uit {ABSENTIE_STATUSSEN}.")

    @property
    def aanwezig(self) -> bool:
        return self.status == "aanwezig"
