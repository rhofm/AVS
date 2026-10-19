"""Estafettes: de tijd en punten van een kwartet schatten, en kwartetten voorstellen.

Een estafette heeft geen prestatie per atleet. Het regelbestand geeft per
estafette de `benen` (welk onderdeel elke loper loopt, bijv. [80m, 80m, 80m,
80m] of bij de Zweedse [400m, 300m, 200m, 100m]) en een `correctie_s` voor de
wissels (vliegende start: meestal negatief). Dan:

    tijd = beste verdeling van de lopers over de benen (som van hun beentijden)
           + correctie_s

De beentijden komen uit de matrix (eigen prestatie, anders voorspeld; zie
ploeg/voorspeller.py). De punten volgen uit de puntentelling van de estafette.
Bij een gemengde estafette ({M: 2, V: 2}) telt alleen een kwartet met de juiste
samenstelling; een been met `geslacht` in het regelbestand neemt alleen lopers
van dat geslacht.

`opties()` rekent voor de optimalisatie de beste kwartetten voor: uit de
snelsten per been (samen hoogstens POOL atleten) alle combinaties. Bij een
4x80m zijn dat de 10 snelsten: 210 kwartetten.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterable

from atleten.prestaties import toon_waarde
from ploeg import punten as _punten
from ploeg.vergelijk import Matrix

POOL = 10                       # zoveel atleten (de snelsten per been) gaan mee in de kwartetten


@dataclass(frozen=True, slots=True)
class Schatting:
    sleutel: str                # programmasleutel van de estafette
    lopers: tuple[str, ...]     # master_ids in de volgorde van de benen
    tijd: float
    punten: int
    voorspeld: bool             # minstens één beentijd is voorspeld

    @property
    def tekst(self) -> str:
        return ("≈" if self.voorspeld else "") + toon_waarde(self.tijd, "tijd")


def _geslacht(categorie: str | None) -> str | None:
    if not categorie:
        return None
    return categorie[-1] if "-" in categorie else categorie[0]


def schat(matrix: Matrix, sleutel: str, atleten: Iterable[str]) -> Schatting | None:
    """Schatting voor precies deze lopers, of None (verkeerd aantal, samenstelling klopt niet,
    of een loper heeft geen tijd op een been)."""
    regel = matrix.regel(sleutel)
    if regel is None or regel.soort != "estafette":
        return None
    info = regel.onderdeel
    atleten = list(dict.fromkeys(atleten))
    if not info.benen or len(atleten) != len(info.benen):
        return None
    if info.samenstelling:
        per = {g: 0 for g in ("M", "V")}
        for a in atleten:
            g = _geslacht(matrix.categorieen.get(a))
            if g in per:
                per[g] += 1
        if any(per.get(g, 0) != n for g, n in info.samenstelling.items()):
            return None
    beste: tuple[float, tuple[str, ...], bool] | None = None
    for volgorde in itertools.permutations(atleten):
        totaal, voorspeld = 0.0, False
        for a, been in zip(volgorde, info.benen):
            t = matrix.beentijden.get(a, {}).get(been)
            if t is None:
                break
            totaal += t.tijd
            voorspeld = voorspeld or t.voorspeld
        else:
            if beste is None or totaal < beste[0] - 1e-9:
                beste = (totaal, volgorde, voorspeld)
    if beste is None:
        return None
    rs = matrix.regelset
    tijd = round(beste[0] + info.correctie_s, 2)
    g = rs.punten_geslacht(matrix.ploeg, sleutel)
    pt = _punten.puntentelling(rs.puntentelling)
    return Schatting(sleutel, beste[1], tijd, pt.punten(rs.puntentabel, info.punten_sleutel, g, tijd), beste[2])


def opties(matrix: Matrix, sleutel: str, atleten: Iterable[str]) -> list[Schatting]:
    """Mogelijke kwartetten uit deze atleten, beste eerst (alleen die met punten)."""
    regel = matrix.regel(sleutel)
    if regel is None or regel.soort != "estafette" or not regel.onderdeel.benen:
        return []
    benen = regel.onderdeel.benen
    mag = []
    for a in dict.fromkeys(atleten):
        c = matrix.cel(a, sleutel)
        if c is not None and not c.nvt and matrix.beentijden.get(a):
            mag.append(a)
    # de snelsten per been, om de beurt, tot POOL atleten
    ranglijsten = []
    for been in dict.fromkeys(benen):
        met_tijd = [a for a in mag if been in matrix.beentijden[a]]
        ranglijsten.append(sorted(met_tijd, key=lambda a: matrix.beentijden[a][been].tijd))
    pool: list[str] = []
    for rang in itertools.zip_longest(*ranglijsten):
        for a in rang:
            if a is not None and a not in pool and len(pool) < POOL:
                pool.append(a)
    uit = []
    for kwartet in itertools.combinations(pool, len(benen)):
        s = schat(matrix, sleutel, kwartet)
        if s is not None and s.punten > 0:
            uit.append(s)
    uit.sort(key=lambda s: (-s.punten, s.tijd))
    return uit
