"""Instellingen van de app: eerste dag van de week, licht/donker thema en tijdnotatie.

De keuzes staan in `instellingen.json` in de datamap (naast de databases, dus
ook git-genegeerd). Er staat geen persoonlijke informatie in, daarom is dit
gewoon JSON en geen SQLCipher-database.

Elke keuze kan ook 'systeem' zijn: dan volgt AVS de instellingen van de
computer (zie `instellingen.systeem`). AVS draait altijd op de computer van de
gebruiker zelf, dus de server kan die gewoon uitlezen. Het thema 'systeem'
regelt de browser zelf (CSS `prefers-color-scheme`).

Gebruik in de rest van de code:

    from instellingen import dagvolgorde, tijd, tijdvak
    for dag in dagvolgorde(): ...            # ('zondag', 'maandag', …) als de week op zondag begint
    tijd("18:30")                            # '18:30u' of '6:30PM'

De UI zet de actieve instellingen per request (`activeer(laad(map))`). Zonder
activeren (bijv. in losse tests) geldt de vaste Nederlandse standaard: week op
maandag, 24-uursklok, zodat uitkomsten niet van de testcomputer afhangen.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from models import DAGEN

from . import systeem

BESTAND = "instellingen.json"
SYSTEEM = "systeem"

#: Keuzes zoals ze in het bestand staan → tekst in de UI.
EERSTE_DAG_KEUZES: dict[str, str] = {SYSTEEM: "Zoals de computer", **{d: d.capitalize() for d in DAGEN}}
THEMA_KEUZES: dict[str, str] = {SYSTEEM: "Zoals de computer", "licht": "Licht", "donker": "Donker"}
TIJD_KEUZES: dict[str, str] = {SYSTEEM: "Zoals de computer", "24": "24-uursklok", "12": "12-uursklok"}

#: Waarde voor het data-theme-attribuut van <html> (avs.css); None = de browser volgt de computer.
_THEMA_ATTRIBUUT = {"licht": "light", "donker": "dark", SYSTEEM: None}


@dataclass(frozen=True)
class Instellingen:
    eerste_dag: str = SYSTEEM          # 'systeem' of 'maandag' … 'zondag'
    thema: str = SYSTEEM               # 'systeem', 'licht' of 'donker'
    tijdnotatie: str = SYSTEEM         # 'systeem', '24' of '12'

    def __post_init__(self) -> None:
        for veld, keuzes in (("eerste_dag", EERSTE_DAG_KEUZES), ("thema", THEMA_KEUZES),
                             ("tijdnotatie", TIJD_KEUZES)):
            if getattr(self, veld) not in keuzes:
                raise ValueError(f"Onbekende keuze {getattr(self, veld)!r} voor {veld}.")

    # ---------- wat er werkelijk geldt ('systeem' ingevuld) ----------
    @property
    def eerste_weekdag(self) -> int:
        """0 = maandag … 6 = zondag (zoals date.weekday())."""
        if self.eerste_dag == SYSTEEM:
            return systeem.eerste_weekdag()
        return DAGEN.index(self.eerste_dag)

    @property
    def tijd_24(self) -> bool:
        if self.tijdnotatie == SYSTEEM:
            return systeem.tijd_24()
        return self.tijdnotatie == "24"

    @property
    def thema_attribuut(self) -> str | None:
        return _THEMA_ATTRIBUUT[self.thema]

    # ---------- hulpjes ----------
    def dagen(self) -> tuple[str, ...]:
        """De dagen van de week in weergavevolgorde, beginnend bij de eerste dag."""
        i = self.eerste_weekdag
        return DAGEN[i:] + DAGEN[:i]

    def weekbegin(self, d: date) -> date:
        """De eerste dag van de week waar d in valt."""
        return d - timedelta(days=(d.weekday() - self.eerste_weekdag) % 7)

    def tijd(self, hhmm: str | None) -> str:
        """'18:30' -> '18:30u' (24-uurs) of '6:30PM' (12-uurs). Onleesbaar blijft zoals het is."""
        delen = _uren_minuten(hhmm)
        if delen is None:
            return hhmm or ""
        u, m = delen
        if self.tijd_24:
            return f"{u:02d}:{m:02d}u"
        return f"{_uur_12(u)}:{m:02d}{_ampm(u)}"

    def tijdvak(self, begin: str | None, eind: str | None) -> str:
        """Begin- en eindtijd samen: '18:00–18:45u', '6:00–6:45PM' of '11:30AM–12:15PM'."""
        b, e = _uren_minuten(begin), _uren_minuten(eind)
        if b is None or e is None:
            return self.tijd(begin) if not eind else f"{self.tijd(begin)}–{self.tijd(eind)}"
        if self.tijd_24:
            return f"{b[0]:02d}:{b[1]:02d}–{self.tijd(eind)}"
        if _ampm(b[0]) == _ampm(e[0]):
            return f"{_uur_12(b[0])}:{b[1]:02d}–{self.tijd(eind)}"
        return f"{self.tijd(begin)}–{self.tijd(eind)}"


def _uren_minuten(hhmm: str | None) -> tuple[int, int] | None:
    """'18:30' of '18:30:00' -> (18, 30); anders None."""
    if not hhmm:
        return None
    delen = str(hhmm).strip().split(":")
    if len(delen) < 2 or not all(x.isdigit() for x in delen[:2]):
        return None
    u, m = int(delen[0]), int(delen[1])
    if not (0 <= u <= 23 and 0 <= m <= 59):
        return None
    return u, m


def _uur_12(u: int) -> int:
    return u % 12 or 12


def _ampm(u: int) -> str:
    return "AM" if u < 12 else "PM"


# ============================================================
# Bestand
# ============================================================
def _pad(map: Path | None) -> Path:
    from db.init_db import standaard_map
    return (Path(map) if map else standaard_map()) / BESTAND


def laad(map: Path | None = None) -> Instellingen:
    """De opgeslagen instellingen; ontbreekt het bestand of klopt een waarde niet, dan de standaard."""
    try:
        gegevens = json.loads(_pad(map).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Instellingen()
    uit = Instellingen()
    if isinstance(gegevens, dict):
        for veld in asdict(uit):
            try:
                uit = replace(uit, **{veld: gegevens[veld]})
            except (KeyError, TypeError, ValueError):
                continue                           # deze ene waarde overslaan, de rest wel gebruiken
    return uit


def opslaan(inst: Instellingen, map: Path | None = None) -> None:
    """Schrijf de instellingen weg (eerst naar een tijdelijk bestand, dan vervangen)."""
    pad = _pad(map)
    pad.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=pad.parent, delete=False,
                                     prefix=".instellingen-", suffix=".tmp") as f:
        json.dump(asdict(inst), f, indent=2)
        tijdelijk = f.name
    os.replace(tijdelijk, pad)


def uit_formulier(form) -> Instellingen:
    """Instellingen uit het formulier van de pagina Instellingen. ValueError bij een onbekende keuze."""
    return Instellingen(eerste_dag=form.get("eerste_dag", SYSTEEM), thema=form.get("thema", SYSTEEM),
                        tijdnotatie=form.get("tijdnotatie", SYSTEEM))


# ============================================================
# Actieve instellingen (één gebruiker, één thread: zie ui/app.py)
# ============================================================
#: Buiten de app (scripts, tests): vast, niet afhankelijk van de computer.
NEDERLANDS = Instellingen(eerste_dag="maandag", tijdnotatie="24")
_actief = NEDERLANDS


def activeer(inst: Instellingen) -> None:
    global _actief
    _actief = inst


def actief() -> Instellingen:
    return _actief


def dagvolgorde() -> tuple[str, ...]:
    return _actief.dagen()


def weekbegin(d: date) -> date:
    return _actief.weekbegin(d)


def eerste_weekdag() -> int:
    return _actief.eerste_weekdag


def tijd(hhmm: str | None) -> str:
    return _actief.tijd(hhmm)


def tijdvak(begin: str | None, eind: str | None) -> str:
    return _actief.tijdvak(begin, eind)
