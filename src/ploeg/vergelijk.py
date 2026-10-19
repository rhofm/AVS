"""Vergelijken van PRs/prestaties binnen een groep atleten: de matrix atleten x onderdelen.

Voor één ploeg (regelset + categorie + programma) en een wedstrijddag geeft
`matrix()` per atleet en per onderdeel van het programma de beste prestatie en
de punten die daarbij horen. Daarmee maakt de trainer een opstelling (met de
hand of later met een strategie).

- Welke prestatie telt: `prestatiebasis` 'seizoen' (huidig + vorig
  kalenderjaar, zoals de serie-indeling in bepaling 17.5), 'pr' of '12mnd'.
  Altijd alleen prestaties tot en met de wedstrijddag, en windlegaal (zoals
  de PR's; indoor telt altijd).
- Welk onderdeel: de naam + specificatie uit het regelbestand
  (`Regelset.onderdeel_naam`), bijv. 'Kogelstoten 3kg' in de U16-ploeg, ook
  voor een U14-atleet. Een handtijd op dat onderdeel ('100 meter Handtijd')
  telt mee, met de handtijdcorrectie (zonder windmeting toegestaan).
- Geen prestatie op het juiste onderdeel maar wel op dezelfde soort met een
  andere specificatie (een U14 met de 2 kg-kogel)? Dan staat die als `hint` in
  de cel, zonder punten. Voorspellen komt later (ploeg/voorspeller.py).
- Estafettes hebben geen prestatie per atleet: die cellen blijven leeg.

Alleen lezen; er wordt niets opgeslagen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from atleten.landingspagina import leeftijdscategorie
from atleten.prestaties import toon_waarde
from db.queries import Opslag
from models import PRESTATIEBASIS, Atleet, Onderdeel, Prestatie
from ploeg import punten as _punten
from ploeg.regels import Programmaregel, Regelset, categorie_code

_SPEC = re.compile(r"^[\d.]+(kg|g|cm)$")          # rest na de naam: '3kg', '76.2cm', '600g'


def normaliseer(naam: str) -> str:
    """Naam van een onderdeel om te vergelijken: kleine letters, zonder spaties,
    komma als punt en zonder nullen achter de komma ('76,20 cm' -> '76.2cm')."""
    n = re.sub(r"\s+", "", naam.lower()).replace(",", ".")
    n = re.sub(r"(\d+\.\d*?)0+(?=\D|$)", r"\1", n)
    return re.sub(r"(\d+)\.(?=\D|$)", r"\1", n)


@dataclass(slots=True)
class Cel:
    """Eén atleet op één onderdeel van het programma."""

    onderdeel: str                       # programmasleutel, bijv. 'kogelstoten'
    onderdeel_naam: str                  # naam + specificatie bij de prestaties, bijv. 'Kogelstoten 3kg'
    waarde: float | None = None          # beste prestatie (s of m), None = geen
    datum: date | None = None
    punten: int | None = None
    handtijd: bool = False
    eenheid: str = "tijd"
    hint: str | None = None              # prestatie met een andere specificatie, zonder punten

    @property
    def tekst(self) -> str:
        if self.waarde is None:
            return ""
        t = toon_waarde(self.waarde, self.eenheid)
        return f"{t} (hand)" if self.handtijd else t


@dataclass(slots=True)
class Rij:
    atleet: Atleet
    categorie: str | None                # 'U14-V' op de wedstrijddag; None = onbekend
    toegestaan: bool
    cellen: dict[str, Cel] = field(default_factory=dict)

    @property
    def master_id(self) -> str:
        return self.atleet.master_id


@dataclass(slots=True)
class Matrix:
    regelset: Regelset
    ploeg: str                           # categorie van de ploeg, bijv. 'U16-V'
    programma: str
    peildatum: date
    prestatiebasis: str
    regels: list[Programmaregel]
    rijen: list[Rij]

    def rij(self, master_id: str) -> Rij | None:
        return next((r for r in self.rijen if r.master_id == master_id), None)

    def cel(self, master_id: str, onderdeel: str) -> Cel | None:
        r = self.rij(master_id)
        return r.cellen.get(onderdeel) if r else None

    def punten(self, master_id: str, onderdeel: str) -> int:
        c = self.cel(master_id, onderdeel)
        return c.punten or 0 if c else 0

    @property
    def categorieen(self) -> dict[str, str | None]:
        return {r.master_id: r.categorie for r in self.rijen}


def categorie_op(atleet: Atleet, peildatum: date) -> str | None:
    """Categoriecode op de wedstrijddag, bijv. 'U16-V'. None zonder geboortedatum of geslacht."""
    return categorie_code(leeftijdscategorie(atleet, peildatum), atleet.geslacht)


def in_periode(d: date, peildatum: date, basis: str) -> bool:
    """Telt een prestatie van datum d mee voor deze prestatiebasis?"""
    if d > peildatum:
        return False
    if basis == "seizoen":
        return d.year >= peildatum.year - 1
    if basis == "12mnd":
        return d > peildatum - timedelta(days=365)
    return True                                    # 'pr'


def matrix(db: Opslag, regelset: Regelset, ploeg: str, programma: str, peildatum: date,
           atleten: Iterable[Atleet], prestatiebasis: str = "seizoen") -> Matrix:
    """De matrix voor deze atleten (in deze volgorde)."""
    if prestatiebasis not in PRESTATIEBASIS:
        raise ValueError(f"Onbekende prestatiebasis {prestatiebasis!r}.")
    regels = regelset.programma(ploeg, programma)
    geslacht = regelset.ploeg(ploeg).geslacht
    pt = _punten.puntentelling(regelset.puntentelling)
    onderdelen: dict[int, Onderdeel] = {o.id: o for o in db.onderdelen()}

    rijen = []
    for a in atleten:
        cat = categorie_op(a, peildatum)
        rij = Rij(a, cat, regelset.mag_meedoen(ploeg, cat))
        per_naam: dict[str, list[Prestatie]] = {}
        for p in db.prestaties(a.master_id):
            o = onderdelen.get(p.onderdeel_id)
            if o is None or not in_periode(p.datum, peildatum, prestatiebasis):
                continue
            n = normaliseer(o.naam)
            # Handtijden hebben meestal geen windmeting: alleen een gemeten wind moet kloppen.
            hand_zonder_wind = n.endswith("handtijd") and p.wind is None
            if not (hand_zonder_wind or o.windlegaal(p.wind, p.indoor)):
                continue
            per_naam.setdefault(n, []).append(p)

        for r in regels:
            naam = regelset.onderdeel_naam(ploeg, r.sleutel, cat or ploeg)
            cel = Cel(r.sleutel, naam, eenheid="tijd" if r.soort != "technisch" else "afstand")
            rij.cellen[r.sleutel] = cel
            if r.soort == "estafette":
                continue
            beste = _beste(per_naam, naam, r.sleutel, r.soort != "technisch")
            if beste is not None:
                p, handtijd = beste
                cel.waarde, cel.datum, cel.handtijd = p.waarde, p.datum, handtijd
                cel.eenheid = onderdelen[p.onderdeel_id].eenheid
                cel.punten = pt.punten(regelset.puntentabel, r.sleutel, geslacht, p.waarde, handtijd=handtijd)
            else:
                cel.hint = _hint(per_naam, regelset.onderdelen[r.sleutel].naam, naam, onderdelen,
                                 r.soort != "technisch")
        rijen.append(rij)
    return Matrix(regelset, ploeg, programma, peildatum, prestatiebasis, regels, rijen)


def _beste(per_naam: dict[str, list[Prestatie]], naam: str, sleutel: str,
           lager_is_beter: bool) -> tuple[Prestatie, bool] | None:
    """Beste prestatie op dit onderdeel; een handtijd telt met correctie (en verliest bij gelijke waarde)."""
    n = normaliseer(naam)
    kandidaten = [(p, False) for p in per_naam.get(n, [])]
    kandidaten += [(p, True) for p in per_naam.get(n + "handtijd", [])]
    if not kandidaten:
        return None

    def effectief(k):
        p, hand = k
        if not hand or not lager_is_beter:
            return p.waarde
        return p.waarde + _punten.handtijd_correctie(sleutel) + 1e-6     # bij gelijk: elektronisch wint

    return min(kandidaten, key=effectief) if lager_is_beter else max(kandidaten, key=effectief)


def _hint(per_naam: dict[str, list[Prestatie]], basisnaam: str, naam: str, onderdelen: dict[int, Onderdeel],
          lager_is_beter: bool) -> str | None:
    """Beste prestatie op hetzelfde onderdeel met een andere specificatie, als tekst."""
    basis, eigen = normaliseer(basisnaam), normaliseer(naam)
    beste: Prestatie | None = None
    for n, lijst in per_naam.items():
        if n == eigen or not n.startswith(basis) or not _SPEC.match(n[len(basis):]):
            continue
        for p in lijst:
            if beste is None or (p.waarde < beste.waarde if lager_is_beter else p.waarde > beste.waarde):
                beste = p
    if beste is None:
        return None
    o = onderdelen[beste.onderdeel_id]
    spec = o.naam[len(basisnaam):].strip() if o.naam.lower().startswith(basisnaam.lower()) else o.naam
    return f"{spec}: {toon_waarde(beste.waarde, o.eenheid)}"
