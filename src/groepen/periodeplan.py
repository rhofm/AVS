"""Periodisering van een groep: megacyclus en mesocycli invullen, het jaaroverzicht, en kopiëren.

Pagina's:
  * Periodisering wijzigen (/groep/<id>/periodisering): de megacyclus als lijst
    rijen (fase + startdatum) en de mesocycli (startdatum, aantal weken, naam per
    week). Alles wordt in één keer opgeslagen en vervangt wat er stond. Een rij
    zonder datum telt niet mee: zo haal je een rij weg.
  * Jaaroverzicht (op de groepspagina en de pagina hierboven): de fasen als
    gekleurde balk over twaalf maanden, de mesoweken eronder, met 'vandaag'.
  * Kopiëren naar andere groepen: de megacyclus en/of de mesocycli. Kopiëren
    vervangt wat de andere groep had; daarna zijn de groepen weer los van elkaar
    (er wordt niets gekoppeld).

De startdatum van een mesocyclus wordt op het begin van de week gezet
(instellingen.weekbegin), zodat de weken gelijk lopen met de kalender.
Geen SQL: alles via `Opslag`. Wat er in welke fase/week valt: models/periodisering.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Mapping

from db.queries import Opslag, OpslagFout
from instellingen import weekbegin
from models import FASE_CODES, FASEN, Fase, Groep, Mesocyclus, Periode, Periodisering
from models.periodisering import MAX_WEKEN

LEGE_FASE_RIJEN = 3                   # zoveel lege rijen onder de megacyclus om iets toe te voegen
LEGE_CYCLI = 1                        # en zoveel lege mesocycli
STANDAARD_WEKEN = 4
MAX_NAAM = 40
MAANDEN_TERUG = 3                     # het jaaroverzicht begint zoveel maanden voor vandaag
MAANDEN = ("jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec")


# ============================================================
# Formulier
# ============================================================
@dataclass
class FaseRij:
    fase: str = ""                    # code uit FASE_CODES, '' = nog niet gekozen
    start: str = ""                   # 'YYYY-MM-DD' zoals in het formulier


@dataclass
class CyclusRij:
    start: str = ""
    weken: int = STANDAARD_WEKEN
    namen: list[str] = field(default_factory=lambda: [""] * MAX_WEKEN)


@dataclass
class Formulier:
    groep: Groep
    fasen: list[FaseRij]
    cycli: list[CyclusRij]

    @property
    def fase_keuzes(self) -> list[tuple[str, str]]:
        """(code, 'V1 – Algemene voorbereiding') voor de keuzelijst."""
        return [(c, f"{c} – {FASEN[c][0]}") for c in FASE_CODES]

    @property
    def max_weken(self) -> int:
        return MAX_WEKEN


def _met_lege(rijen: list, leeg, aantal: int) -> list:
    return rijen + [leeg() for _ in range(aantal)]


def formulier(db: Opslag, groep_id: int, *, ingevuld: Mapping[str, str] | None = None) -> Formulier | None:
    """Het formulier met wat er is opgeslagen, of (na een fout) met wat er was ingevuld."""
    groep = db.groep(groep_id)
    if groep is None:
        return None
    if ingevuld is not None:
        fasen = [FaseRij(f, s) for f, s in _fase_velden(ingevuld) if f or s]
        cycli = [c for c in _cyclus_velden(ingevuld) if c.start or any(c.namen)]
    else:
        fasen = [FaseRij(f.fase, f.startdatum.isoformat()) for f in db.groep_fasen(groep_id)]
        cycli = [CyclusRij(m.startdatum.isoformat(), m.aantal_weken, m.weeknamen + [""] * (MAX_WEKEN - m.aantal_weken))
                 for m in db.mesocycli(groep_id)]
    return Formulier(groep, _met_lege(fasen, FaseRij, LEGE_FASE_RIJEN), _met_lege(cycli, CyclusRij, LEGE_CYCLI))


def _aantal(formulier: Mapping[str, str], voorvoegsel: str) -> int:
    """Hoeveel genummerde rijen er in het formulier staan (velden '<voorvoegsel><i>...')."""
    nummers = [int(k[len(voorvoegsel):].split("-")[0]) for k in formulier
               if k.startswith(voorvoegsel) and k[len(voorvoegsel):].split("-")[0].isdigit()]
    return max(nummers) + 1 if nummers else 0


def _fase_velden(formulier: Mapping[str, str]) -> list[tuple[str, str]]:
    """Velden 'fase-<i>' en 'fasestart-<i>' als (fase, start), in volgorde."""
    n = max(_aantal(formulier, "fase-"), _aantal(formulier, "fasestart-"))
    return [(str(formulier.get(f"fase-{i}", "")).strip(), str(formulier.get(f"fasestart-{i}", "")).strip())
            for i in range(n)]


def _cyclus_velden(formulier: Mapping[str, str]) -> list[CyclusRij]:
    """Velden 'meso-<i>-start', 'meso-<i>-weken', 'meso-<i>-naam-<n>' (n = 1..12)."""
    uit = []
    for i in range(_aantal(formulier, "meso-")):
        try:
            weken = int(str(formulier.get(f"meso-{i}-weken", STANDAARD_WEKEN)).strip() or STANDAARD_WEKEN)
        except ValueError:
            weken = STANDAARD_WEKEN
        namen = [" ".join(str(formulier.get(f"meso-{i}-naam-{n}", "")).split())[:MAX_NAAM]
                 for n in range(1, MAX_WEKEN + 1)]
        uit.append(CyclusRij(str(formulier.get(f"meso-{i}-start", "")).strip(), weken, namen))
    return uit


def _datum(tekst: str, wat: str) -> date:
    try:
        return date.fromisoformat(tekst)
    except ValueError:
        raise OpslagFout(f"{wat}: {tekst!r} is geen geldige datum.") from None


def lees_fasen(formulier: Mapping[str, str]) -> list[Fase]:
    """De fasen uit het formulier. Een rij zonder datum telt niet mee; een datum zonder fase is een fout."""
    uit = []
    for n, (fase, start) in enumerate(_fase_velden(formulier), start=1):
        if not start:
            continue
        if fase not in FASEN:
            raise OpslagFout(f"Megacyclus, rij {n}: kies een fase.")
        uit.append(Fase(_datum(start, f"Megacyclus, rij {n}"), fase))
    return uit


def lees_mesocycli(formulier: Mapping[str, str]) -> list[Mesocyclus]:
    """De mesocycli uit het formulier; start op het begin van de week. Zonder startdatum telt hij niet mee."""
    uit = []
    for n, c in enumerate(_cyclus_velden(formulier), start=1):
        if not c.start:
            continue
        if not 1 <= c.weken <= MAX_WEKEN:
            raise OpslagFout(f"Mesocyclus {n}: kies 1 tot {MAX_WEKEN} weken.")
        uit.append(Mesocyclus(weekbegin(_datum(c.start, f"Mesocyclus {n}")), c.weken, c.namen[: c.weken]))
    return uit


@dataclass
class Opgeslagen:
    fasen: list[Fase]
    cycli: list[Mesocyclus]
    verschoven: int = 0               # mesocycli waarvan de start naar het begin van de week is gezet

    @property
    def tekst(self) -> str:
        if not self.fasen and not self.cycli:
            return "Periodisering opgeslagen: geen fasen en geen mesocycli."
        delen = [f"{len(self.fasen)} {'fasen' if len(self.fasen) != 1 else 'fase'}",
                 f"{len(self.cycli)} {'mesocycli' if len(self.cycli) != 1 else 'mesocyclus'}"]
        tekst = "Periodisering opgeslagen: " + " en ".join(delen) + "."
        if self.verschoven:
            tekst += " De start van een mesocyclus is op het begin van de week gezet."
        return tekst


def opslaan(db: Opslag, groep_id: int, formulier: Mapping[str, str]) -> Opgeslagen:
    """Lees en controleer alles eerst; sla daarna megacyclus en mesocycli op (vervangt wat er stond)."""
    if db.groep(groep_id) is None:
        raise OpslagFout(f"Groep {groep_id} bestaat niet.")
    fasen = lees_fasen(formulier)
    cycli = lees_mesocycli(formulier)
    verschoven = sum(1 for c, rij in zip(cycli, [r for r in _cyclus_velden(formulier) if r.start])
                     if c.startdatum.isoformat() != rij.start)
    for lijst, wat in ((fasen, "fasen"), (cycli, "mesocycli")):
        starts = [x.startdatum for x in lijst]
        if len(starts) != len(set(starts)):
            raise OpslagFout(f"Twee {wat} beginnen op dezelfde dag"
                             + (" (na het verschuiven naar het begin van de week)." if wat == "mesocycli" else "."))
    fasen = db.groep_fasen_opslaan(groep_id, fasen)
    cycli = db.mesocycli_opslaan(groep_id, cycli)
    return Opgeslagen(fasen, cycli, verschoven)


# ============================================================
# Jaaroverzicht
# ============================================================
@dataclass
class Blok:
    """Een stuk van een balk in het jaaroverzicht; links en breedte in procenten."""
    begin: date
    eind: date
    links: float
    breedte: float
    code: str = ""                    # fase-code (voor de kleur)
    titel: str = ""                   # wat er in het blok staat
    uitleg: str = ""                  # tooltip / voor schermlezers
    afwisselend: bool = False         # mesoweken: om en om een tint, per cyclus

    @property
    def weken(self) -> int:
        return (self.eind - self.begin).days // 7 + 1


@dataclass
class Jaaroverzicht:
    van: date
    tot: date
    fasen: list[Blok]
    weken: list[Blok]                 # alleen weken die in een mesocyclus vallen
    maanden: list[tuple[str, float]]  # ('okt', links in %)
    vandaag: date
    nu: Periode

    @property
    def vandaag_pct(self) -> float | None:
        return _pct(self.van, self.tot, self.vandaag) if self.van <= self.vandaag <= self.tot else None

    @property
    def vorige(self) -> date:
        return _maand_erbij(self.van, -12)

    @property
    def volgende(self) -> date:
        return _maand_erbij(self.van, 12)

    @property
    def leeg(self) -> bool:
        return not self.fasen and not self.weken

    @property
    def legenda(self) -> list[tuple[str, str]]:
        """(code, naam) van de fasen met een kleur ('Geen' heeft geen kleur)."""
        return [(c, FASEN[c][0]) for c in FASE_CODES if c != "Geen"]


def _maand_erbij(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def _pct(van: date, tot: date, d: date) -> float:
    return round(100 * (d - van).days / ((tot - van).days + 1), 3)


def _blok(van: date, tot: date, begin: date, eind: date, **kw) -> Blok:
    begin, eind = max(begin, van), min(eind, tot)
    return Blok(begin, eind, _pct(van, tot, begin), round(_pct(van, tot, eind + timedelta(days=1)) - _pct(van, tot, begin), 3), **kw)


def jaaroverzicht(plan: Periodisering, *, vandaag: date | None = None, van: date | None = None) -> Jaaroverzicht:
    """Twaalf maanden vanaf `van` (de eerste van een maand; standaard MAANDEN_TERUG maanden voor vandaag)."""
    vandaag = vandaag or date.today()
    van = date(van.year, van.month, 1) if van else _maand_erbij(date(vandaag.year, vandaag.month, 1), -MAANDEN_TERUG)
    tot = _maand_erbij(van, 12) - timedelta(days=1)
    fasen = [_blok(van, tot, b, e, code=f.fase, titel=f.fase,
                   uitleg=f"{f.naam} ({f.fase}): {b.isoformat()} t/m {e.isoformat()}")
             for f, b, e in plan.fase_blokken(van, tot)]
    weken = []
    week = weekbegin(van)
    while week <= tot:
        m = plan.mesocyclus_op(week)
        w = m.week_op(week) if m else None
        if w is not None:
            nr = plan.cycli.index(m)
            weken.append(_blok(van, tot, week, week + timedelta(days=6), titel=str(w.nummer),
                               uitleg=f"Week van {week.isoformat()}: week {w.nummer} van {w.aantal} ({w.titel})",
                               afwisselend=nr % 2 == 1))
        week += timedelta(weeks=1)
    maanden = [(MAANDEN[_maand_erbij(van, i).month - 1], _pct(van, tot, _maand_erbij(van, i))) for i in range(12)]
    return Jaaroverzicht(van, tot, fasen, weken, maanden, vandaag, plan.op(vandaag))


# ============================================================
# Kopiëren naar andere groepen
# ============================================================
@dataclass
class Kopieerdoel:
    groep: Groep
    fasen: int                        # wat die groep nu heeft (wordt vervangen)
    cycli: int

    def overschrijft(self, fasen: bool, cycli: bool) -> str:
        """Wat er bij deze groep verloren gaat: '4 fasen en 1 mesocyclus', of '' als er niets wordt overschreven."""
        delen = []
        if fasen and self.fasen:
            delen.append(f"{self.fasen} {'fasen' if self.fasen != 1 else 'fase'}")
        if cycli and self.cycli:
            delen.append(f"{self.cycli} {'mesocycli' if self.cycli != 1 else 'mesocyclus'}")
        return " en ".join(delen)


@dataclass
class Kopieerpagina:
    bron: Groep
    plan: Periodisering
    doelen: list[Kopieerdoel]         # alle andere groepen; zelfde seizoen eerst


def kopieerpagina(db: Opslag, groep_id: int) -> Kopieerpagina | None:
    bron = db.groep(groep_id)
    if bron is None:
        return None
    anderen = [g for g in db.groepen() if g.id != groep_id]
    anderen.sort(key=lambda g: (g.seizoen != bron.seizoen, g.naam.lower()))
    doelen = [Kopieerdoel(g, len(db.groep_fasen(g.id)), len(db.mesocycli(g.id))) for g in anderen]
    return Kopieerpagina(bron, db.periodisering(groep_id), doelen)


@dataclass
class Gekopieerd:
    groepen: list[Groep]
    fasen: bool
    cycli: bool

    @property
    def tekst(self) -> str:
        if not self.groepen:
            return "Niets gekopieerd."
        wat = " en ".join(w for w, aan in (("de megacyclus", self.fasen), ("de mesocycli", self.cycli)) if aan)
        return f"{wat[0].upper()}{wat[1:]} gekopieerd naar {', '.join(g.naam for g in self.groepen)}."


def kopieren(db: Opslag, bron_id: int, doel_ids: list[int], *, fasen: bool, cycli: bool) -> Gekopieerd:
    """Kopieer de megacyclus en/of mesocycli van de bron naar de doelgroepen (vervangt wat die hadden)."""
    if db.groep(bron_id) is None:
        raise OpslagFout(f"Groep {bron_id} bestaat niet.")
    if not fasen and not cycli:
        raise OpslagFout("Kies wat je wilt kopiëren: de megacyclus, de mesocycli of allebei.")
    doelen = []
    for gid in dict.fromkeys(doel_ids):
        g = db.groep(gid)
        if g is None or gid == bron_id:
            raise OpslagFout("Kies andere, bestaande groepen om naar te kopiëren.")
        doelen.append(g)
    if not doelen:
        raise OpslagFout("Kies minstens één groep om naar te kopiëren.")
    plan = db.periodisering(bron_id)
    for g in doelen:
        if fasen:
            db.groep_fasen_opslaan(g.id, plan.fasen)
        if cycli:
            db.mesocycli_opslaan(g.id, [Mesocyclus(m.startdatum, m.aantal_weken, list(m.weeknamen))
                                        for m in plan.cycli])
    return Gekopieerd(doelen, fasen, cycli)
