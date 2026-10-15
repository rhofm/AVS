"""Alles over één atleet in één object, voor de profielpagina in de UI.

Haalt gegevens uit alle drie de databases bij elkaar; de UI hoeft niets te
weten van pseudoniemen of losse bestanden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from db.queries import Opslag
from models import Atleet, Groep, Leerlijn, LeerlijnStap, Onderdeel, Prestatie, Test, Testresultaat, Wedstrijd

from .testen import laatste_per_test


@dataclass
class PRRegel:
    onderdeel: Onderdeel
    waarde: float


@dataclass
class GeplandeWedstrijd:
    wedstrijd: Wedstrijd
    onderdeel: Onderdeel | None


@dataclass
class TestRegel:
    test: Test
    laatste: Testresultaat


@dataclass
class LeerlijnStand:
    leerlijn: Leerlijn
    behaald: int                         # aantal behaalde stappen
    volgende: LeerlijnStap | None        # None = leerlijn afgerond

    @property
    def totaal(self) -> int:
        return len(self.leerlijn.stappen)


@dataclass
class AtleetProfiel:
    atleet: Atleet
    leeftijd: int | None
    prs: list[PRRegel] = field(default_factory=list)
    recente_prestaties: list[Prestatie] = field(default_factory=list)
    geplande_wedstrijden: list[GeplandeWedstrijd] = field(default_factory=list)
    testen: list[TestRegel] = field(default_factory=list)
    leerlijnen: list[LeerlijnStand] = field(default_factory=list)
    groepen: list[Groep] = field(default_factory=list)


def profiel(db: Opslag, master_id: str, *, peildatum: date | None = None,
            aantal_recent: int = 10) -> AtleetProfiel | None:
    """Het volledige profiel van één atleet, of None als de atleet niet bestaat."""
    atleet = db.atleet(master_id)
    if atleet is None:
        return None
    vandaag = peildatum or date.today()
    onderdelen = {o.id: o for o in db.onderdelen()}

    prs = sorted(
        (PRRegel(onderdelen[pr.onderdeel_id], pr.waarde) for pr in db.prs(master_id)),
        key=lambda r: (r.onderdeel.categorie or "", r.onderdeel.naam),
    )

    gepland = []
    for i in db.inschrijvingen(master_id):
        w = db.wedstrijd(i.wedstrijd_id)
        if w and w.datum >= vandaag:
            gepland.append(GeplandeWedstrijd(w, onderdelen.get(i.onderdeel_id)))

    testen_per_id = {t.id: t for t in db.testen()}
    testregels = sorted(
        (TestRegel(testen_per_id[tid], r) for tid, r in laatste_per_test(db, master_id).items()),
        key=lambda r: r.test.naam,
    )

    behaald_ids = {v.stap_id for v in db.voortgang(master_id) if v.behaald}
    standen = []
    for lijn in db.leerlijnen():
        stap_ids = {s.id for s in lijn.stappen}
        aantal = len(stap_ids & behaald_ids)
        if aantal:  # alleen leerlijnen waar de atleet aan begonnen is
            standen.append(LeerlijnStand(lijn, aantal, lijn.volgende_stap(behaald_ids)))

    return AtleetProfiel(
        atleet=atleet,
        leeftijd=atleet.leeftijd_op(vandaag),
        prs=prs,
        recente_prestaties=db.prestaties(master_id)[:aantal_recent],
        geplande_wedstrijden=gepland,
        testen=testregels,
        leerlijnen=standen,
        groepen=db.groepen_van_atleet(master_id),
    )
