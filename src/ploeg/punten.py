"""Punten bij een prestatie, en de prestatie die nodig is voor een aantal punten.

De constanten staan niet in deze code maar in `config/puntentelling/<uitgave>.yaml`
(nu `au_2025.yaml`: "Formules & Constanten", december 2025). Een nieuwe uitgave
van de Atletiekunie = een nieuw YAML-bestand, geen codewijziging.

Gebruik:

    from ploeg import punten
    punten.punten("au_u14_u16", "80m", "V", 11.2)            # -> 586
    punten.punten("au_senioren", "100m", "M", 11.2, handtijd=True)
    punten.prestatie_voor("au_u14_u16", "verspringen", "M", 500)   # -> 4.41

Regels uit het document:

- Prestaties in seconden (lopen) of meters (springen, werpen); 1.02.2 op de
  400 m is dus 62.2.
- Het puntenaantal wordt **afgekapt**, niet afgerond (627,43 -> 627).
- Constanten voor lopen gaan uit van elektronische tijden. Een handtijd wordt
  eerst gecorrigeerd: +0,24 s t/m 300 m (ook horden) en estafettes t/m
  4x80 m, +0,14 s op 400 m, 400 m horden en 4x100 m (`handtijd_correctie`).
- Geen geldige of een heel zwakke prestatie: 0 punten (nooit negatief).

Dit bestand rekent alleen; welke tabel bij welke competitie hoort staat in de
regelbestanden (`config/ploeg_regels/`).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from ploeg.config import config_map

STANDAARD_UITGAVE = "au_2025"

FORMULES = ("au_loop", "au_techn", "lineair", "wa_loop", "wa_spring", "wa_werp")
LOOP_FORMULES = ("au_loop", "wa_loop")      # lager is beter
MET_C = ("lineair", "wa_loop", "wa_spring", "wa_werp")

ALLE = "alle"                               # geslachtssleutel voor 'jongens/meisjes samen'
GESLACHTEN = ("M", "V")

_EPS = 1e-9          # vangt afrondfouten van floats op bij afkappen en grenzen
_STAP = 0.01         # tijden in honderdsten, afstanden in centimeters


class PuntenFout(ValueError):
    """Onbekende tabel, onderdeel of geslacht, of een kapot puntentellingbestand."""


# ============================================================
# Formules
# ============================================================
@dataclass(frozen=True, slots=True)
class Stuk:
    """Eén formule met constanten; `tot` = geldt t/m deze prestatie (None = daarboven)."""

    formule: str
    A: float
    B: float
    C: float | None = None
    tot: float | None = None

    def ruw(self, w: float) -> float:
        """Het puntenaantal vóór afkappen. Buiten het bereik van de formule: 0."""
        A, B, C = self.A, self.B, self.C
        f = self.formule
        if f == "au_loop":
            return A / w - B
        if f == "au_techn":
            return A * math.sqrt(w) - B
        if f == "lineair":
            return (w - B) * A + C
        if f == "wa_loop":
            return A * (B - w) ** C if w < B else 0.0
        if f == "wa_spring":
            return A * (100 * (w - B)) ** C if w > B else 0.0
        if f == "wa_werp":
            return A * (w - B) ** C if w > B else 0.0
        raise PuntenFout(f"Onbekende formule {f!r}")

    def grens(self, p: float) -> float:
        """De prestatie waarbij `ruw` precies p is (de inverse van de formule)."""
        A, B, C = self.A, self.B, self.C
        f = self.formule
        if f == "au_loop":
            return A / (p + B)
        if f == "au_techn":
            return ((p + B) / A) ** 2
        if f == "lineair":
            return (p - C) / A + B
        if f == "wa_loop":
            return B - (p / A) ** (1 / C)
        if f == "wa_spring":
            return B + (p / A) ** (1 / C) / 100
        if f == "wa_werp":
            return B + (p / A) ** (1 / C)
        raise PuntenFout(f"Onbekende formule {f!r}")


@dataclass(frozen=True, slots=True)
class Formule:
    """De puntentelling van één onderdeel: één stuk, of meer stukken met een knik."""

    onderdeel: str
    stukken: tuple[Stuk, ...]

    @property
    def lager_is_beter(self) -> bool:
        return self.stukken[0].formule in LOOP_FORMULES

    def _stuk(self, w: float) -> Stuk:
        for s in self.stukken:
            if s.tot is None or w <= s.tot + _EPS:
                return s
        return self.stukken[-1]

    def punten(self, prestatie: float) -> int:
        """Afgekapt puntenaantal, minimaal 0. Prestatie <= 0 = geen prestatie = 0."""
        if prestatie is None or not math.isfinite(prestatie) or prestatie <= 0:
            return 0
        ruw = self._stuk(prestatie).ruw(prestatie)
        return max(0, math.floor(ruw + _EPS))

    def prestatie_voor(self, punten: int, afronden: bool = True) -> float:
        """De zwakste prestatie die nog minstens `punten` punten oplevert.

        Lopen: de langzaamste tijd, technisch: de kortste afstand of laagste
        hoogte. Met `afronden` op honderdsten (tijd naar beneden, afstand naar
        boven), zoals een prestatie gemeten wordt.
        """
        if punten <= 0:
            raise ValueError("Geef een puntenaantal van minstens 1.")
        if self.lager_is_beter:
            w = self.stukken[0].grens(punten)
            if not afronden:
                return w
            w = math.floor(w / _STAP + _EPS) * _STAP
            while self.punten(w) < punten:
                w -= _STAP
            return round(w, 2)

        # Technisch (hoger is beter): het eerste stuk waarin de grens valt.
        # Valt hij voor het begin van een stuk (sprong in de puntentabel bij
        # een knik), dan is het begin van dat stuk de zwakste prestatie.
        ondergrens = 0.0
        w = None
        for s in self.stukken:
            g = s.grens(punten)
            if g < ondergrens:
                g = ondergrens
            if s.tot is None or g <= s.tot + _EPS:
                w = g
                break
            ondergrens = s.tot
        assert w is not None
        if not afronden:
            return w
        w = math.ceil(w / _STAP - _EPS) * _STAP
        while self.punten(w) < punten:
            w += _STAP
        return round(w, 2)


# ============================================================
# Handtijden
# ============================================================
_VLAK = re.compile(r"^(\d+)m(h(-\d+)?)?$")       # 100m, 80mH, 60mH-84
_ESTAFETTE = re.compile(r"^4x(\d+)m$")           # 4x100m


def handtijd_correctie(onderdeel: str) -> float:
    """Seconden die bij een handtijd opgeteld worden (Formules & Constanten, punt 4).

    +0,24 s: t/m 300 m (ook horden over die afstanden) en estafettes t/m 4x80 m
    (start niet op de plaats van de finish). +0,14 s: 400 m, 400 m horden en
    4x100 m. Andere onderdelen: geen correctie.
    """
    n = onderdeel.strip().lower()
    m = _VLAK.match(n)
    if m:
        afstand = int(m.group(1))
        if afstand <= 300:
            return 0.24
        if afstand == 400:
            return 0.14
        return 0.0
    m = _ESTAFETTE.match(n)
    if m:
        been = int(m.group(1))
        if been <= 80:
            return 0.24
        if been == 100:
            return 0.14
    return 0.0


# ============================================================
# Puntentelling (een uitgave van Formules & Constanten)
# ============================================================
class Puntentelling:
    """Alle tabellen uit één YAML-bestand.

    `tabellen[tabel][geslacht][onderdeel] -> Formule`, met geslacht 'M', 'V' of
    'alle' (zelfde constanten voor jongens en meisjes, of gemengde estafette).
    """

    def __init__(self, naam: str, uitgave: str, tabellen: dict[str, dict[str, dict[str, Formule]]],
                 omschrijvingen: dict[str, str]):
        self.naam = naam
        self.uitgave = uitgave
        self.tabellen = tabellen
        self.omschrijvingen = omschrijvingen

    # ---------------- laden ----------------
    @classmethod
    def uit_bestand(cls, pad: Path) -> "Puntentelling":
        try:
            with open(pad, encoding="utf-8") as f:
                ruw = yaml.safe_load(f)
        except FileNotFoundError:
            raise PuntenFout(f"Puntentelling {pad.name} niet gevonden in {pad.parent}.") from None
        except yaml.YAMLError as e:
            raise PuntenFout(f"{pad.name} is geen geldige YAML: {e}") from None
        return cls.uit_dict(ruw, bron=pad.name)

    @classmethod
    def uit_dict(cls, ruw: dict, bron: str = "puntentelling") -> "Puntentelling":
        if not isinstance(ruw, dict) or not isinstance(ruw.get("tabellen"), dict):
            raise PuntenFout(f"{bron}: 'tabellen' ontbreekt.")
        tabellen: dict[str, dict[str, dict[str, Formule]]] = {}
        omschrijvingen: dict[str, str] = {}
        for tabel, inhoud in ruw["tabellen"].items():
            if not isinstance(inhoud, dict):
                raise PuntenFout(f"{bron}: tabel {tabel!r} is leeg of geen lijst van geslachten.")
            omschrijvingen[tabel] = str(inhoud.get("omschrijving", "")).strip()
            tabellen[tabel] = {}
            for geslacht, onderdelen in inhoud.items():
                if geslacht == "omschrijving":
                    continue
                if geslacht not in (*GESLACHTEN, ALLE):
                    raise PuntenFout(f"{bron}: {tabel}: onbekend geslacht {geslacht!r} "
                                     f"(kies uit M, V, alle).")
                if not isinstance(onderdelen, dict):
                    raise PuntenFout(f"{bron}: {tabel}.{geslacht} bevat geen onderdelen.")
                tabellen[tabel][geslacht] = {
                    str(o): _formule(f"{bron}: {tabel}.{geslacht}.{o}", str(o), d)
                    for o, d in onderdelen.items()
                }
        return cls(str(ruw.get("naam", bron)), str(ruw.get("uitgave", "")), tabellen, omschrijvingen)

    # ---------------- opvragen ----------------
    def formule(self, tabel: str, onderdeel: str, geslacht: str) -> Formule:
        if tabel not in self.tabellen:
            raise PuntenFout(f"Onbekende puntentabel {tabel!r}; kies uit {sorted(self.tabellen)}.")
        g = (geslacht or "").strip().upper()
        if g not in GESLACHTEN:
            raise PuntenFout(f"Onbekend geslacht {geslacht!r}; kies M of V.")
        t = self.tabellen[tabel]
        for sleutel in (g, ALLE):
            if onderdeel in t.get(sleutel, {}):
                return t[sleutel][onderdeel]
        raise PuntenFout(f"Geen puntentelling voor {onderdeel!r} ({g}) in tabel {tabel!r}.")

    def heeft(self, tabel: str, onderdeel: str, geslacht: str) -> bool:
        try:
            self.formule(tabel, onderdeel, geslacht)
            return True
        except PuntenFout:
            return False

    def onderdelen(self, tabel: str, geslacht: str) -> list[str]:
        """Alle onderdelen met een puntentelling voor dit geslacht in deze tabel."""
        if tabel not in self.tabellen:
            raise PuntenFout(f"Onbekende puntentabel {tabel!r}.")
        t = self.tabellen[tabel]
        return sorted({*t.get(geslacht.upper(), {}), *t.get(ALLE, {})})

    def punten(self, tabel: str, onderdeel: str, geslacht: str, prestatie: float,
               handtijd: bool = False) -> int:
        f = self.formule(tabel, onderdeel, geslacht)
        if handtijd and f.lager_is_beter and prestatie and prestatie > 0:
            prestatie = prestatie + handtijd_correctie(onderdeel)
        return f.punten(prestatie)

    def prestatie_voor(self, tabel: str, onderdeel: str, geslacht: str, punten: int,
                       afronden: bool = True) -> float:
        return self.formule(tabel, onderdeel, geslacht).prestatie_voor(punten, afronden)


def _getal(waar: str, d: dict, sleutel: str) -> float:
    v = d.get(sleutel)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PuntenFout(f"{waar}: {sleutel} ontbreekt of is geen getal.")
    return float(v)


def _stuk(waar: str, d) -> Stuk:
    if not isinstance(d, dict):
        raise PuntenFout(f"{waar}: verwacht {{formule: ..., A: ..., B: ...}}.")
    f = d.get("formule")
    if f not in FORMULES:
        raise PuntenFout(f"{waar}: onbekende formule {f!r}; kies uit {FORMULES}.")
    C = _getal(waar, d, "C") if f in MET_C else None
    tot = _getal(waar, d, "tot") if "tot" in d else None
    return Stuk(f, _getal(waar, d, "A"), _getal(waar, d, "B"), C, tot)


def _formule(waar: str, onderdeel: str, d) -> Formule:
    stukken = tuple(_stuk(f"{waar}[{i}]", s) for i, s in enumerate(d)) if isinstance(d, list) \
        else (_stuk(waar, d),)
    if not stukken:
        raise PuntenFout(f"{waar}: geen formule.")
    for s in stukken[:-1]:
        if s.tot is None:
            raise PuntenFout(f"{waar}: elk stuk behalve het laatste heeft 'tot' nodig.")
    if stukken[-1].tot is not None:
        raise PuntenFout(f"{waar}: het laatste stuk heeft geen 'tot'.")
    grenzen = [s.tot for s in stukken[:-1]]
    if grenzen != sorted(grenzen) or len(set(grenzen)) != len(grenzen):
        raise PuntenFout(f"{waar}: de 'tot'-grenzen moeten oplopen.")
    if len(stukken) > 1 and any(s.formule in LOOP_FORMULES for s in stukken):
        raise PuntenFout(f"{waar}: een knik in de formule kan alleen bij technische onderdelen.")
    return Formule(onderdeel, stukken)


# ============================================================
# Gemak: de standaarduitgave
# ============================================================
@lru_cache(maxsize=8)
def _laad(uitgave: str, map: str) -> Puntentelling:
    return Puntentelling.uit_bestand(Path(map) / "puntentelling" / f"{uitgave}.yaml")


def puntentelling(uitgave: str = STANDAARD_UITGAVE, map: Path | None = None) -> Puntentelling:
    """De puntentelling uit `config/puntentelling/<uitgave>.yaml` (eenmaal ingelezen)."""
    return _laad(uitgave, str(map or config_map()))


def punten(tabel: str, onderdeel: str, geslacht: str, prestatie: float,
           handtijd: bool = False, uitgave: str = STANDAARD_UITGAVE) -> int:
    """Punten voor een prestatie (seconden of meters) volgens de standaarduitgave."""
    return puntentelling(uitgave).punten(tabel, onderdeel, geslacht, prestatie, handtijd)


def prestatie_voor(tabel: str, onderdeel: str, geslacht: str, punten: int,
                   afronden: bool = True, uitgave: str = STANDAARD_UITGAVE) -> float:
    """De zwakste prestatie die nog minstens zoveel punten oplevert."""
    return puntentelling(uitgave).prestatie_voor(tabel, onderdeel, geslacht, punten, afronden)
