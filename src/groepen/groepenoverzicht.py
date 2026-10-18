"""Het groepenoverzicht (pagina 'Groepen'): zoeken, filteren en sorteren.

Eén zoekvak doorzoekt naam, seizoen, trainingsdagen en het aantal atleten
tegelijk: elk woord moet ergens voorkomen, zonder op hoofdletters of accenten
te letten. 'sprint 2026' vindt sprintgroepen van seizoen 2026-2027,
'dinsdag' (of 'di') de groepen die op dinsdag trainen en '12 atleten' de
groepen met 12 atleten. Daarnaast twee keuzelijsten: seizoen en trainingsdag.

De sorteersleutels per kolom gaan mee naar de pagina (data-sort), zodat
static/sorteer.js op elke kolom kan sorteren. Zelfde opzet als atleten.overzicht.
Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from atleten.landingspagina import DAG_KORT
from atleten.overzicht import plat
from db.queries import Opslag
from instellingen import dagvolgorde, tijd as toon_tijd
from models import Groep

from .landingspagina import trainingsdagen

GEEN_SEIZOEN = "-"                     # keuze 'zonder seizoen' in de keuzelijst


@dataclass
class GroepRij:
    groep: Groep
    dagen: list[str]                   # weekdagen waarop de groep traint, maandag eerst: ['dinsdag', 'donderdag']
    labels: list[str]                  # zoals getoond: ['Di 18:30', 'Do']

    @property
    def aantal(self) -> int:
        return len(self.groep.leden)

    @property
    def zoektekst(self) -> str:
        """Alles waarop gezocht kan worden, plat gemaakt."""
        delen = [self.groep.naam, self.groep.seizoen or "", *self.dagen, *self.labels,
                 f"{self.aantal} {'atleet' if self.aantal == 1 else 'atleten'}"]
        return plat(" ".join(delen))

    # ---- sorteersleutels (data-sort) ----
    @property
    def sort_naam(self) -> str:
        return plat(self.groep.naam)

    @property
    def sort_seizoen(self) -> str:
        return plat(self.groep.seizoen)                       # leeg = onderaan

    @property
    def sort_dagen(self) -> str:
        """'13' voor di + do: groepen die vroeg in de week beginnen eerst. Leeg = geen dagen (onderaan).
        'Vroeg in de week' volgt de eerste dag uit Instellingen."""
        volgorde = dagvolgorde()
        return "".join(str(volgorde.index(d)) for d in self.dagen)


@dataclass
class Groepenoverzicht:
    rijen: list[GroepRij]              # na zoeken en filteren, op naam
    totaal: int
    zoek: str
    seizoen: str                       # gekozen filter, '' = alle, GEEN_SEIZOEN = zonder seizoen
    dag: str                           # gekozen filter, '' = alle, anders 'dinsdag'
    seizoenen: list[str]               # keuzelijst: nieuwste eerst
    zonder_seizoen: bool               # er zijn groepen zonder seizoen (extra keuze)
    dagkeuzes: list[tuple[str, str]]   # keuzelijst: (dag, 'Dinsdag'), alleen dagen waarop een groep traint

    @property
    def gefilterd(self) -> bool:
        return bool(self.zoek or self.seizoen or self.dag)


def past(rij: GroepRij, zoek: str = "", seizoen: str = "", dag: str = "") -> bool:
    """Voldoet deze rij aan het zoekvak en de filters?"""
    if seizoen == GEEN_SEIZOEN and rij.groep.seizoen:
        return False
    if seizoen and seizoen != GEEN_SEIZOEN and rij.groep.seizoen != seizoen:
        return False
    if dag and dag not in rij.dagen:
        return False
    hooiberg = rij.zoektekst
    return all(woord in hooiberg for woord in plat(zoek).split())


def groepenoverzicht(db: Opslag, *, zoek: str = "", seizoen: str = "", dag: str = "",
                     peildatum: date | None = None) -> Groepenoverzicht:
    vandaag = peildatum or date.today()
    alle = []
    for g in db.groepen():
        dagen, _ = trainingsdagen(db, g, vandaag)
        gesorteerd = [d for d in dagvolgorde() if d in dagen]
        labels = [f"{DAG_KORT[d]} {' & '.join(toon_tijd(t) for t in g.tijden(d))}" if g.tijden(d) else DAG_KORT[d]
                  for d in gesorteerd]
        alle.append(GroepRij(g, gesorteerd, labels))
    alle.sort(key=lambda r: r.sort_naam)

    seizoenen = sorted({r.groep.seizoen for r in alle if r.groep.seizoen}, reverse=True)
    zonder = any(not r.groep.seizoen for r in alle)
    seizoen = (seizoen or "").strip()
    if seizoen not in seizoenen and not (seizoen == GEEN_SEIZOEN and zonder):
        seizoen = ""
    aanwezig = {d for r in alle for d in r.dagen}
    dag = (dag or "").strip().lower()
    if dag not in aanwezig:
        dag = ""
    return Groepenoverzicht(
        rijen=[r for r in alle if past(r, zoek, seizoen, dag)],
        totaal=len(alle), zoek=(zoek or "").strip(), seizoen=seizoen, dag=dag,
        seizoenen=seizoenen, zonder_seizoen=zonder,
        dagkeuzes=[(d, d.capitalize()) for d in dagvolgorde() if d in aanwezig],
    )
