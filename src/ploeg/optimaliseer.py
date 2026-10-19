"""Opstelling optimaliseren: een (geheeltallig) lineair programma met scipy.optimize.milp.

Variabelen (allemaal 0 of 1):
    x[a, e]  atleet a doet onderdeel e
    s[a, e]  atleet a is een van de tellende atleten op e (s <= x)
    w[e, k]  kwartet k (ploeg/estafettes.py: opties) loopt estafette e
    plus wat een strategie zelf nodig heeft (bijv. z[a]: atleet a doet mee).

Eisen uit het regelbestand:
    per onderdeel:  som_a x[a, e] <= max_atleten,   som_a s[a, e] <= tellend
    per estafette:  som_k w[e, k] <= 1
    per atleet:     som_e x[a, e] + som (w met a erin) + vaste estafettes[a]
                    <= max_onderdelen_per_atleet (4.1)
    tijdschema:     botsing e1/e2 voor atleet a: keuzes(a, e1) + keuzes(a, e2) <= 1;
                    onderdeel buiten het dagdeel van a: keuzes(a, e) = 0 (ploeg/tijdschema.py)
    voorkeuren:     'wil_niet': keuzes(a, e) = 0; 'moet': keuzes(a, e) >= 1; 'voorkeur': een
                    extra doel direct na het eerste doel van de strategie (ploeg/voorkeuren.py)
    alleen cellen waar de atleet het onderdeel mag doen (geslacht, 'alleen') en
    vastgezette vinkjes blijven staan (x = 1).

Het doel komt van de strategie (ploeg/strategieen/): één of meer doelen na elkaar
(lexicografisch): eerst het eerste zo groot mogelijk, dan met dat resultaat vast
het volgende. Zo kan 'iedereen doet mee' eerst het aantal atleten maximaliseren
en daarna pas de punten.

Estafettes: de beste kwartetten worden vooraf uitgerekend (tijd = som van de
beentijden + correctie, zie ploeg/estafettes.py) en elk kwartet is één keuze
w[e, k] met zijn punten. Een estafette blijft staan zoals de trainer hem zette
als hij is vastgezet ('huidige vinkjes laten staan' of een vaste loper), of als
er geen kwartet te schatten is (geen beentijden); dan telt hij mee voor de 3
onderdelen.

Met een tijdschema (gekoppelde wedstrijd) plant de optimalisatie geen botsingen
in en niets buiten het dagdeel van een atleet; daarna krijgen atleten op een
technisch onderdeel met meer groepen elk een eigen groep (9.1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping

import numpy as np

from models import Inzet, PloegLid
from ploeg.estafettes import Schatting
from ploeg.estafettes import opties as _opties
from ploeg.regels import Programmaregel, Regelset
from ploeg.tijdschema import Schema, groepen_indelen
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
    vrije_estafettes: tuple[str, ...] = ()               # estafettes waarvoor een kwartet wordt gekozen
    verboden: frozenset[tuple[str, str]] = frozenset()   # (atleet, onderdeel) dat niet kan (dagdeel)
    botsingen: tuple[tuple[str, str, str], ...] = ()     # (atleet, e1, e2): niet allebei
    vaste_estafettes: frozenset[tuple[str, str]] = frozenset()   # (atleet, estafette) die blijft staan
    moet: frozenset[tuple[str, str]] = frozenset()       # (atleet, onderdeel) dat erin moet ('moet')
    graag: frozenset[tuple[str, str]] = frozenset()      # (atleet, onderdeel) met 'voorkeur'
    regels: list[Programmaregel] = field(init=False)
    x: dict[tuple[str, str], int] = field(init=False, default_factory=dict)
    s: dict[tuple[str, str], int] = field(init=False, default_factory=dict)
    punten: dict[tuple[str, str], int] = field(init=False, default_factory=dict)
    w: dict[tuple[str, int], int] = field(init=False, default_factory=dict)
    kwartetten: dict[tuple[str, int], Schatting] = field(init=False, default_factory=dict)
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
                self.x[k] = self.variabele(lb=1 if k in self.vast else 0, ub=0 if k in self.verboden else 1)
                self.s[k] = self.variabele()
                self.punten[k] = c.punten or 0
                self.eis({self.s[k]: 1, self.x[k]: -1}, -math.inf, 0)          # s <= x
        for r in self.regels:
            xs = {v: 1 for (a, e), v in self.x.items() if e == r.sleutel}
            ss = {v: 1 for (a, e), v in self.s.items() if e == r.sleutel}
            if xs:
                self.eis(xs, -math.inf, r.max_atleten)
                self.eis(ss, -math.inf, r.tellend)
        for e in self.vrije_estafettes:
            ws = {}
            opties = [o for o in _opties(self.matrix, e, self.atleten)
                      if not any((a, e) in self.verboden for a in o.lopers)]
            for k, sch in enumerate(opties):
                self.w[(e, k)] = v = self.variabele()
                self.kwartetten[(e, k)] = sch
                ws[v] = 1
            if ws:
                self.eis(ws, -math.inf, 1)                                    # één estafetteploeg
        for a in self.atleten:
            ruimte = self.regelset.max_onderdelen_per_atleet - self.estafettes.get(a, 0)
            eigen = self.van_atleet(a)
            if eigen:
                self.eis({v: 1 for v in eigen}, -math.inf, ruimte)
        for a, e in self.moet:
            keuzes = self.keuzes(a, e)
            if keuzes and (a, e) not in self.vaste_estafettes:     # geen keuze (bijv. estafette zonder
                self.eis({v: 1 for v in keuzes}, 1, math.inf)      # tijden): de controle meldt het
        for a, e1, e2 in self.botsingen:
            keuzes = self.keuzes(a, e1) + self.keuzes(a, e2)
            vast = sum(1 for e in (e1, e2) if (a, e) in self.vaste_estafettes)
            if keuzes:
                self.eis({v: 1 for v in keuzes}, -math.inf, 1 - vast)

    # ---------------- bouwstenen voor strategieën ----------------
    def variabele(self, lb: float = 0, ub: float = 1) -> int:
        self._lb.append(lb)
        self._ub.append(ub)
        return len(self._lb) - 1

    def eis(self, coef: dict[int, float], lb: float, ub: float) -> None:
        self._eisen.append((coef, lb, ub))

    def van_atleet(self, a: str) -> list[int]:
        """Alle keuzes waarmee atleet a een onderdeel doet (x en de kwartetten met a erin)."""
        return [v for (b, _), v in self.x.items() if b == a] + \
               [v for k, v in self.w.items() if a in self.kwartetten[k].lopers]

    def keuzes(self, a: str, e: str) -> list[int]:
        """Variabelen waarmee atleet a onderdeel e doet (x, of de kwartetten met a erin)."""
        if (a, e) in self.x:
            return [self.x[(a, e)]]
        return [v for k, v in self.w.items() if k[0] == e and a in self.kwartetten[k].lopers]

    def voorkeurdoel(self) -> dict[int, float]:
        """Zoveel mogelijk onderdelen met 'voorkeur' (een kwartet telt per loper met voorkeur)."""
        doel: dict[int, float] = {}
        for a, e in self.graag:
            for v in self.keuzes(a, e):
                doel[v] = doel.get(v, 0) + 1
        return doel

    def puntendoel(self) -> dict[int, float]:
        doel = {self.s[k]: p for k, p in self.punten.items() if p}
        doel.update({v: self.kwartetten[k].punten for k, v in self.w.items()})
        return doel

    def inschrijvingen(self) -> dict[int, float]:
        """Aantal inschrijvingen: elke x telt 1, een kwartet telt voor zijn lopers."""
        return {**{v: 1 for v in self.x.values()},
                **{v: len(self.kwartetten[k].lopers) for k, v in self.w.items()}}

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
                raise OptimalisatieFout("Er is geen opstelling die aan de regels, de vaste keuzes en de "
                                        "'moet'-voorkeuren voldoet (te veel onderdelen, of tegelijk?).")
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
                 leden: Iterable[PloegLid], inzet: Iterable[Inzet], vastzetten: bool,
                 schema: Schema | None = None, voorkeuren: Mapping | None = None) -> Resultaat:
    """Nieuwe opstelling volgens een strategie.

    atleten:     wie mag worden ingezet (bijv. de aangevinkte deelnemers, of iedereen die mag)
    leden/inzet: de huidige opstelling; reserves blijven reserve, en met `vastzetten` blijven
                 alle huidige vinkjes staan. Een estafette blijft staan als een loper vast staat
                 of als er geen kwartet te schatten is; anders kiest de optimalisatie het kwartet.
    schema:      tijdschema van de gekoppelde wedstrijd (botsingen, dagdelen, groepen), of None.
    voorkeuren:  (atleet, onderdeel) -> voorkeur (str of iets met `.voorkeur`), zie ploeg/voorkeuren.py.
    """
    leden, inzet = list(leden), list(inzet)
    rol = {lid.atleet_id: lid.rol for lid in leden}
    lid_van = {lid.atleet_id: lid for lid in leden}
    estafette_regels = [r.sleutel for r in matrix.regels if r.soort == "estafette"]
    atleten = [a for a in dict.fromkeys(atleten) if rol.get(a) != "reserve"]
    vrij = []
    for e in estafette_regels:
        huidig = [i for i in inzet if i.onderdeel == e and i.atleet_id in rol]
        if not (vastzetten or any(i.vast for i in huidig)) and _opties(matrix, e, atleten):
            vrij.append(e)
    vaste_estafette = [i for i in inzet if i.onderdeel in estafette_regels and i.onderdeel not in vrij
                       and i.atleet_id in rol]
    estafettes: dict[str, int] = {}
    for i in vaste_estafette:
        estafettes[i.atleet_id] = estafettes.get(i.atleet_id, 0) + 1
    vast = {(i.atleet_id, i.onderdeel) for i in inzet
            if i.onderdeel not in estafette_regels and (vastzetten or i.vast) and i.atleet_id in atleten}

    verboden: set[tuple[str, str]] = set()
    botsingen: list[tuple[str, str, str]] = []
    if schema is not None:
        beschikbaar = {lid.atleet_id: lid.beschikbaar for lid in leden}
        sleutels = [r.sleutel for r in matrix.regels]
        for a in atleten:
            verboden |= {(a, e) for e in sleutels
                         if not schema.past_dagdeel(a, e, beschikbaar.get(a, "hele_dag"))}
            botsingen += [(a, e1, e2) for e1, e2 in schema.botsingen(a, sleutels)]
    moet: set[tuple[str, str]] = set()
    graag: set[tuple[str, str]] = set()
    for (a, e), v in (voorkeuren or {}).items():
        v = getattr(v, "voorkeur", v)
        c = matrix.cel(a, e)
        if a not in atleten or c is None or c.nvt:
            continue
        if v == "wil_niet" and (a, e) not in vast:
            verboden.add((a, e))
        elif v == "moet" and (a, e) not in verboden:
            moet.add((a, e))
        elif v == "voorkeur":
            graag.add((a, e))
    model = Model(matrix, regelset, atleten, vast, estafettes, tuple(vrij), frozenset(verboden),
                  tuple(botsingen), frozenset((i.atleet_id, i.onderdeel) for i in vaste_estafette),
                  frozenset(moet), frozenset(graag))
    doelen = strategie.bouw(model)
    if graag:
        doelen.insert(1, model.voorkeurdoel())
    waarden = model.oplossen(doelen)

    nieuw = [Inzet(a, e, vast=(a, e) in vast) for (a, e), v in model.x.items() if waarden[v] > 0.5]
    nieuw += [Inzet(a, e) for (e, k), v in model.w.items() if waarden[v] > 0.5
              for a in model.kwartetten[(e, k)].lopers]
    nieuw += [Inzet(i.atleet_id, i.onderdeel, i.groep, i.vast) for i in vaste_estafette]
    nieuw = groepen_indelen(schema, regelset, nieuw, {lid.atleet_id: lid.beschikbaar for lid in leden})
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
