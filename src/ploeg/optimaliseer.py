"""Opstelling optimaliseren: een (geheeltallig) lineair programma met scipy.optimize.milp.

Variabelen (allemaal 0 of 1):
    x[a, e]  atleet a doet onderdeel e
    s[a, e]  atleet a is een van de tellende atleten op e (s <= x)
    plus wat een strategie zelf nodig heeft (bijv. z[a]: atleet a doet mee).

Eisen uit het regelbestand:
    per onderdeel:  som_a x[a, e] <= max_atleten,   som_a s[a, e] <= tellend
    per atleet:     som_e x[a, e] + estafettes[a] <= max_onderdelen_per_atleet (4.1)
    alleen cellen waar de atleet het onderdeel mag doen (geslacht, 'alleen') en
    vastgezette vinkjes blijven staan (x = 1).

Het doel komt van de strategie (ploeg/strategieen/): één of meer doelen na elkaar
(lexicografisch): eerst het eerste zo groot mogelijk, dan met dat resultaat vast
het volgende. Zo kan 'iedereen doet mee' eerst het aantal atleten maximaliseren
en daarna pas de punten.

Estafettes doen niet mee in de optimalisatie (nog geen punten per loper): wie de
trainer al op een estafette zette, blijft daar staan en dat telt mee voor de 3
onderdelen. Botsingen in het tijdschema en beschikbaarheid per dagdeel komen
later (stap 7).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from models import Inzet, PloegLid
from ploeg.regels import Programmaregel, Regelset
from ploeg.vergelijk import Matrix


class OptimalisatieFout(RuntimeError):
    """Geen oplossing (tegenstrijdige vaste keuzes) of scipy ontbreekt."""


@dataclass
class Model:
    """Het lineaire programma; strategieën voegen variabelen, eisen en doelen toe."""

    matrix: Matrix
    regelset: Regelset
    atleten: list[str]                                   # master_ids die mogen worden ingezet
    vast: set[tuple[str, str]]                           # (atleet, onderdeel) dat moet blijven
    estafettes: dict[str, int]                           # atleet -> aantal vaste estafettes
    regels: list[Programmaregel] = field(init=False)
    x: dict[tuple[str, str], int] = field(init=False, default_factory=dict)
    s: dict[tuple[str, str], int] = field(init=False, default_factory=dict)
    punten: dict[tuple[str, str], int] = field(init=False, default_factory=dict)
    _lb: list[float] = field(init=False, default_factory=list)
    _ub: list[float] = field(init=False, default_factory=list)
    _eisen: list[tuple[dict[int, float], float, float]] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.regels = [r for r in self.matrix.regels if r.soort != "estafette"]
        for a in self.atleten:
            for r in self.regels:
                c = self.matrix.cel(a, r.sleutel)
                if c is None or c.nvt:
                    continue
                k = (a, r.sleutel)
                self.x[k] = self.variabele(lb=1 if k in self.vast else 0)
                self.s[k] = self.variabele()
                self.punten[k] = c.punten or 0
                self.eis({self.s[k]: 1, self.x[k]: -1}, -math.inf, 0)          # s <= x
        for r in self.regels:
            xs = {v: 1 for (a, e), v in self.x.items() if e == r.sleutel}
            ss = {v: 1 for (a, e), v in self.s.items() if e == r.sleutel}
            if xs:
                self.eis(xs, -math.inf, r.max_atleten)
                self.eis(ss, -math.inf, r.tellend)
        for a in self.atleten:
            ruimte = self.regelset.max_onderdelen_per_atleet - self.estafettes.get(a, 0)
            eigen = self.van_atleet(a)
            if eigen:
                self.eis({v: 1 for v in eigen}, -math.inf, ruimte)

    # ---------------- bouwstenen voor strategieën ----------------
    def variabele(self, lb: float = 0, ub: float = 1) -> int:
        self._lb.append(lb)
        self._ub.append(ub)
        return len(self._lb) - 1

    def eis(self, coef: dict[int, float], lb: float, ub: float) -> None:
        self._eisen.append((coef, lb, ub))

    def van_atleet(self, a: str) -> list[int]:
        return [v for (b, _), v in self.x.items() if b == a]

    def puntendoel(self) -> dict[int, float]:
        return {self.s[k]: p for k, p in self.punten.items() if p}

    # ---------------- oplossen ----------------
    def oplossen(self, doelen: list[dict[int, float]], tijdslimiet: float = 30) -> np.ndarray:
        """Maximaliseer de doelen na elkaar. Geeft de waarden van alle variabelen."""
        try:
            from scipy.optimize import Bounds, LinearConstraint, milp
        except ImportError:
            raise OptimalisatieFout("Voor optimaliseren is het pakket scipy nodig (pip install scipy).") from None
        n = len(self._lb)
        if n == 0:
            return np.zeros(0)
        eisen = list(self._eisen)
        uitkomst = None
        for doel in doelen:
            c = np.zeros(n)
            for i, w in doel.items():
                c[i] = -w                                   # milp minimaliseert
            A = np.zeros((len(eisen), n))
            lb, ub = np.empty(len(eisen)), np.empty(len(eisen))
            for r, (coef, lo, hi) in enumerate(eisen):
                for i, w in coef.items():
                    A[r, i] = w
                lb[r], ub[r] = lo, hi
            res = milp(c, integrality=np.ones(n), bounds=Bounds(self._lb, self._ub),
                       constraints=[LinearConstraint(A, lb, ub)] if len(eisen) else None,
                       options={"time_limit": tijdslimiet})
            if res.x is None:
                raise OptimalisatieFout("Er is geen opstelling die aan de regels en de vaste keuzes voldoet.")
            uitkomst = np.round(res.x)
            beste = float(sum(w * uitkomst[i] for i, w in doel.items()))
            eisen.append((doel, beste - 1e-6, math.inf))   # dit doel vasthouden voor het volgende
        return uitkomst if uitkomst is not None else np.zeros(n)


@dataclass(slots=True)
class Resultaat:
    leden: list[PloegLid]
    inzet: list[Inzet]
    strategie: str


def optimaliseer(matrix: Matrix, regelset: Regelset, strategie, atleten: Iterable[str],
                 leden: Iterable[PloegLid], inzet: Iterable[Inzet], vastzetten: bool) -> Resultaat:
    """Nieuwe opstelling volgens een strategie.

    atleten:     wie mag worden ingezet (bijv. de aangevinkte deelnemers, of iedereen die mag)
    leden/inzet: de huidige opstelling; reserves blijven reserve, estafettes blijven staan,
                 en met `vastzetten` blijven ook alle huidige vinkjes staan.
    """
    leden, inzet = list(leden), list(inzet)
    rol = {lid.atleet_id: lid.rol for lid in leden}
    lid_van = {lid.atleet_id: lid for lid in leden}
    estafette_regels = {r.sleutel for r in matrix.regels if r.soort == "estafette"}
    atleten = [a for a in dict.fromkeys(atleten) if rol.get(a) != "reserve"]
    vaste_estafette = [i for i in inzet if i.onderdeel in estafette_regels and i.atleet_id in rol]
    estafettes: dict[str, int] = {}
    for i in vaste_estafette:
        estafettes[i.atleet_id] = estafettes.get(i.atleet_id, 0) + 1
    vast = {(i.atleet_id, i.onderdeel) for i in inzet
            if i.onderdeel not in estafette_regels and (vastzetten or i.vast) and i.atleet_id in atleten}

    model = Model(matrix, regelset, atleten, vast, estafettes)
    doelen = strategie.bouw(model)
    waarden = model.oplossen(doelen)

    nieuw = [Inzet(a, e, vast=(a, e) in vast) for (a, e), v in model.x.items() if waarden[v] > 0.5]
    nieuw += [Inzet(i.atleet_id, i.onderdeel, i.groep, i.vast) for i in vaste_estafette]
    met_onderdeel = {i.atleet_id for i in nieuw}
    nieuwe_leden = []
    for a in dict.fromkeys([*rol, *met_onderdeel]):
        oud = lid_van.get(a)
        beschikbaar = oud.beschikbaar if oud else "hele_dag"
        if a in met_onderdeel:
            nieuwe_leden.append(PloegLid(a, "deelnemer", beschikbaar))
        elif oud is not None:
            nieuwe_leden.append(oud)                     # reserve, of aangevinkt maar niet ingezet
    return Resultaat(nieuwe_leden, nieuw, strategie.naam)
