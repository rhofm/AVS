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
    # Starttijd per weekdag, bijv. {'dinsdag': '18:30', 'donderdag': '18:30'}.
    # Een dag die er niet in staat = geen training. De tijden horen bij de groep,
    # niet bij de atleet: iedereen in de groep heeft dezelfde tijden.
    starttijden: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.starttijden = self._controleer(self.starttijden)

    @staticmethod
    def _controleer(tijden: dict[str, str | None]) -> dict[str, str]:
        uit = {}
        for dag, tijd in (tijden or {}).items():
            dag = dag.strip().lower()
            if dag not in DAGEN:
                raise ValueError(f"Onbekende dag {dag!r}; kies uit {DAGEN}.")
            t = normaliseer_tijd(tijd)
            if t is not None:
                uit[dag] = t
        return {d: uit[d] for d in DAGEN if d in uit}          # vaste volgorde maandag -> zondag

    def zet_starttijden(self, tijden: dict[str, str | None]) -> None:
        """Vervang alle starttijden (gecontroleerd en genormaliseerd)."""
        self.starttijden = self._controleer(tijden)

    @property
    def trainingsdagen(self) -> list[str]:
        """De weekdagen waarop de groep traint, van maandag tot zondag."""
        return list(self.starttijden)

    def starttijd(self, dag: str) -> str | None:
        return self.starttijden.get(dag.lower())

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


#: De onderdelen van een training, in volgorde: (veldnaam, titel in de app).
TRAININGSONDERDELEN: tuple[tuple[str, str], ...] = (
    ("warming_up", "Warming-up"),
    ("kern_a", "Kern A"),
    ("kern_b", "Kern B"),
    ("cooling_down", "Cooling-down"),
)


@dataclass(slots=True)
class Training:
    """Eén training van een groep (tabel training in personen.db, migratie 005).

    De tekstvelden zijn meerregelig en mogen markdown bevatten (**vet**, *schuin*,
    '- ' lijstjes, '# ' kopjes). Leeg/None = niet ingevuld.

    Afwijkende training: hoofdtraining_id wijst naar de gewone training van de
    groep (zelfde groep en datum) en `atleten` zegt wie deze variant volgt. De
    gewone training heeft geen `atleten`: die geldt voor de rest van de groep.
    """
    groep_id: int
    datum: date
    onderwerp: str | None = None
    notities: str | None = None
    periodeplan_id: int | None = None
    id: int | None = None
    warming_up: str | None = None
    kern_a: str | None = None
    kern_b: str | None = None
    cooling_down: str | None = None
    hoofdtraining_id: int | None = None
    atleten: list[str] = field(default_factory=list)   # master_ids; alleen bij een afwijkende training

    def __post_init__(self) -> None:
        # Lege tekst ('' of alleen spaties) opslaan als None; regeleinden gelijk trekken.
        for veld in ("onderwerp", "notities", *(v for v, _ in TRAININGSONDERDELEN)):
            tekst = getattr(self, veld)
            if tekst is not None:
                tekst = str(tekst).replace("\r\n", "\n").strip()
                setattr(self, veld, tekst or None)

    @property
    def is_afwijkend(self) -> bool:
        return self.hoofdtraining_id is not None

    @property
    def onderdelen(self) -> list[tuple[str, str]]:
        """Ingevulde onderdelen als (titel, tekst), in volgorde warming-up -> cooling-down."""
        return [(titel, getattr(self, veld)) for veld, titel in TRAININGSONDERDELEN if getattr(self, veld)]


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
