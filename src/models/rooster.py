"""Rooster: geplande trainingsinhoud per week, als sjabloon dat een groep vanaf een datum volgt.

Hoort bij personen.db (tabellen rooster, rooster_regel, groep_rooster, zie schema_personen.sql).
Geen persoonsgegevens.

    r = Rooster("Najaar U16", 4, regels=[RoosterRegel(1, "dinsdag", onderwerp="Starts"), ...])
    k = GroepRooster(groep_id, r.id, date(2026, 10, 5))     # vanaf maandag 5 oktober, herhalen
    k.week_op(date(2026, 10, 20), r.aantal_weken)            # -> 3

Weeknummers tellen vanaf de start van de koppeling, los van de mesocyclus.
Welke regel bij een training hoort en het kopiëren naar trainingen: groepen/rooster.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .groep import TRAININGSONDERDELEN, normaliseer_tijd
from .trainingsschema import DAGEN

MAX_WEKEN = 60                         # langste rooster (ruim een seizoen)

#: De inhoud van een training en een roosterregel: (veld, titel in de app, maximale lengte).
INHOUD: tuple[tuple[str, str, int], ...] = (
    ("onderwerp", "Onderwerp", 120),
    *((veld, titel, 10_000) for veld, titel in TRAININGSONDERDELEN),
    ("notities", "Notities", 10_000),
)
INHOUD_VELDEN: tuple[str, ...] = tuple(v for v, _, _ in INHOUD)


def _tekst(waarde) -> str | None:
    """Lege tekst wordt None, regeleinden gelijk getrokken (zoals bij Training)."""
    if waarde is None:
        return None
    return str(waarde).replace("\r\n", "\n").strip() or None


@dataclass(slots=True)
class RoosterRegel:
    """Wat er in week `week` op `dag` (en begintijd) wordt gedaan. starttijd None = de vaste tijd van die dag."""
    week: int
    dag: str
    starttijd: str | None = None
    onderwerp: str | None = None
    warming_up: str | None = None
    kern_a: str | None = None
    kern_b: str | None = None
    cooling_down: str | None = None
    notities: str | None = None
    rooster_id: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        self.dag = str(self.dag).lower()
        if self.dag not in DAGEN:
            raise ValueError(f"Onbekende dag {self.dag!r}.")
        if int(self.week) < 1:
            raise ValueError("Weeknummers beginnen bij 1.")
        self.week = int(self.week)
        self.starttijd = normaliseer_tijd(self.starttijd)
        for veld in INHOUD_VELDEN:
            setattr(self, veld, _tekst(getattr(self, veld)))

    @property
    def inhoud(self) -> dict[str, str | None]:
        return {v: getattr(self, v) for v in INHOUD_VELDEN}

    @property
    def leeg(self) -> bool:
        return not any(self.inhoud.values())

    @property
    def aantal_delen(self) -> int:
        """Hoeveel velden naast het onderwerp zijn ingevuld (warming-up … notities)."""
        return sum(1 for v in INHOUD_VELDEN[1:] if getattr(self, v))

    @property
    def moment(self) -> tuple[int, str, str | None]:
        return (self.week, self.dag, self.starttijd)


@dataclass(slots=True)
class Rooster:
    naam: str
    aantal_weken: int
    regels: list[RoosterRegel] = field(default_factory=list)
    id: int | None = None

    def __post_init__(self) -> None:
        self.naam = " ".join(str(self.naam or "").split())
        if not self.naam:
            raise ValueError("Geef het rooster een naam.")
        if not 1 <= int(self.aantal_weken) <= MAX_WEKEN:
            raise ValueError(f"Een rooster heeft 1 tot {MAX_WEKEN} weken.")
        self.aantal_weken = int(self.aantal_weken)


@dataclass(slots=True)
class GroepRooster:
    """Een groep volgt een rooster vanaf startdatum (begin van week 1), tot de volgende koppeling."""
    groep_id: int
    rooster_id: int
    startdatum: date
    herhalen: bool = True
    einddatum: date | None = None

    def __post_init__(self) -> None:
        if self.einddatum is not None and self.einddatum < self.startdatum:
            raise ValueError("De einddatum ligt voor de startdatum.")

    def week_op(self, datum: date, aantal_weken: int) -> int | None:
        """Roosterweek (1..aantal_weken) op datum, of None: vóór de start, na de einddatum, of
        (zonder herhalen) na de laatste week."""
        if datum < self.startdatum or (self.einddatum is not None and datum > self.einddatum):
            return None
        weken = (datum - self.startdatum).days // 7
        if not self.herhalen and weken >= aantal_weken:
            return None
        return weken % aantal_weken + 1
