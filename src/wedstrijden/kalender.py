"""Wedstrijdplanning van één atleet of een groep: als lijst en als maandkalender.

Hoort bij de pagina 'Wedstrijdplanning' (bereikbaar vanaf de landingspagina van
een atleet). Werkt voor één master_id of voor meerdere (een groep): dan staat
per wedstrijd wie er meegaat en met welke onderdelen.

Geen SQL: alles via `Opslag`. De kalender wordt hier berekend, zodat het
template alleen hoeft te tekenen.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from db.queries import Opslag
from instellingen import eerste_weekdag
from models import Wedstrijd

MAANDNAMEN = ("januari", "februari", "maart", "april", "mei", "juni", "juli",
              "augustus", "september", "oktober", "november", "december")


@dataclass
class Deelname:
    atleet_id: str                    # master_id
    naam: str                         # voor de groepsweergave
    onderdelen: list[str]             # [] = gaat mee, onderdelen volgen later


@dataclass
class PlanningRegel:
    wedstrijd: Wedstrijd
    deelnames: list[Deelname]
    dagen_tot: int                    # negatief = geweest

    @property
    def geweest(self) -> bool:
        return self.dagen_tot < 0

    @property
    def onderdelen(self) -> list[str]:
        """Alle onderdelen samen (handig bij één atleet)."""
        return sorted({o for d in self.deelnames for o in d.onderdelen})


@dataclass
class KalenderDag:
    datum: date
    in_maand: bool                    # False = opvuldag uit de vorige/volgende maand
    vandaag: bool
    regels: list[PlanningRegel] = field(default_factory=list)


@dataclass
class KalenderMaand:
    jaar: int
    maand: int
    weken: list[list[KalenderDag]]
    regels: list[PlanningRegel]       # de wedstrijden in deze maand, op datum

    @property
    def naam(self) -> str:
        return f"{MAANDNAMEN[self.maand - 1]} {self.jaar}"

    @property
    def anker(self) -> str:
        return f"{self.jaar}-{self.maand:02d}"


@dataclass
class Wedstrijdplanning:
    regels: list[PlanningRegel]
    maanden: list[KalenderMaand]
    van: date
    groep: bool                       # meer dan één atleet: namen tonen

    @property
    def komend(self) -> list[PlanningRegel]:
        return [r for r in self.regels if not r.geweest]

    @property
    def geweest(self) -> list[PlanningRegel]:
        return [r for r in self.regels if r.geweest]


def _regels(db: Opslag, master_ids: list[str], van: date, tot: date | None, vandaag: date) -> list[PlanningRegel]:
    namen_onderdeel = {o.id: o.naam for o in db.onderdelen()}
    per_wedstrijd: dict[int, dict[str, list[str]]] = {}
    for mid in master_ids:
        for i in db.inschrijvingen(mid):
            lijst = per_wedstrijd.setdefault(i.wedstrijd_id, {}).setdefault(mid, [])
            if i.onderdeel_id is not None:
                lijst.append(namen_onderdeel[i.onderdeel_id])
    namen = {}
    for mid in master_ids:
        a = db.atleet(mid)
        namen[mid] = a.naam if a else "?"
    volgorde = {mid: n for n, mid in enumerate(master_ids)}
    uit = []
    for wid, deelnemers in per_wedstrijd.items():
        w = db.wedstrijd(wid)
        if w is None or w.datum < van or (tot is not None and w.datum > tot):
            continue
        deelnames = [Deelname(mid, namen[mid], sorted(o))
                     for mid, o in sorted(deelnemers.items(), key=lambda kv: volgorde[kv[0]])]
        uit.append(PlanningRegel(w, deelnames, (w.datum - vandaag).days))
    return sorted(uit, key=lambda r: (r.wedstrijd.datum, r.wedstrijd.naam))


def _maanden(regels: list[PlanningRegel], vandaag: date, min_maanden: int) -> list[KalenderMaand]:
    """Maandkalenders van de eerste wedstrijd (of deze maand) tot de laatste, minimaal min_maanden."""
    begin = min([vandaag.replace(day=1)] + [r.wedstrijd.datum.replace(day=1) for r in regels])
    eind = max([r.wedstrijd.datum.replace(day=1) for r in regels] + [vandaag.replace(day=1)])
    jaar, maand = begin.year, begin.month
    aantal = (eind.year - jaar) * 12 + eind.month - maand + 1
    # minimaal min_maanden vanaf deze maand
    vanaf_nu = (vandaag.year - jaar) * 12 + vandaag.month - maand
    aantal = max(aantal, vanaf_nu + min_maanden)

    per_dag: dict[date, list[PlanningRegel]] = {}
    for r in regels:
        per_dag.setdefault(r.wedstrijd.datum, []).append(r)

    kal = calendar.Calendar(firstweekday=eerste_weekdag())    # zie Instellingen
    uit = []
    for _ in range(aantal):
        weken = [[KalenderDag(d, d.month == maand, d == vandaag, per_dag.get(d, [])) for d in week]
                 for week in kal.monthdatescalendar(jaar, maand)]
        in_maand = [r for r in regels if (r.wedstrijd.datum.year, r.wedstrijd.datum.month) == (jaar, maand)]
        uit.append(KalenderMaand(jaar, maand, weken, in_maand))
        jaar, maand = (jaar + 1, 1) if maand == 12 else (jaar, maand + 1)
    return uit


def wedstrijdplanning(db: Opslag, master_ids: str | Iterable[str], *, van: date | None = None,
                      tot: date | None = None, peildatum: date | None = None,
                      weken_terug: int = 8, min_maanden: int = 3) -> Wedstrijdplanning:
    """De planning voor één atleet (master_id) of een groep (lijst master_ids).

    van:         eerste datum; standaard `weken_terug` weken voor vandaag, zodat
                 recente wedstrijden ook nog in beeld zijn.
    tot:         laatste datum; standaard alles wat gepland is.
    min_maanden: de kalender toont minstens zoveel maanden vanaf deze maand.
    """
    vandaag = peildatum or date.today()
    ids = [master_ids] if isinstance(master_ids, str) else list(dict.fromkeys(master_ids))
    begin = van or vandaag - timedelta(weeks=weken_terug)
    regels = _regels(db, ids, begin, tot, vandaag)
    return Wedstrijdplanning(regels, _maanden(regels, vandaag, min_maanden), begin, len(ids) > 1)
