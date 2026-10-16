"""Dataclasses Groep, Training, Absentie, Periodeplan.

Horen bij personen.db. Atleten worden aangeduid met hun master_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Literal

from .trainingsschema import DAGEN

AbsentieStatus = Literal["aanwezig", "afgemeld", "afwezig", "blessure"]
ABSENTIE_STATUSSEN: tuple[str, ...] = ("aanwezig", "afgemeld", "afwezig", "blessure")


_TIJD_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def normaliseer_tijd(tijd: str | None) -> str | None:
    """'18:30', '9:00', '9.00' -> 'HH:MM'. Leeg of None -> None. Ongeldig -> ValueError."""
    if tijd is None or not str(tijd).strip():
        return None
    m = _TIJD_RE.match(str(tijd))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"Ongeldige starttijd {tijd!r}; gebruik bijv. '18:30'.")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


@dataclass(slots=True)
class Groep:
    naam: str
    seizoen: str | None = None                       # bijv. '2026-2027'
    leden: list[str] = field(default_factory=list)   # master_ids (tabel groep_lid)
    id: int | None = None
    # Vaste trainingstijden (tabel groep_trainingstijden): {'dinsdag': '18:30', 'donderdag': '19:00'}.
    # Een dag die er niet in staat = geen training. Leeg = geen vaste dagen ingesteld.
    # De tijden horen bij de groep, niet bij de atleet. Opslaan via
    # Opslag.groep_trainingsdagen_opslaan() (los van groep_opslaan()).
    trainingsdagen: dict[str, str] = field(default_factory=dict)

    def starttijd(self, dag: str) -> str | None:
        return self.trainingsdagen.get(dag.lower())

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
