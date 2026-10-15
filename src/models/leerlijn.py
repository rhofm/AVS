"""Dataclasses Leerlijn, LeerlijnStap, LeerlijnVoortgang.

Horen bij personen.db (tabellen leerlijn, leerlijn_stap, atleet_leerlijn).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True)
class LeerlijnStap:
    volgorde: int                   # 1, 2, 3, ... binnen de leerlijn
    naam: str
    beschrijving: str | None = None
    leerlijn_id: int | None = None
    id: int | None = None


@dataclass(slots=True)
class Leerlijn:
    naam: str
    beschrijving: str | None = None
    stappen: list[LeerlijnStap] = field(default_factory=list)
    id: int | None = None

    def __post_init__(self) -> None:
        self.stappen.sort(key=lambda s: s.volgorde)

    def stap(self, volgorde: int) -> LeerlijnStap | None:
        return next((s for s in self.stappen if s.volgorde == volgorde), None)

    def volgende_stap(self, behaalde_stap_ids: set[int]) -> LeerlijnStap | None:
        """De eerste stap die nog niet behaald is (None als alles behaald is)."""
        return next((s for s in self.stappen if s.id not in behaalde_stap_ids), None)


@dataclass(slots=True)
class LeerlijnVoortgang:
    """Waar een atleet staat: één behaalde (of lopende) stap (tabel atleet_leerlijn)."""
    atleet_id: str                  # master_id
    stap_id: int
    behaald_op: date | None = None  # None = wel toegewezen, nog niet behaald
    notities: str | None = None

    @property
    def behaald(self) -> bool:
        return self.behaald_op is not None
