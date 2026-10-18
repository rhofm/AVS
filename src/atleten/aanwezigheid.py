"""Aanwezigheid van één atleet: welke trainingen, met welke status. Als lijst en als maandkalender.

Voor de pagina 'Aanwezigheid' (bereikbaar vanaf de landingspagina van een atleet).
Leest absentie.db (statuses) en personen.db (trainingen en groepen) via `Opslag`.

Een training staat in het overzicht als:
  - er een status voor deze atleet is opgeslagen, of
  - de training van een groep van de atleet is, al geweest is, en de atleet die
    weekdag volgens zijn trainingsschema traint: dan 'niet ingevuld'.
'blessure' is gezondheidsinformatie: de reden blijft kort en feitelijk.
"""

from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from db.queries import Opslag
from instellingen import eerste_weekdag
from models import ABSENTIE_STATUSSEN, Training

NIET_INGEVULD = "niet_ingevuld"
STATUS_TEKST = {"aanwezig": "Aanwezig", "afwezig": "Afwezig", "afgemeld": "Afgemeld",
                "blessure": "Blessure", NIET_INGEVULD: "Niet ingevuld"}
MAANDNAMEN = ("januari", "februari", "maart", "april", "mei", "juni", "juli",
              "augustus", "september", "oktober", "november", "december")


@dataclass
class AanwezigheidRegel:
    training: Training
    groep: str
    status: str                      # een van ABSENTIE_STATUSSEN of NIET_INGEVULD
    reden: str | None = None

    @property
    def status_tekst(self) -> str:
        return STATUS_TEKST[self.status]


@dataclass
class AanwezigheidDag:
    datum: date
    in_maand: bool
    vandaag: bool
    regels: list[AanwezigheidRegel] = field(default_factory=list)

    @property
    def status(self) -> str | None:
        """De kleur van de dag: bij één training die status; bij meer de 'ergste'."""
        if not self.regels:
            return None
        volgorde = ["blessure", "afwezig", "afgemeld", NIET_INGEVULD, "aanwezig"]
        return min((r.status for r in self.regels), key=volgorde.index)


@dataclass
class AanwezigheidMaand:
    jaar: int
    maand: int
    weken: list[list[AanwezigheidDag]]
    telling: dict[str, int]

    @property
    def naam(self) -> str:
        return f"{MAANDNAMEN[self.maand - 1]} {self.jaar}"


@dataclass
class Aanwezigheid:
    regels: list[AanwezigheidRegel]          # nieuwste eerst
    maanden: list[AanwezigheidMaand]         # nieuwste eerst
    van: date
    tot: date
    telling: dict[str, int]                  # per status, ook NIET_INGEVULD

    @property
    def ingevuld(self) -> int:
        return sum(self.telling[s] for s in ABSENTIE_STATUSSEN)

    @property
    def percentage(self) -> float | None:
        """Aanwezig als percentage van de ingevulde trainingen; None als er niets is ingevuld."""
        return round(100 * self.telling["aanwezig"] / self.ingevuld, 1) if self.ingevuld else None


def _telling(regels: list[AanwezigheidRegel]) -> dict[str, int]:
    c = Counter(r.status for r in regels)
    return {s: c.get(s, 0) for s in (*ABSENTIE_STATUSSEN, NIET_INGEVULD)}


def _regels(db: Opslag, master_id: str, van: date, tot: date) -> list[AanwezigheidRegel]:
    groepnamen: dict[int, str] = {}

    def groepnaam(gid: int) -> str:
        if gid not in groepnamen:
            g = db.groep(gid)
            groepnamen[gid] = g.naam if g else "?"
        return groepnamen[gid]

    uit: dict[int, AanwezigheidRegel] = {}
    for a in db.absenties_van_atleet(master_id):
        t = db.training(a.training_id)
        if t is not None and van <= t.datum <= tot:
            uit[t.id] = AanwezigheidRegel(t, groepnaam(t.groep_id), a.status, a.reden)
    schema = db.trainingsschema(master_id)
    for g in db.groepen_van_atleet(master_id):
        for t in db.trainingen(g.id, van=van, tot=tot):
            if t.id not in uit and schema.traint_mee(t, g):
                uit[t.id] = AanwezigheidRegel(t, g.naam, NIET_INGEVULD)
    return sorted(uit.values(), key=lambda r: (r.training.datum, r.groep), reverse=True)


def _maanden(regels: list[AanwezigheidRegel], van: date, tot: date, vandaag: date) -> list[AanwezigheidMaand]:
    per_dag: dict[date, list[AanwezigheidRegel]] = {}
    for r in sorted(regels, key=lambda r: (r.training.datum, r.groep)):
        per_dag.setdefault(r.training.datum, []).append(r)
    kal = calendar.Calendar(firstweekday=eerste_weekdag())     # zie Instellingen
    jaar, maand = tot.year, tot.month
    uit = []
    while (jaar, maand) >= (van.year, van.month):
        weken = [[AanwezigheidDag(d, d.month == maand, d == vandaag, per_dag.get(d, []) if d.month == maand else [])
                  for d in week] for week in kal.monthdatescalendar(jaar, maand)
                 if week[0] <= tot]                      # geen weken die helemaal na `tot` vallen
        in_maand = [r for r in regels if (r.training.datum.year, r.training.datum.month) == (jaar, maand)]
        uit.append(AanwezigheidMaand(jaar, maand, weken, _telling(in_maand)))
        jaar, maand = (jaar - 1, 12) if maand == 1 else (jaar, maand - 1)
    return uit


def aanwezigheid(db: Opslag, master_id: str, *, van: date | None = None, tot: date | None = None,
                 peildatum: date | None = None, weken_terug: int = 12) -> Aanwezigheid:
    """Aanwezigheid van één atleet tussen `van` en `tot` (standaard: de laatste `weken_terug` weken t/m vandaag)."""
    vandaag = peildatum or date.today()
    tot = tot or vandaag
    van = van or vandaag - timedelta(weeks=weken_terug)
    regels = _regels(db, master_id, van, tot)
    return Aanwezigheid(regels, _maanden(regels, van, tot, vandaag), van, tot, _telling(regels))
