"""Overzichtspagina's van een groep: PR's, testresultaten, leerdoelen en aanwezigheid.

Elke functie geeft een tabel met de atleten als rijen, kant-en-klaar voor de UI
(opgemaakte waarden, 'beste' gemarkeerd). Bereikbaar vanaf de landingspagina
van de groep (groepen/landingspagina.py).

Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from atleten.aanwezigheid import NIET_INGEVULD, STATUS_TEKST
from atleten.landingspagina import categorie_code, leeftijdscategorie
from atleten.prestaties import toon_waarde
from atleten.testen import laatste_per_test
from db.queries import Opslag
from leerlijnen.voortgang import leerdoelenpagina
from models import Atleet, Groep, Training

from .landingspagina import DagAanwezigheid, GroepLid, LeerlijnGemiddelde, _aanwezigheid, _leerdoelen

#: Korte letter per status in het aanwezigheidsregister (naast de kleur).
STATUS_LETTER = {"aanwezig": "A", "afgemeld": "M", "afwezig": "X", "blessure": "B", NIET_INGEVULD: "?"}


# ============================================================
# Gedeeld: één rij per atleet
# ============================================================
@dataclass
class Rij:
    atleet: Atleet
    categorie: str | None
    cellen: list = field(default_factory=list)

    @property
    def categorie_code(self) -> str | None:
        return categorie_code(self.categorie, self.atleet.geslacht)


#: Volgorde van de leeftijdscategorieën, jong naar oud.
CATEGORIE_VOLGORDE = ("U8", "U10", "U12", "U14", "U16", "U18", "U20", "Senior")


def _volgorde(rij: Rij) -> tuple:
    """Sorteersleutel: categorie (jong naar oud), dan geslacht; onbekende categorie achteraan."""
    if rij.categorie not in CATEGORIE_VOLGORDE:
        return (len(CATEGORIE_VOLGORDE), "")
    return (CATEGORIE_VOLGORDE.index(rij.categorie), rij.atleet.geslacht or "")


def _markeer_beste(rijen: list[Rij], waarden: list[list[float | None]], lager_is_beter: list[bool]) -> None:
    """Zet Waarde.beste per kolom, alleen binnen dezelfde categorie (U16M met U16M, U16V met U16V, ...).

    waarden[i][k] is de ruwe waarde van rij i in kolom k (None = geen waarde).
    Een categorie met maar één waarde in een kolom krijgt geen 'beste'; atleten
    zonder bekende categorie worden niet vergeleken.
    """
    per_categorie: dict[str, list[int]] = {}
    for i, r in enumerate(rijen):
        if r.categorie_code is not None:
            per_categorie.setdefault(r.categorie_code, []).append(i)
    for k, lager in enumerate(lager_is_beter):
        for ids in per_categorie.values():
            gevuld = [i for i in ids if waarden[i][k] is not None]
            if len(gevuld) < 2:
                continue
            kies = min if lager else max
            top = kies(waarden[i][k] for i in gevuld)
            for i in gevuld:
                rijen[i].cellen[k].beste = waarden[i][k] == top


def _atleten(db: Opslag, groep: Groep, vandaag: date) -> list[tuple[Atleet, str | None]]:
    uit = []
    for mid in groep.leden:
        a = db.atleet(mid)
        if a is not None:
            uit.append((a, leeftijdscategorie(a, vandaag)))
    return uit


# ============================================================
# PR's
# ============================================================
@dataclass
class Waarde:
    tekst: str                        # '12,93', '4,80 m'
    beste: bool = False               # beste van de groep in deze kolom
    datum: date | None = None         # bij testresultaten: wanneer getest


@dataclass
class Kolom:
    naam: str
    sub: str | None = None            # categorie van het onderdeel / eenheid van de test


@dataclass
class Tabel:
    groep: Groep
    kolommen: list[Kolom]
    rijen: list[Rij]                  # cellen: Waarde of None, één per kolom; op categorie gesorteerd

    @property
    def per_categorie(self) -> list[tuple[str | None, list[Rij]]]:
        """De rijen per categoriecode ('U16M'), in de volgorde van `rijen`."""
        uit: list[tuple[str | None, list[Rij]]] = []
        for r in self.rijen:
            if not uit or uit[-1][0] != r.categorie_code:
                uit.append((r.categorie_code, []))
            uit[-1][1].append(r)
        return uit

    @property
    def gevuld(self) -> int:
        """Aantal ingevulde cellen."""
        return sum(1 for r in self.rijen for c in r.cellen if c is not None)


def prs(db: Opslag, groep: Groep, *, peildatum: date | None = None) -> Tabel:
    """PR's van alle atleten: één kolom per onderdeel waarop minstens één atleet een PR heeft."""
    vandaag = peildatum or date.today()
    atleten = _atleten(db, groep, vandaag)
    onderdelen = {o.id: o for o in db.onderdelen()}
    per_atleet = {a.master_id: {pr.onderdeel_id: pr.waarde for pr in db.prs(a.master_id)} for a, _ in atleten}
    gebruikt = sorted({oid for p in per_atleet.values() for oid in p},
                      key=lambda oid: (onderdelen[oid].categorie or "", onderdelen[oid].naam))
    rijen = []
    for a, cat in atleten:
        p = per_atleet[a.master_id]
        rijen.append(Rij(a, cat, [Waarde(toon_waarde(p[oid], onderdelen[oid].eenheid)) if oid in p else None
                                  for oid in gebruikt]))
    rijen.sort(key=_volgorde)
    _markeer_beste(rijen, [[per_atleet[r.atleet.master_id].get(oid) for oid in gebruikt] for r in rijen],
                   [onderdelen[oid].lager_is_beter for oid in gebruikt])
    return Tabel(groep, [Kolom(onderdelen[oid].naam, onderdelen[oid].categorie) for oid in gebruikt], rijen)


