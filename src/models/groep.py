"""Dataclasses Groep, Training, Absentie.

De periodisering (fasen, mesocycli) staat in models/periodisering.py.

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
    # Extra begintijden op dezelfde dag (tabel groep_extra_trainingstijd, migratie 006):
    # {'zaterdag': ['10:30']}. Alleen op dagen die ook in trainingsdagen staan.
    # Opslaan via Opslag.groep_extra_tijden_opslaan().
    extra_tijden: dict[str, list[str]] = field(default_factory=dict)

    def starttijd(self, dag: str) -> str | None:
        """De vaste (eerste) begintijd op deze dag, of None."""
        return self.trainingsdagen.get(dag.lower())

    def tijden(self, dag: str) -> list[str]:
        """Alle begintijden op deze dag, vroegste eerst: ['09:00', '10:30']. [] = geen training."""
        dag = dag.lower()
        if dag not in self.trainingsdagen:
            return []
        return sorted({self.trainingsdagen[dag], *self.extra_tijden.get(dag, [])})

    @property
    def momenten(self) -> list[tuple[str, str]]:
        """Alle vaste trainingen in een week als (dag, tijd), van maandag t/m zondag."""
        return [(d, t) for d in DAGEN for t in self.tijden(d)]

    def voeg_toe(self, master_id: str) -> None:
        if master_id not in self.leden:
            self.leden.append(master_id)

    def verwijder(self, master_id: str) -> None:
        if master_id in self.leden:
            self.leden.remove(master_id)


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
    id: int | None = None
    warming_up: str | None = None
    kern_a: str | None = None
    kern_b: str | None = None
    cooling_down: str | None = None
    hoofdtraining_id: int | None = None
    atleten: list[str] = field(default_factory=list)   # master_ids; alleen bij een afwijkende training
    # Begintijd van deze training ('HH:MM', migratie 006). None = de vaste begintijd van die dag;
    # nodig als een groep meerdere trainingen op één dag heeft. Zie effectieve_starttijd().
    starttijd: str | None = None
    # Uit welke roosterregel de inhoud komt (migratie 008). None = niet (of niet meer) uit het rooster.
    rooster_regel_id: int | None = None

    def __post_init__(self) -> None:
        # Lege tekst ('' of alleen spaties) opslaan als None; regeleinden gelijk trekken.
        for veld in ("onderwerp", "notities", *(v for v, _ in TRAININGSONDERDELEN)):
            tekst = getattr(self, veld)
            if tekst is not None:
                tekst = str(tekst).replace("\r\n", "\n").strip()
                setattr(self, veld, tekst or None)

    def effectieve_starttijd(self, groep: "Groep | None") -> str | None:
        """De begintijd: die van de training zelf, anders de vaste begintijd van de groep op die dag."""
        if self.starttijd:
            return self.starttijd
        return groep.starttijd(DAGEN[self.datum.weekday()]) if groep is not None else None

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
