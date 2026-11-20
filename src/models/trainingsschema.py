"""Dataclass Trainingsschema: op welke dagen van de week een atleet traint.

Hoort bij trainingsschema.db. In de database staat de atleet als pseudoniem
(atleet_ref); in dit model altijd als master_id (`atleet_id`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    # Gekozen trainingen per weekdag als er meer zijn (trainingsschema.db: trainingskeuze,
    # zie schema_trainingsschema.sql): {'zaterdag': {(groep_id, '10:30')}}. Een dag zonder keuze = alle
    # trainingen van de groepen van de atleet. Opslaan via Opslag.trainingskeuze_opslaan().
    keuze: dict[str, set[tuple[int, str]]] = field(default_factory=dict)

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

    def traint_mee(self, training, groep=None) -> bool:
        """Doet de atleet mee aan deze training (models.Training) van deze groep (models.Groep)?

        Alleen als hij die weekdag traint. Heeft hij voor die dag een keuze gemaakt,
        dan alleen bij een gekozen training. Trainingen die niet te kiezen zijn (de
        groep heeft op die tijd geen vaste training, bijv. een losse extra training)
        tellen gewoon mee.
        """
        if not self.traint_op(training.datum):
            return False
        dag = DAGEN[training.datum.weekday()]
        gekozen = self.keuze.get(dag)
        if not gekozen:
            return True
        tijd = training.effectieve_starttijd(groep)
        if (training.groep_id, tijd) in gekozen:
            return True
        kiesbaar = groep is not None and tijd in groep.tijden(dag)
        return not kiesbaar

    def traint_op(self, dag_of_datum: str | date) -> bool:
        """Traint de atleet op deze dag ('dinsdag') of datum (date(2026, 10, 20))?"""
        if isinstance(dag_of_datum, date):
            dag = DAGEN[dag_of_datum.weekday()]
        else:
            dag = dag_of_datum.lower()
            if dag not in DAGEN:
                raise ValueError(f"Onbekende dag {dag_of_datum!r}; kies uit {DAGEN}.")
        return getattr(self, dag)
