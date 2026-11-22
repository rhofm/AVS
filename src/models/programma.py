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
_GEWICHT = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,3})?)\s?kg\b", re.I)     # '3kg', '7,26 kg', '0.6kg'


@dataclass(slots=True)
class ProgrammaOnderdeel:
    wedstrijd_id: int
    datum: date
    starttijd: str                       # 'HH:MM'
    onderdeel_id: int | None = None      # onderdeel uit de lijst; None = (nog) niet gekoppeld
    onderdeel_tekst: str | None = None   # naam zoals in het tijdschema, bijv. '60m horden 76,2cm'
    categorie: str | None = None         # bijv. 'Vrouwen U16', 'Meisjes U16' (oud), 'JU14'; None = voor iedereen
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

    # ---------- groep ----------
    @property
    def gewicht(self) -> str | None:
        """Gewicht van het werptuig uit het tijdschema, bijv. '4kg' of '7,26kg'; None als er geen staat.

        Gemengde werpgroepen (leeftijd en geslacht door elkaar) zijn per gewicht ingedeeld; dat gewicht
        staat in de naam van het onderdeel ('Kogelstoten 4kg'), de opmerking of de categorie.
        """
        for tekst in (self.onderdeel_tekst, self.opmerking, self.categorie):
            if tekst and (m := _GEWICHT.search(tekst)):
                return m.group(1).replace(".", ",") + "kg"
        return None

    @property
    def groep_sleutel(self) -> str:
        """Wat bij een inschrijving wordt bewaard als de trainer een groep kiest: 'Mannen|2', 'Vrouwen|', '|1',
        met gewicht 'Mannen|2|4kg'.

        Categorie + groepsnummer (+ gewicht) van de regel, dus ook na het opnieuw importeren van het
        tijdschema nog te vinden (regel-id's veranderen dan wel).
        """
        basis = self.groep_sleutel_zonder_gewicht
        return f"{basis}|{self.gewicht}" if self.gewicht else basis

    @property
    def groep_sleutel_zonder_gewicht(self) -> str:
        """De sleutel van vóór het gewicht erbij kwam; bewaarde keuzes van toen blijven zo werken."""
        return f"{self.categorie or ''}|{self.groep or ''}"

    @property
    def groep_tekst(self) -> str:
        """Voor een keuzelijst: 'Mannen · groep 2', 'Vrouwen', 'Groep 1', 'Alle'; met gewicht '4kg · Mannen · groep 2'."""
        delen = [self.gewicht, self.categorie, f"groep {self.groep}" if self.groep else None]
        tekst = " · ".join(d for d in delen if d)
        return tekst[:1].upper() + tekst[1:] if tekst else "Alle"

    # ---------- tekst ----------
    @property
    def naam(self) -> str:
        return self.onderdeel_tekst or ""

    @property
    def omschrijving(self) -> str:
        """Bijv. '60m horden 76,2cm Vrouwen U16, serie, groep 2'."""
        kop = " ".join(x for x in (self.naam, self.categorie) if x)
        rest = [x for x in (self.ronde, f"groep {self.groep}" if self.groep else None) if x]
        return ", ".join([kop, *rest])


# ============================================================
# Categorie uit de tekst van een tijdschema
# ============================================================
_LEEFTIJD = re.compile(r"\b(?:[MJVW]?U)\s?(\d{1,2})\b", re.I)        # 'U16', 'U 16', 'MU16', 'JU14', 'VU20'
_MASTERS = re.compile(r"\bmasters?\b", re.I)
_MASTERS_KLASSE = re.compile(r"\b([MV])\s?(\d{2})(\+)?(?!\d)", re.I)         # 'M35', 'V40', 'M 85', 'V60+'

#: Masterscategorieën van vijf jaar: M35, V40, ..., 95 (de laatste klasse is 95+). Zoals ploeg.regels.masters_code.
MASTERS_KLASSEN = tuple(range(35, 100, 5))


def masters_categorie(klasse: int) -> str:
    """'Masters 40': de categorie van een atleet van 40 t/m 44 (leeftijd op de wedstrijddag)."""
    return f"Masters {klasse}"


