"""Periodisering van een groep: megacyclus (fasen over het jaar) en mesocyclus (blok van een paar weken).

Hoort bij personen.db (tabellen groep_fase, mesocyclus, mesocyclus_week; migratie 007).
Geen persoonsgegevens.

Eén regel voor allebei: een rij heeft een startdatum en geldt tot de volgende
rij van dezelfde soort begint. Er worden alleen startdatums bewaard; in welke
fase en mesoweek een datum valt, wordt hier uitgerekend en nooit per training
opgeslagen.

    p = Periodisering(fasen, cycli)
    p.fase_op(date(2027, 1, 12))      -> Fase('V2', ...) of None
    p.mesoweek_op(date(2027, 1, 12))  -> MesoWeek(nummer=3, naam='Piek', ...) of None
    p.op(date(2027, 1, 12)).kort      -> 'V2 · wk 3 Piek'
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta

#: De fasen van de megacyclus: code -> (naam in de app, korte uitleg).
#: 'Geen' beëindigt de periodisering (bijv. einde seizoen); zonder 'Geen' loopt de laatste fase door.
FASEN: dict[str, tuple[str, str]] = {
    "V1": ("Algemene voorbereiding", "Basis: conditie, kracht, techniek in de breedte"),
    "V2": ("Specifieke voorbereiding", "Wedstrijdspecifiek trainen, intensiteit omhoog"),
    "WP": ("Wedstrijdperiode", "Wedstrijden, onderhouden en scherp blijven"),
    "Rust": ("Overgang / rust", "Herstel, actieve rust"),
    "Geen": ("Geen periodisering", "Vanaf hier geen fase meer"),
}
FASE_CODES: tuple[str, ...] = tuple(FASEN)
MAX_WEKEN = 12                         # langste mesocyclus


@dataclass(slots=True, frozen=True)
class Fase:
    """Eén rij van de megacyclus: vanaf startdatum geldt deze fase."""
    startdatum: date
    fase: str                          # een van FASE_CODES

    def __post_init__(self) -> None:
        if self.fase not in FASEN:
            raise ValueError(f"Onbekende fase {self.fase!r}; kies uit {', '.join(FASE_CODES)}.")

    @property
    def naam(self) -> str:
        return FASEN[self.fase][0]

    @property
    def is_geen(self) -> bool:
        return self.fase == "Geen"


@dataclass(slots=True, frozen=True)
class MesoWeek:
    """De week van een mesocyclus waar een datum in valt."""
    nummer: int                        # 1 .. aantal
    aantal: int                        # weken in de cyclus
    naam: str                          # 'Piek'; '' = geen eigen naam
    begin: date                        # eerste dag van deze week

    @property
    def titel(self) -> str:
        """De naam, of 'Week 3' als de week geen eigen naam heeft."""
        return self.naam or f"Week {self.nummer}"


@dataclass(slots=True)
class Mesocyclus:
    """Een blok van `aantal_weken` weken dat zich herhaalt vanaf startdatum (tot de volgende mesocyclus).

    weeknamen: de naam per week, in volgorde ('' = geen eigen naam, de app toont
    dan 'Week n'). Ontbrekende namen worden '', namen na aantal_weken vervallen.
    """
    startdatum: date
    aantal_weken: int
    weeknamen: list[str] = field(default_factory=list)
    groep_id: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= int(self.aantal_weken) <= MAX_WEKEN:
            raise ValueError(f"Een mesocyclus heeft 1 tot {MAX_WEKEN} weken.")
        self.aantal_weken = int(self.aantal_weken)
        namen = [" ".join(str(n or "").split()) for n in self.weeknamen][: self.aantal_weken]
        self.weeknamen = namen + [""] * (self.aantal_weken - len(namen))

    def week_op(self, datum: date) -> MesoWeek | None:
        """De week waar datum in valt (de cyclus herhaalt zich), of None vóór de startdatum."""
        if datum < self.startdatum:
            return None
        weken = (datum - self.startdatum).days // 7
        nummer = weken % self.aantal_weken + 1
        return MesoWeek(nummer, self.aantal_weken, self.weeknamen[nummer - 1],
                        self.startdatum + timedelta(weeks=weken))


@dataclass(slots=True, frozen=True)
class Periode:
    """Waar een datum in de periodisering valt: de fase en/of de mesoweek (allebei optioneel)."""
    fase: Fase | None = None
    week: MesoWeek | None = None

    def __bool__(self) -> bool:
        return self.fase is not None or self.week is not None

    @property
    def kort(self) -> str:
        """'V2 · wk 3 Piek' (voor lijsten)."""
        delen = []
        if self.fase:
            delen.append(self.fase.fase)
        if self.week:
            delen.append(f"wk {self.week.nummer} {self.week.naam}".rstrip())
        return " · ".join(delen)

    @property
    def lang(self) -> str:
        """'Specifieke voorbereiding (V2) · week 3 van 4: Piek'."""
        delen = []
        if self.fase:
            delen.append(f"{self.fase.naam} ({self.fase.fase})")
        if self.week:
            tekst = f"week {self.week.nummer} van {self.week.aantal}"
            if self.week.naam:
                tekst += f": {self.week.naam}"
            delen.append(tekst)
        return " · ".join(delen)


def _geldend(items: list, datum: date):
    """Het item met de laatste startdatum <= datum (items gesorteerd op startdatum), of None."""
    i = bisect_right([x.startdatum for x in items], datum)
    return items[i - 1] if i else None


@dataclass(slots=True)
class Periodisering:
    """De megacyclus (fasen) en mesocycli van één groep. Lijsten worden op startdatum gesorteerd."""
    fasen: list[Fase] = field(default_factory=list)
    cycli: list[Mesocyclus] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.fasen = sorted(self.fasen, key=lambda f: f.startdatum)
        self.cycli = sorted(self.cycli, key=lambda m: m.startdatum)

    @property
    def leeg(self) -> bool:
        return not self.fasen and not self.cycli

    def fase_op(self, datum: date) -> Fase | None:
        """De fase op datum; None vóór de eerste fase of in 'Geen'."""
        f = _geldend(self.fasen, datum)
        return None if f is None or f.is_geen else f

    def mesocyclus_op(self, datum: date) -> Mesocyclus | None:
        return _geldend(self.cycli, datum)

    def mesoweek_op(self, datum: date) -> MesoWeek | None:
        m = self.mesocyclus_op(datum)
        return m.week_op(datum) if m else None

    def op(self, datum: date) -> Periode:
        return Periode(self.fase_op(datum), self.mesoweek_op(datum))

    def fase_blokken(self, van: date, tot: date) -> list[tuple[Fase, date, date]]:
        """De fasen tussen van en tot (beide inclusief) als (fase, begin, eind), afgekapt op van/tot.
        'Geen' en de tijd vóór de eerste fase komen er niet in."""
        uit = []
        for i, f in enumerate(self.fasen):
            eind = self.fasen[i + 1].startdatum - timedelta(days=1) if i + 1 < len(self.fasen) else tot
            begin, eind = max(f.startdatum, van), min(eind, tot)
            if begin <= eind and not f.is_geen:
                uit.append((f, begin, eind))
        return uit
