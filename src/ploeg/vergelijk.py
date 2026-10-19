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
- Geen prestatie op het juiste onderdeel? Dan een voorspelling
  (ploeg/voorspeller.py): uit een buuronderdeel of een andere specificatie
  (een U14 met de 2 kg-kogel), gemarkeerd met `voorspeld` en de `bron`. Kan
  dat niet, maar is er wel een prestatie met een andere specificatie, dan
  staat die als `hint` in de cel, zonder punten.
- Estafettes hebben geen prestatie per atleet. De matrix bewaart per atleet
  de tijd op elk estafettebeen (`beentijden`); ploeg/estafettes.py rekent
  daarmee een kwartet uit. In de cel staat die beentijd ter informatie.

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
from ploeg.regels import Programmaregel, Regelset, categorie_code, masters_code
from ploeg.voorspeller import Beentijd, beentijd, voorspel

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
    nvt: bool = False                    # atleet mag dit onderdeel niet doen (ander geslacht, alleen U18, ...)
    voorspeld: bool = False              # waarde/punten zijn een voorspelling (geen echte prestatie)
    bron: str | None = None              # waar de voorspelling vandaan komt
    beentijd: str | None = None          # estafette: tijd(en) van de atleet op de benen, als tekst

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
    beentijden: dict[str, dict[str, Beentijd]] = field(default_factory=dict)   # atleet -> been -> tijd

    def regel(self, sleutel: str) -> Programmaregel | None:
        return next((r for r in self.regels if r.sleutel == sleutel), None)

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


def categorie_op(atleet: Atleet, peildatum: date, regelset: Regelset | None = None) -> str | None:
    """Categoriecode op de wedstrijddag: 'U16-V', 'SEN-M', of bij een masterscompetitie
    (leeftijdsklassen: masters) de klasse op leeftijd: 'V45'. None zonder geboortedatum of geslacht."""
    if regelset is not None and regelset.leeftijdsklassen == "masters":
        return masters_code(atleet.geslacht, atleet.leeftijd_op(peildatum))
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
    pt = _punten.puntentelling(regelset.puntentelling)
    onderdelen: dict[int, Onderdeel] = {o.id: o for o in db.onderdelen()}

    benen = list(dict.fromkeys(b for r in regels if r.soort == "estafette" for b in r.onderdeel.benen))

    rijen = []
    beentijden: dict[str, dict[str, Beentijd]] = {}
    for a in atleten:
        cat = categorie_op(a, peildatum, regelset)
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

        def beste(naam, sleutel, lager, per_naam=per_naam):
            b = _beste(per_naam, naam, sleutel, lager)
            return (b[0].waarde, b[1], onderdelen[b[0].onderdeel_id].eenheid) if b else None

        def specificaties(basisnaam, lager, per_naam=per_naam):
            return _specificaties(per_naam, basisnaam, onderdelen, lager)

        eigen = {b: t for b in benen
                 if (t := beentijd(regelset, ploeg, b, cat, beste, specificaties)) is not None}
        if eigen:
            beentijden[a.master_id] = eigen

        for r in regels:
            info = r.onderdeel
            naam = regelset.onderdeel_naam(ploeg, r.sleutel, cat or ploeg)
            cel = Cel(r.sleutel, naam, eenheid="tijd" if r.soort != "technisch" else "afstand")
            rij.cellen[r.sleutel] = cel
            if cat is not None and not info.past_bij(cat, regelset.materiaal_categorie(ploeg, cat)):
                cel.nvt = True
                continue
            if r.soort == "estafette":
                cel.beentijd = _beentekst(regelset, info.benen, eigen)
                continue
            gevonden = _beste(per_naam, naam, info.punten_sleutel, r.soort != "technisch")
            if gevonden is not None:
                p, handtijd = gevonden
                cel.waarde, cel.datum, cel.handtijd = p.waarde, p.datum, handtijd
                cel.eenheid = onderdelen[p.onderdeel_id].eenheid
                g = regelset.punten_geslacht(ploeg, r.sleutel)
                cel.punten = pt.punten(regelset.puntentabel, info.punten_sleutel, g, p.waarde, handtijd=handtijd)
                continue
            cel.hint = _hint(per_naam, regelset.onderdelen[r.sleutel].naam, naam, onderdelen,
                             r.soort != "technisch")
            v = voorspel(regelset, ploeg, r.sleutel, cat, beste, specificaties)
            if v is not None:
                cel.waarde, cel.punten, cel.voorspeld, cel.bron = v.waarde, v.punten, True, v.bron
        rijen.append(rij)
    return Matrix(regelset, ploeg, programma, peildatum, prestatiebasis, regels, rijen, beentijden)


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


def _specificaties(per_naam: dict[str, list[Prestatie]], basisnaam: str, onderdelen: dict[int, Onderdeel],
                   lager_is_beter: bool) -> list[tuple[str, str, float, str]]:
    """Beste prestatie per specificatie van een onderdeel: [('3kg', '3kg', 9.12, 'afstand'), ...]."""
    basis = normaliseer(basisnaam)
    uit = []
    for n, lijst in per_naam.items():
        rest = n[len(basis):]
        if not n.startswith(basis) or not _SPEC.match(rest):
            continue
        p = min(lijst, key=lambda q: q.waarde) if lager_is_beter else max(lijst, key=lambda q: q.waarde)
        o = onderdelen[p.onderdeel_id]
        tekst = o.naam[len(basisnaam):].strip() if o.naam.lower().startswith(basisnaam.lower()) else rest
        uit.append((rest, tekst, p.waarde, o.eenheid))
    return uit


def _beentekst(regelset: Regelset, benen: tuple[str, ...], tijden: dict[str, Beentijd]) -> str | None:
    """'10,85' (alle benen hetzelfde) of '400 meter: 58,10 · 200 meter: ≈26,02' (Zweedse)."""
    soorten = list(dict.fromkeys(benen))
    delen = []
    for b in soorten:
        t = tijden.get(b)
        if t is not None:
            tijd = f"{'≈' if t.voorspeld else ''}{toon_waarde(t.tijd, 'tijd')}"
            delen.append(tijd if len(soorten) == 1 else f"{regelset.onderdelen[b].naam}: {tijd}")
    return " · ".join(delen) or None
