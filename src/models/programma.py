"""Dataclass ProgrammaOnderdeel: één regel uit het tijdschema (chronoloog) van een wedstrijd.

Hoort bij prestaties.db (tabel wedstrijd_programma). Geen persoonsgegevens:
het tijdschema is van de wedstrijd. Wie wanneer moet, rekent
wedstrijden/chronoloog.py uit met de inschrijvingen en de categorie van de atleet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .groep import normaliseer_tijd

MAX_DUUR = 720          # minuten (12 uur); een meerkampdag past erin


@dataclass(slots=True)
class ProgrammaOnderdeel:
    wedstrijd_id: int
    datum: date
    starttijd: str                       # 'HH:MM'
    onderdeel_id: int | None = None      # onderdeel uit de lijst; None = (nog) niet gekoppeld
    onderdeel_tekst: str | None = None   # naam zoals in het tijdschema, bijv. '60m horden 76,2cm'
    categorie: str | None = None         # bijv. 'Meisjes U16', 'JU14'; None = voor iedereen
    ronde: str = ""                      # 'serie', 'finale', ...; '' = n.v.t.
    groep: int | None = None             # 1e, 2e, ... groep; None = één groep
    duur: int | None = None              # minuten; None = onbekend
    opmerking: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        tijd = normaliseer_tijd(self.starttijd)
        if tijd is None:
            raise ValueError("Een onderdeel in het tijdschema heeft een starttijd nodig.")
        self.starttijd = tijd
        for veld in ("onderdeel_tekst", "categorie", "opmerking"):
            tekst = getattr(self, veld)
            setattr(self, veld, " ".join(str(tekst).split()) or None if tekst is not None else None)
        self.ronde = " ".join((self.ronde or "").split())
        if self.groep is not None:
            self.groep = int(self.groep)
            if self.groep < 1:
                raise ValueError("Groep is 1, 2, 3, ...")
        if self.duur is not None:
            self.duur = int(self.duur)
            if not 1 <= self.duur <= MAX_DUUR:
                raise ValueError(f"Duur is in minuten, tussen 1 en {MAX_DUUR}.")
        if self.onderdeel_id is None and not self.onderdeel_tekst:
            raise ValueError("Geef het onderdeel op (uit de lijst of als tekst).")

    # ---------- tijd ----------
    @property
    def begin(self) -> datetime:
        u, m = map(int, self.starttijd.split(":"))
        return datetime(self.datum.year, self.datum.month, self.datum.day, u, m)

    @property
    def einde(self) -> datetime | None:
        return self.begin + timedelta(minutes=self.duur) if self.duur else None

    @property
    def eindtijd(self) -> str | None:
        """'HH:MM', of None als de duur onbekend is. Na middernacht: de kloktijd op de volgende dag."""
        return self.einde.strftime("%H:%M") if self.einde else None

    def overlapt(self, ander: ProgrammaOnderdeel) -> bool:
        """Lopen de twee tegelijk? Zonder duur telt alleen dezelfde begintijd als overlap."""
        if self.begin == ander.begin:
            return True
        if self.begin > ander.begin:
            return ander.overlapt(self)
        return self.einde is not None and self.einde > ander.begin

    # ---------- tekst ----------
    @property
    def naam(self) -> str:
        return self.onderdeel_tekst or ""

    @property
    def omschrijving(self) -> str:
        """Bijv. '60m horden 76,2cm Meisjes U16, serie, groep 2'."""
        kop = " ".join(x for x in (self.naam, self.categorie) if x)
        rest = [x for x in (self.ronde, f"groep {self.groep}" if self.groep else None) if x]
        return ", ".join([kop, *rest])


# ============================================================
# Categorie uit de tekst van een tijdschema
# ============================================================
_LEEFTIJD = re.compile(r"\b(?:[MJVW]?U)\s?(\d{1,2})\b", re.I)        # 'U16', 'U 16', 'MU16', 'JU14', 'VU20'
_MASTERS = re.compile(r"\bmasters?\b", re.I)
_SENIOR = re.compile(r"\b(senioren|seniors?|sen|mannen|vrouwen|heren|dames|[MV]sen)\b", re.I)
_VROUW = re.compile(r"\b(meisjes|meiden|vrouwen|dames|Vsen|VU\d{1,2})\b|-V\b|\bSEN-V\b", re.I)
_MAN = re.compile(r"\b(jongens|mannen|heren|JU\d{1,2}|Msen)\b|-M\b|\bSEN-M\b", re.I)
_MU = re.compile(r"\bMU\s?(\d{1,2})\b", re.I)                              # MU16 = meisjes, MU20 = mannen


def lees_categorie(tekst: str | None) -> tuple[str | None, str | None]:
    """Categorie en geslacht uit tijdschema-tekst: ('U16', 'V'), ('Senior', 'M'), (None, None).

    'Meisjes U16' / 'MU16' -> ('U16', 'V'); 'Jongens U14' / 'JU14' -> ('U14', 'M');
    'Vrouwen' / 'VSen' -> ('Senior', 'V'); 'U12' -> ('U12', None). Wat niet te lezen is: None.
    Ook de notatie van atletiek.nu: 'U16-V' -> ('U16', 'V'), 'SEN-M' -> ('Senior', 'M'),
    'VU20+V Masters' -> ('U20', 'V'), 'MU20 + M Masters' -> ('U20', 'M') (MU20 = mannen U20).
    En wat de Seltec-importer maakt: 'U16-V', 'SEN-M', 'Masters-V' -> ('Masters', 'V').
    Eén categorie per keer; een lijst ('U18-M, U16-V') splitst wedstrijden/chronoloog.past_bij.
    """
    if not tekst or not tekst.strip():
        return None, None
    if m := _LEEFTIJD.search(tekst):
        leeftijd = f"U{int(m.group(1))}"
    elif _MASTERS.search(tekst):
        leeftijd = "Masters"            # 35+; geen eigen categorie bij de atleten
    elif _SENIOR.search(tekst):
        leeftijd = "Senior"
    else:
        leeftijd = None
    if _VROUW.search(tekst):
        geslacht = "V"
    elif _MAN.search(tekst):
        geslacht = "M"
    elif m := _MU.search(tekst):
        # Atletiekunie: MU8 t/m MU18 = meisjes, maar MU20 = mannen U20 (naast VU20 = vrouwen).
        geslacht = "M" if int(m.group(1)) >= 20 else "V"
    else:
        geslacht = None
    return leeftijd, geslacht