# ============================================================
# Testresultaten
# ============================================================
def _getal(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def testresultaten(db: Opslag, groep: Groep, *, peildatum: date | None = None) -> Tabel:
    """Het laatste resultaat per test van alle atleten: één kolom per test met minstens één resultaat."""
    vandaag = peildatum or date.today()
    atleten = _atleten(db, groep, vandaag)
    testen = {t.id: t for t in db.testen()}
    per_atleet = {a.master_id: laatste_per_test(db, a.master_id) for a, _ in atleten}
    gebruikt = sorted({tid for p in per_atleet.values() for tid in p}, key=lambda tid: testen[tid].naam)
    rijen = []
    for a, cat in atleten:
        p = per_atleet[a.master_id]
        rijen.append(Rij(a, cat, [None if tid not in p else Waarde(_getal(p[tid].waarde), datum=p[tid].datum)
                                  for tid in gebruikt]))
    rijen.sort(key=_volgorde)
    _markeer_beste(rijen, [[per_atleet[r.atleet.master_id][tid].waarde if tid in per_atleet[r.atleet.master_id]
                            else None for tid in gebruikt] for r in rijen],
                   [testen[tid].lager_is_beter for tid in gebruikt])
    return Tabel(groep, [Kolom(testen[tid].naam, testen[tid].eenheid) for tid in gebruikt], rijen)


# ============================================================
# Leerdoelen per atleet
# ============================================================
@dataclass
class LeerlijnCel:
    aantal: int                       # leerdoelen van de eigen categorie op deze leerlijn
    beoordeeld: int
    zelfstandig: int
    gemiddelde: float | None

    @property
    def pct(self) -> int:
        return round(100 * self.zelfstandig / self.aantal) if self.aantal else 0


@dataclass
class LeerdoelenTabel:
    groep: Groep
    kolommen: list[Kolom]             # leerlijnen
    rijen: list[Rij]                  # cellen: LeerlijnCel of None (leerlijn niet voor deze categorie)
    gemiddelden: list[LeerlijnGemiddelde | None]   # per kolom, zoals op de landingspagina


def leerdoelen(db: Opslag, groep: Groep, *, peildatum: date | None = None) -> LeerdoelenTabel:
    """Per atleet per leerlijn: hoeveel leerdoelen zelfstandig, hoeveel beoordeeld, gemiddelde score."""
    vandaag = peildatum or date.today()
    atleten = _atleten(db, groep, vandaag)
    per_atleet: dict[str, dict[str, LeerlijnCel]] = {}
    for a, cat in atleten:
        p = leerdoelenpagina(db, a.master_id, cat, peildatum=vandaag)
        per_atleet[a.master_id] = {b.code: LeerlijnCel(b.aantal, b.beoordeeld, b.zelfstandig,
                                                       round(b.gemiddelde, 1) if b.gemiddelde is not None else None)
                                   for b in (p.leerlijnen if p else [])}
    lijnen = [(code, naam) for code, naam in db.leerdoel_leerlijnen()
              if any(code in p for p in per_atleet.values())]
    leden = [GroepLid(a, cat, []) for a, cat in atleten]
    gem = {g.code: g for g in _leerdoelen(db, leden)}
    rijen = [Rij(a, cat, [per_atleet[a.master_id].get(code) for code, _ in lijnen]) for a, cat in atleten]
    return LeerdoelenTabel(groep, [Kolom(naam, code) for code, naam in lijnen], rijen,
                           [gem.get(code) for code, _ in lijnen])


# ============================================================
# Aanwezigheidsregister
# ============================================================
@dataclass
class RegisterCel:
    status: str                       # een van ABSENTIE_STATUSSEN of NIET_INGEVULD
    reden: str | None = None

    @property
    def letter(self) -> str:
        return STATUS_LETTER[self.status]

    @property
    def tekst(self) -> str:
        return STATUS_TEKST[self.status] + (f": {self.reden}" if self.reden else "")


@dataclass
class RegisterRij(Rij):
    @property
    def ingevuld(self) -> int:
        return sum(1 for c in self.cellen if c is not None and c.status != NIET_INGEVULD)

    @property
    def aanwezig(self) -> int:
        return sum(1 for c in self.cellen if c is not None and c.status == "aanwezig")

    @property
    def percentage(self) -> float | None:
        return round(100 * self.aanwezig / self.ingevuld, 1) if self.ingevuld else None


@dataclass
class Register:
    groep: Groep
    trainingen: list[Training]        # oudste eerst (kolommen)
    rijen: list[RegisterRij]          # cellen: RegisterCel of None (niet ingeroosterd, niets opgeslagen)
    per_dag: list[DagAanwezigheid]
    van: date
    tot: date
    weken: int

    def aanwezig_op(self, i: int) -> int:
        return sum(1 for r in self.rijen if r.cellen[i] is not None and r.cellen[i].status == "aanwezig")

    @property
    def percentage(self) -> float | None:
        aanwezig = sum(r.aanwezig for r in self.rijen)
        ingevuld = sum(r.ingevuld for r in self.rijen)
        return round(100 * aanwezig / ingevuld, 1) if ingevuld else None


def aanwezigheid(db: Opslag, groep: Groep, *, peildatum: date | None = None, weken: int = 12) -> Register:
    """Wie was er op welke training, de laatste `weken` weken t/m vandaag.

    Een cel is 'niet ingevuld' als de atleet die weekdag volgens zijn schema traint
    maar er nog niets is opgeslagen; leeg (None) als hij niet ingeroosterd was.
    """
    vandaag = peildatum or date.today()
    van = vandaag - timedelta(weeks=weken)
    trainingen = db.trainingen(groep.id, van=van, tot=vandaag)
    statussen = {t.id: {a.atleet_id: a for a in db.absenties(t.id)} for t in trainingen}
    rijen = []
    for a, cat in _atleten(db, groep, vandaag):
        schema = db.trainingsschema(a.master_id)
        cellen = []
        for t in trainingen:
            s = statussen[t.id].get(a.master_id)
            if s is not None:
                cellen.append(RegisterCel(s.status, s.reden))
            elif schema.traint_op(t.datum):
                cellen.append(RegisterCel(NIET_INGEVULD))
            else:
                cellen.append(None)
        rijen.append(RegisterRij(a, cat, cellen))
    return Register(groep, trainingen, rijen, _aanwezigheid(db, groep, van, vandaag), van, vandaag, weken)
