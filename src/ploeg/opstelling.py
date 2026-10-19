"""Maakt een ploegopstelling uit atleten + regels + strategie.

Nu: de opstelling die de trainer met de hand maakt.

- `kandidaten()`: welke atleten in aanmerking komen voor een ploeg (actief en
  van een toegestane categorie op de wedstrijddag), plus wie er al in staat.
- `stand()`: punten per onderdeel en het totaal. Per onderdeel tellen de beste
  `tellend` atleten (regelbestand: bij U14/U16 twee bij lopen, één bij
  technisch). Een estafette met precies één ploeg lopers krijgt de punten van
  de geschatte tijd (ploeg/estafettes.py).
- `controleer()`: de competitieregels (ploeg/regels.py), één ploeg per dag
  met de andere ploegen op dezelfde dag, en waarschuwingen voor wie op een
  onderdeel staat zonder prestatie (0 punten) of met een voorspelling, en met
  een tijdschema (ploeg/tijdschema.py) voor botsingen en onderdelen buiten het
  dagdeel van de atleet.
- `lees_formulier()`: de opstelling uit het formulier van de ploegpagina.

Opslaan gaat via `Opslag.ploeg_opstelling_opslaan()`. De optimalisatie
(strategieën) komt in ploeg/optimaliseer.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from db.queries import Opslag
from models import Atleet, Inzet, Ploeg, PloegLid
from models.ploeg import BESCHIKBAAR
from ploeg import estafettes as _estafettes
from ploeg import regels as _regels
from ploeg.estafettes import Schatting
from ploeg.regels import Overtreding, Programmaregel, Regelset
from ploeg.tijdschema import Schema, dagdeel_tekst
from ploeg.vergelijk import Matrix, categorie_op


# ============================================================
# Atleten die in aanmerking komen
# ============================================================
def kandidaten(db: Opslag, regelset: Regelset, ploeg: Ploeg, leden: Iterable[PloegLid] = ()) -> list[Atleet]:
    """Actieve atleten die op de wedstrijddag in deze ploeg mogen, plus de huidige leden
    (ook als die niet (meer) mogen: dan ziet de trainer de overtreding). Op naam gesorteerd."""
    lid_ids = {lid.atleet_id for lid in leden}
    uit = []
    for a in db.atleten(alleen_actief=False):
        if a.master_id in lid_ids or (a.actief and regelset.mag_meedoen(ploeg.categorie,
                                                                        categorie_op(a, ploeg.datum, regelset))):
            uit.append(a)
    return uit


# ============================================================
# Punten
# ============================================================
@dataclass(slots=True)
class OnderdeelStand:
    regel: Programmaregel
    ingezet: list[str] = field(default_factory=list)      # master_ids op dit onderdeel
    tellend: list[str] = field(default_factory=list)      # wie meetelt (beste eerst)
    punten: int = 0
    schatting: Schatting | None = None                    # estafette: geschatte tijd en punten

    @property
    def vol(self) -> bool:
        if self.regel.soort == "estafette":
            return len(self.ingezet) >= self.regel.max_atleten * (self.regel.onderdeel.lopers or 4)
        return len(self.ingezet) >= self.regel.max_atleten


@dataclass(slots=True)
class Stand:
    onderdelen: dict[str, OnderdeelStand]
    totaal: int
    per_atleet: dict[str, int]                              # aantal onderdelen per atleet (estafette telt mee)
    estafettes_zonder_punten: bool = False                  # een estafette met lopers maar zonder schatting

    def punten(self, onderdeel: str) -> int:
        s = self.onderdelen.get(onderdeel)
        return s.punten if s else 0


def stand(matrix: Matrix, inzet: Iterable[Inzet]) -> Stand:
    """Punten van een opstelling volgens de matrix (beste `tellend` atleten per onderdeel)."""
    per: dict[str, OnderdeelStand] = {r.sleutel: OnderdeelStand(r) for r in matrix.regels}
    per_atleet: dict[str, int] = {}
    for i in inzet:
        s = per.get(i.onderdeel)
        if s is None or i.atleet_id in s.ingezet:
            continue
        s.ingezet.append(i.atleet_id)
        per_atleet[i.atleet_id] = per_atleet.get(i.atleet_id, 0) + 1
    estafette = False
    for s in per.values():
        if s.regel.soort == "estafette":
            s.schatting = _estafettes.schat(matrix, s.regel.sleutel, s.ingezet) if s.ingezet else None
            if s.schatting is not None:
                s.tellend, s.punten = list(s.schatting.lopers), s.schatting.punten
            elif s.ingezet:
                estafette = True
            continue
        met_punten = sorted((m for m in s.ingezet if matrix.punten(m, s.regel.sleutel) > 0),
                            key=lambda m: -matrix.punten(m, s.regel.sleutel))
        s.tellend = met_punten[:s.regel.tellend]
        s.punten = sum(matrix.punten(m, s.regel.sleutel) for m in s.tellend)
    return Stand(per, sum(s.punten for s in per.values()), per_atleet, estafette)


# ============================================================
# Controleren
# ============================================================
def controleer(db: Opslag, regelset: Regelset, ploeg: Ploeg, leden: Iterable[PloegLid], inzet: Iterable[Inzet],
               matrix: Matrix, schema: Schema | None = None) -> list[Overtreding]:
    """Regels van de competitie + één ploeg per dag + waarschuwing 'geen prestatie'."""
    leden, inzet = list(leden), list(inzet)
    uit = regelset.controleer(ploeg.categorie, ploeg.programma, leden, inzet, matrix.categorieen)

    dag: dict[str, list[PloegLid]] = {ploeg.naam: leden}
    for p in db.ploegen(ploeg.datum):
        if p.id != ploeg.id:
            naam = p.naam if p.naam not in dag else f"{p.naam} ({len(dag) + 1})"
            dag[naam] = db.ploeg_leden(p.id)
    if len(dag) > 1:
        uit += _regels.controleer_dag(dag)

    soorten = {r.sleutel: r for r in matrix.regels}
    for i in inzet:
        r = soorten.get(i.onderdeel)
        if r is None or r.soort == "estafette":
            continue
        c = matrix.cel(i.atleet_id, i.onderdeel)
        if matrix.punten(i.atleet_id, i.onderdeel) == 0:
            uit.append(Overtreding("geen_prestatie",
                                   f"Geen prestatie op {r.naam} (dit seizoen): telt voor 0 punten.",
                                   "waarschuwing", i.atleet_id, i.onderdeel))
        elif c is not None and c.voorspeld:
            uit.append(Overtreding("voorspeld", f"Geen prestatie op {r.naam}: de punten zijn een schatting "
                                                f"({c.bron}).", "waarschuwing", i.atleet_id, i.onderdeel))
    if schema is not None:
        uit += _tijdschema_controle(schema, soorten, leden, inzet)
    return uit


def _tijdschema_controle(schema: Schema, soorten: Mapping[str, Programmaregel], leden: list[PloegLid],
                         inzet: list[Inzet]) -> list[Overtreding]:
    """Botsingen en onderdelen buiten het dagdeel (waarschuwingen: het tijdschema kan nog schuiven)."""
    uit = []
    beschikbaar = {lid.atleet_id: lid.beschikbaar for lid in leden}
    per_atleet: dict[str, list[str]] = {}
    for i in inzet:
        if i.onderdeel in soorten:
            per_atleet.setdefault(i.atleet_id, []).append(i.onderdeel)
    for a, onderdelen in per_atleet.items():
        for e1, e2 in schema.botsingen(a, onderdelen):
            t1, t2 = schema.van(a, e1)[0], schema.van(a, e2)[0]
            uit.append(Overtreding("botsing", f"{soorten[e1].naam} ({t1.starttijd}) en {soorten[e2].naam} "
                                              f"({t2.starttijd}) zijn tegelijk.", "waarschuwing", a, e2))
        b = beschikbaar.get(a, "hele_dag")
        for e in onderdelen:
            if not schema.past_dagdeel(a, e, b):
                t = schema.van(a, e)[0]
                uit.append(Overtreding("dagdeel", f"{soorten[e].naam} begint om {t.starttijd}, maar deze atleet "
                                                  f"is er {dagdeel_tekst(b)}.", "waarschuwing", a, e))
    return uit


# ============================================================
# Formulier van de ploegpagina
# ============================================================
def lees_formulier(form: Mapping, kandidaat_ids: Iterable[str], onderdelen: Iterable[str]
                   ) -> tuple[list[PloegLid], list[Inzet]]:
    """Leden en inzet uit het formulier.

    Velden: `rol-<master_id>` = '' (niet in de ploeg), 'deelnemer' of 'reserve';
    `beschikbaar-<master_id>` = 'hele_dag' (standaard), 'ochtend' of 'middag';
    `inzet` (meer keer) = '<master_id>|<onderdeel>'. Wie een onderdeel heeft maar
    geen rol, wordt deelnemer. Onbekende atleten of onderdelen worden genegeerd.
    """
    kandidaat_ids = list(kandidaat_ids)
    bekend, onderdelen = set(kandidaat_ids), set(onderdelen)
    getlist = form.getlist if hasattr(form, "getlist") else (lambda k: form.get(k, []))
    inzet: list[Inzet] = []
    gezien = set()
    for waarde in getlist("inzet"):
        mid, _, ond = str(waarde).partition("|")
        if mid in bekend and ond in onderdelen and (mid, ond) not in gezien:
            gezien.add((mid, ond))
            inzet.append(Inzet(mid, ond))
    met_inzet = {i.atleet_id for i in inzet}
    leden = []
    for mid in kandidaat_ids:                      # volgorde van de kandidaten (op naam)
        rol = form.get(f"rol-{mid}", "") or ""
        if rol not in ("deelnemer", "reserve"):
            rol = "deelnemer" if mid in met_inzet else ""
        if rol:
            beschikbaar = form.get(f"beschikbaar-{mid}", "") or "hele_dag"
            leden.append(PloegLid(mid, rol, beschikbaar if beschikbaar in BESCHIKBAAR else "hele_dag"))
    return leden, inzet