def is_masters(categorie: str | None) -> bool:
    """'Masters' (klasse onbekend) of 'Masters 40'."""
    return categorie == "Masters" or (categorie is not None and categorie.startswith("Masters "))


def masters_klasse(categorie: str | None) -> int | None:
    """40 voor 'Masters 40'; None voor 'Masters' zonder klasse en voor al het andere."""
    if categorie is None or not categorie.startswith("Masters "):
        return None
    getal = categorie[len("Masters "):].rstrip("+")
    return int(getal) if getal.isdecimal() else None


def _klasse_in(tekst: str) -> tuple[str, int, bool] | None:
    """('V', 40, False) voor 'V40', ('M', 35, True) voor 'M35+'. Alleen echte klassen: 35, 40, ..., 95."""
    for m in _MASTERS_KLASSE.finditer(tekst):
        if int(m.group(2)) in MASTERS_KLASSEN:
            return m.group(1).upper(), int(m.group(2)), bool(m.group(3))
    return None
_SENIOR = re.compile(r"\b(senioren|seniors?|sen|mannen|vrouwen|heren|dames|[MV]sen)\b", re.I)
_VROUW = re.compile(r"\b(meisjes|meiden|vrouwen|dames|Vsen|VU\d{1,2})\b|-V\b|\bSEN-V\b", re.I)
_MAN = re.compile(r"\b(jongens|mannen|heren|JU\d{1,2}|Msen)\b|-M\b|\bSEN-M\b", re.I)
_MU = re.compile(r"\bMU\s?(\d{1,2})\b", re.I)                              # MU16 = meisjes, MU20 = mannen


def lees_categorie(tekst: str | None) -> tuple[str | None, str | None]:
    """Categorie en geslacht uit tijdschema-tekst: ('U16', 'V'), ('Senior', 'M'), (None, None).

    'Vrouwen U16' -> ('U16', 'V'); 'Mannen U14' -> ('U14', 'M'). Sinds de Atletiekunie alle
    categorieën mannen/vrouwen noemt is dat de norm; de oude woorden en notaties blijven leesbaar
    voor oude tijdschema's en links: 'Meisjes U16' / 'MU16' -> ('U16', 'V'); 'Jongens U14' / 'JU14' -> ('U14', 'M');
    'Vrouwen' / 'VSen' -> ('Senior', 'V'); 'U12' -> ('U12', None). Wat niet te lezen is: None.
    Ook de notatie van atletiek.nu: 'U16-V' -> ('U16', 'V'), 'SEN-M' -> ('Senior', 'M'),
    'VU20+V Masters' -> ('U20', 'V'), 'MU20 + M Masters' -> ('U20', 'M') (MU20 = mannen U20).
    En wat de Seltec-importer maakt: 'U16-V', 'SEN-M', 'Masters-V' -> ('Masters', 'V').
    Masterklassen: 'M35' -> ('Masters 35', 'M'), 'V40' -> ('Masters 40', 'V'), 'V35+' -> ('Masters 35+', 'V')
    (vanaf 35); 'Masters' zonder klasse -> ('Masters', ...).
    Eén categorie per keer; een lijst ('U18-M, U16-V') splitst wedstrijden/chronoloog.past_bij.
    """
    if not tekst or not tekst.strip():
        return None, None
    klasse = None
    if m := _LEEFTIJD.search(tekst):
        leeftijd = f"U{int(m.group(1))}"
    elif klasse := _klasse_in(tekst):
        leeftijd = masters_categorie(klasse[1]) + ("+" if klasse[2] else "")
    elif _MASTERS.search(tekst):
        leeftijd = "Masters"            # 35+, klasse onbekend
    elif _SENIOR.search(tekst):
        leeftijd = "Senior"
    else:
        leeftijd = None
    if klasse:
        geslacht = klasse[0]            # de letter van de klasse: M35 = mannen, V40 = vrouwen
    elif _VROUW.search(tekst):
        geslacht = "V"
    elif _MAN.search(tekst):
        geslacht = "M"
    elif m := _MU.search(tekst):
        # Atletiekunie: MU8 t/m MU18 = meisjes, maar MU20 = mannen U20 (naast VU20 = vrouwen).
        geslacht = "M" if int(m.group(1)) >= 20 else "V"
    else:
        geslacht = None
    return leeftijd, geslacht
