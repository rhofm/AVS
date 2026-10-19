"""Voorspeller: een prestatie schatten als een atleet het onderdeel (zo) nog niet deed.

Twee bronnen, allebei ingesteld in het regelbestand (config/ploeg_regels/):

- **Buuronderdeel** (`buren` bij een onderdeel): de beste prestatie op een
  verwant onderdeel geeft punten (80 m: 10,85 -> 760 punten); de voorspelling
  op het doelonderdeel is de zwakste prestatie die evenveel punten geeft,
  maal `voorspelling_factor` (algemeen, standaard 0.95: liever iets te
  voorzichtig).
- **Andere specificatie** (`verhouding` bij een onderdeel): een prestatie met
  ander werpmateriaal of een andere hordehoogte wordt omgerekend met
  prestatie x verhouding[doel] / verhouding[bron]. Bij kogelstoten
  {2kg: 1.0, 3kg: 0.87}: 9,00 m met 2 kg -> 7,83 m met 3 kg. Daarna ook de
  `voorspelling_factor` op de punten.

Van alle bronnen telt de voorspelling met de meeste punten. Een voorspelling
is altijd zichtbaar gemarkeerd in de matrix; de bron staat erbij.

`beentijd()` geeft de tijd van één estafettebeen (eigen prestatie, anders een
voorspelling); ploeg/estafettes.py telt de benen op.

De zoekfuncties (`beste`, `specificaties`) komen uit ploeg/vergelijk.py, zodat
dezelfde regels gelden (prestatiebasis, wind, handtijden).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from atleten.prestaties import toon_waarde
from ploeg import punten as _punten
from ploeg.regels import Regelset

# beste(naam, puntensleutel, lager_is_beter) -> (waarde, handtijd, eenheid) of None
Beste = Callable[[str, str, bool], "tuple[float, bool, str] | None"]
# specificaties(basisnaam, lager_is_beter) -> [(spec genormaliseerd, spec als tekst, waarde, eenheid)]
Specificaties = Callable[[str, bool], "list[tuple[str, str, float, str]]"]


@dataclass(frozen=True, slots=True)
class Voorspelling:
    waarde: float
    punten: int
    bron: str                     # 'voorspeld uit 80 meter: 10,85'


@dataclass(frozen=True, slots=True)
class Beentijd:
    tijd: float                   # seconden, handtijd al gecorrigeerd
    voorspeld: bool = False


def _norm(spec: str) -> str:
    from ploeg.vergelijk import normaliseer          # hier: vergelijk importeert deze module
    return normaliseer(spec)


def voorspel(regelset: Regelset, ploeg: str, sleutel: str, categorie: str | None,
             beste: Beste, specificaties: Specificaties) -> Voorspelling | None:
    """Voorspelling voor één atleet op één onderdeel, of None (niets om uit te voorspellen)."""
    factor = regelset.voorspelling_factor
    info = regelset.onderdelen.get(sleutel)
    if not factor or info is None or info.is_estafette:
        return None
    pt = _punten.puntentelling(regelset.puntentelling)
    tabel, g = regelset.puntentabel, regelset.punten_geslacht(ploeg, sleutel)
    if not pt.heeft(tabel, info.punten_sleutel, g):
        return None
    doel = pt.formule(tabel, info.punten_sleutel, g)
    cat = categorie or ploeg
    kandidaten: list[tuple[int, str]] = []

    # 1. zelfde onderdeel, ander materiaal / andere hordehoogte
    if info.verhouding:
        verh = {_norm(k): v for k, v in info.verhouding.items()}
        doelspec = info.specificatie(regelset.materiaal_categorie(ploeg, cat))
        d = _norm(doelspec) if doelspec else None
        if d in verh:
            for spec, tekst, waarde, eenheid in specificaties(info.naam, doel.lager_is_beter):
                if spec != d and spec in verh:
                    omgerekend = waarde * verh[d] / verh[spec]
                    kandidaten.append((doel.punten(omgerekend), f"{info.naam} {tekst}: {toon_waarde(waarde, eenheid)}"))

    # 2. buuronderdelen, via de punten
    for b in info.buren:
        bi = regelset.onderdelen[b]
        gb = regelset.punten_geslacht(ploeg, b)
        if not bi.past_bij(categorie, regelset.materiaal_categorie(ploeg, cat)) or \
                not pt.heeft(tabel, bi.punten_sleutel, gb):
            continue
        f = pt.formule(tabel, bi.punten_sleutel, gb)
        naam = regelset.onderdeel_naam(ploeg, b, cat)
        r = beste(naam, bi.punten_sleutel, f.lager_is_beter)
        if r is not None:
            waarde, hand, eenheid = r
            p = pt.punten(tabel, bi.punten_sleutel, gb, waarde, handtijd=hand)
            kandidaten.append((p, f"{naam}: {toon_waarde(waarde, eenheid)}{' (hand)' if hand else ''}"))

    if not kandidaten:
        return None
    p, bron = max(kandidaten, key=lambda k: k[0])
    p = int(p * factor)
    if p < 1:
        return None
    waarde = doel.prestatie_voor(p)
    return Voorspelling(waarde, doel.punten(waarde), f"voorspeld uit {bron}")


def beentijd(regelset: Regelset, ploeg: str, been: str, categorie: str | None,
             beste: Beste, specificaties: Specificaties) -> Beentijd | None:
    """Tijd van een atleet op een estafettebeen (bijv. '80m'): eigen beste tijd, anders voorspeld."""
    info = regelset.onderdelen[been]
    cat = categorie or ploeg
    if categorie is not None and not info.past_bij(categorie, regelset.materiaal_categorie(ploeg, cat)):
        return None
    r = beste(regelset.onderdeel_naam(ploeg, been, cat), info.punten_sleutel, True)
    if r is not None:
        waarde, hand, _ = r
        return Beentijd(round(waarde + (_punten.handtijd_correctie(info.punten_sleutel) if hand else 0), 2))
    v = voorspel(regelset, ploeg, been, categorie, beste, specificaties)
    return Beentijd(v.waarde, True) if v else None
