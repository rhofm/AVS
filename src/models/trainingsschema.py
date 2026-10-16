"""Dataclass Trainingsschema: op welke dagen van de week een atleet traint.

Hoort bij trainingsschema.db. In de database staat de atleet als pseudoniem
(atleet_ref); in dit model altijd als master_id (`atleet_id`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Volgorde van date.weekday(): maandag = 0, zondag = 6.
DAGEN: tuple[str, ...] = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


@dataclass(slots=True)
class Trainingsschema:
    atleet_id: str                  # master_id
    maandag: bool = False
    dinsdag: bool = False
    woensdag: bool = False
    donderdag: bool = False
    vrijdag: bool = False
    zaterdag: bool = False
    zondag: bool = False

    @classmethod
    def met_dagen(cls, atleet_id: str, dagen: list[str] | tuple[str, ...]) -> Trainingsschema:
        """Trainingsschema(…, dagen=['dinsdag', 'donderdag']) in één regel."""
        onbekend = [d for d in dagen if d not in DAGEN]
        if onbekend:
            raise ValueError(f"Onbekende dag(en) {onbekend}; kies uit {DAGEN}.")
        return cls(atleet_id, **{d: True for d in dagen})

    @property
    def dagen(self) -> list[str]:
        """De trainingsdagen, van maandag tot zondag."""
        return [d for d in DAGEN if getattr(self, d)]

    @property
    def aantal_per_week(self) -> int:
        return len(self.dagen)

    def traint_op(self, dag_of_datum: str | date) -> bool:
        """Traint de atleet op deze dag ('dinsdag') of datum (date(2026, 10, 20))?"""
        if isinstance(dag_of_datum, date):
            dag = DAGEN[dag_of_datum.weekday()]
        else:
            dag = dag_of_datum.lower()
            if dag not in DAGEN:
                raise ValueError(f"Onbekende dag {dag_of_datum!r}; kies uit {DAGEN}.")
        return getattr(self, dag)
