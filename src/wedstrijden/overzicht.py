"""Het wedstrijdenoverzicht (pagina 'Wedstrijden'): alle wedstrijden van de club.

Bovenaan de komende wedstrijden (vandaag meegerekend), vroegste eerst. De
afgelopen wedstrijden staan eronder, nieuwste eerst; de pagina toont die pas
als 'Afgelopen wedstrijden' is aangevinkt. Dat zijn er snel veel, want ook
elke geïmporteerde uitslag is een wedstrijd.

Per wedstrijd het aantal ingeschreven atleten en, voor afgelopen wedstrijden,
of er al een uitslag is geïmporteerd (aantal prestaties).

Geen SQL: alles via `Opslag`. Geen namen van atleten: alleen aantallen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from db.queries import Opslag
from models import Wedstrijd


@dataclass
class WedstrijdRij:
    wedstrijd: Wedstrijd
    deelnemers: int                    # aantal ingeschreven atleten (niet per onderdeel)
    prestaties: int                    # aantal prestaties op deze wedstrijd (0 = nog geen uitslag)
    dagen_tot: int                     # 0 = vandaag, negatief = geweest

    @property
    def geweest(self) -> bool:
        return self.dagen_tot < 0


@dataclass
class Wedstrijdenoverzicht:
    komend: list[WedstrijdRij]         # vroegste eerst
    afgelopen: list[WedstrijdRij]      # nieuwste eerst


def _rij(db: Opslag, w: Wedstrijd, vandaag: date, *, met_prestaties: bool) -> WedstrijdRij:
    deelnemers = len({i.atleet_id for i in db.deelnemers(w.id)})
    prestaties = len(db.prestaties_van_wedstrijd(w.id)) if met_prestaties else 0
    return WedstrijdRij(w, deelnemers, prestaties, (w.datum - vandaag).days)


def wedstrijdenoverzicht(db: Opslag, peildatum: date | None = None) -> Wedstrijdenoverzicht:
    vandaag = peildatum or date.today()
    komend, afgelopen = [], []
    for w in db.wedstrijden():                          # op datum
        if w.datum >= vandaag:
            komend.append(_rij(db, w, vandaag, met_prestaties=False))
        else:
            afgelopen.append(_rij(db, w, vandaag, met_prestaties=True))
    komend.sort(key=lambda r: (r.wedstrijd.datum, r.wedstrijd.naam.lower()))
    afgelopen.sort(key=lambda r: (r.wedstrijd.datum, r.wedstrijd.naam.lower()), reverse=True)
    return Wedstrijdenoverzicht(komend, afgelopen)
