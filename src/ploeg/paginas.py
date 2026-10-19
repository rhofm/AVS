"""Gegevens voor de ploegpagina's in de UI (menu 'Ploegen').

- `overzicht()`: alle ploegen, nieuwste wedstrijddag eerst.
- `formulier()` / `lees_formulier()`: nieuwe ploeg of gegevens wijzigen
  (naam, competitie + ploeg, welke wedstrijd, datum of gekoppelde wedstrijd,
  prestatiebasis).
- `ploegpagina()`: de matrix atleten x onderdelen met de opstelling, de punten
  en de controle; `opstelling_opslaan()` slaat het formulier van die pagina op.

De templates krijgen alleen deze dataclasses; SQL en regels blijven in db/ en ploeg/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Mapping

from db.queries import Opslag, OpslagFout
from models import PRESTATIEBASIS, Atleet, Inzet, Ploeg, PloegLid, Wedstrijd
from ploeg import opstelling as _opstelling
from ploeg import regels as _regels
from ploeg.regels import Overtreding, RegelFout, Regelset
from ploeg.vergelijk import Matrix, matrix


class InvoerFout(ValueError):
    """Fouten in het formulier, per veld: {'naam': 'Geef de ploeg een naam.'}."""

    def __init__(self, fouten: dict[str, str]):
        super().__init__("; ".join(fouten.values()))
        self.fouten = fouten


def programma_label(programma: str) -> str:
    """'wedstrijd_2' -> 'Wedstrijd 2', 'finale_2027' -> 'Finale 2027'."""
    return programma.replace("_", " ").strip().capitalize()


# ============================================================
# Overzicht
# ============================================================
@dataclass(slots=True)
class OverzichtRegel:
    ploeg: Ploeg
    competitie: str
    ploegnaam: str                  # 'U16 meisjes'
    programma: str                  # 'Wedstrijd 2'
    wedstrijd: Wedstrijd | None
    deelnemers: int
    reserves: int
    geweest: bool


def overzicht(db: Opslag, vandaag: date) -> list[OverzichtRegel]:
    uit = []
    for p in db.ploegen():
        try:
            rs = _regels.laad(p.regelset)
            ploegnaam = rs.ploeg(p.categorie).naam
            competitie = rs.naam
        except RegelFout:
            ploegnaam, competitie = p.categorie, p.competitie or p.regelset
        leden = db.ploeg_leden(p.id)
        uit.append(OverzichtRegel(
            p, competitie, ploegnaam, programma_label(p.programma),
            db.wedstrijd(p.wedstrijd_id) if p.wedstrijd_id else None,
            sum(1 for lid in leden if lid.rol == "deelnemer"), sum(1 for lid in leden if lid.rol == "reserve"),
            p.datum < vandaag))
    return uit


# ============================================================
# Nieuwe ploeg / gegevens wijzigen
# ============================================================
@dataclass(slots=True)
class Keuze:
    waarde: str
    tekst: str
    groep: str = ""                 # voor <optgroup>


@dataclass(slots=True)
class Formulier:
    naam: str = ""
    ploeg: str = ""                 # '<regelset>|<categorie>'
    programma: str = ""
    wedstrijd: str = ""             # wedstrijd-id als tekst, '' = geen
    datum: str = ""
    prestatiebasis: str = "seizoen"
    ploegen: list[Keuze] = field(default_factory=list)
    programmas: list[Keuze] = field(default_factory=list)
    wedstrijden: list[Keuze] = field(default_factory=list)
    prestatiebases: list[Keuze] = field(default_factory=list)
    regelfouten: list[str] = field(default_factory=list)   # regelbestanden die niet te lezen zijn


def formulier(db: Opslag, vandaag: date, ingevuld: Mapping | None = None, ploeg: Ploeg | None = None) -> Formulier:
    f = Formulier()
    if ploeg is not None:
        f.naam, f.ploeg, f.programma = ploeg.naam, f"{ploeg.regelset}|{ploeg.categorie}", ploeg.programma
        f.wedstrijd = str(ploeg.wedstrijd_id or "")
        f.datum, f.prestatiebasis = ploeg.datum.isoformat(), ploeg.prestatiebasis
    if ingevuld is not None:
        for veld in ("naam", "ploeg", "programma", "wedstrijd", "datum", "prestatiebasis"):
            setattr(f, veld, (ingevuld.get(veld) or "").strip())
    programmas: dict[str, None] = {}
    for bestand in _regels.bestanden():
        try:
            rs = _regels.laad(bestand)
        except RegelFout as e:
            f.regelfouten.append(str(e))
            continue
        for sleutel, p in rs.ploegen.items():
            f.ploegen.append(Keuze(f"{bestand}|{sleutel}", p.naam, rs.naam))
            programmas.update(dict.fromkeys(p.programmas))
    f.programmas = [Keuze(p, programma_label(p)) for p in programmas]
    gekozen = int(f.wedstrijd) if f.wedstrijd.isdigit() else None
    for w in db.wedstrijden(van=vandaag - timedelta(days=60)):
        f.wedstrijden.append(Keuze(str(w.id), f"{w.datum.isoformat()} · {w.naam}"))
    if gekozen and all(k.waarde != str(gekozen) for k in f.wedstrijden) and (w := db.wedstrijd(gekozen)):
        f.wedstrijden.insert(0, Keuze(str(w.id), f"{w.datum.isoformat()} · {w.naam}"))
    f.prestatiebases = [Keuze(k, t) for k, t in PRESTATIEBASIS.items()]
    return f


def lees_formulier(db: Opslag, form: Mapping, bestaande: Ploeg | None = None) -> Ploeg:
    """Ploeg uit het formulier (nog niet opgeslagen). InvoerFout met een melding per veld."""
    fouten: dict[str, str] = {}
    naam = " ".join((form.get("naam") or "").split())
    if not naam:
        fouten["naam"] = "Geef de ploeg een naam, bijv. 'U16 meisjes A'."
    bestand, _, categorie = (form.get("ploeg") or "").partition("|")
    rs: Regelset | None = None
    try:
        rs = _regels.laad(bestand) if bestand else None
        if rs is not None:
            rs.ploeg(categorie)
    except RegelFout as e:
        fouten["ploeg"] = str(e)
        rs = None
    if rs is None and "ploeg" not in fouten:
        fouten["ploeg"] = "Kies de competitie en ploeg."
    programma = form.get("programma") or ""
    if rs is not None and programma not in rs.ploeg(categorie).programmas:
        fouten["programma"] = (f"Kies een wedstrijd van {rs.ploeg(categorie).naam}: "
                               + ", ".join(programma_label(p) for p in rs.programmas(categorie)) + ".")
    wedstrijd = None
    w_tekst = (form.get("wedstrijd") or "").strip()
    if w_tekst:
        wedstrijd = db.wedstrijd(int(w_tekst)) if w_tekst.isdigit() else None
        if wedstrijd is None:
            fouten["wedstrijd"] = "Deze wedstrijd bestaat niet (meer)."
    datum = wedstrijd.datum if wedstrijd else None
    if datum is None:
        try:
            datum = date.fromisoformat((form.get("datum") or "").strip())
        except ValueError:
            fouten["datum"] = "Kies een wedstrijd of vul de datum in."
    basis = form.get("prestatiebasis") or "seizoen"
    if basis not in PRESTATIEBASIS:
        fouten["prestatiebasis"] = "Kies welke prestaties tellen."
    if fouten:
        raise InvoerFout(fouten)
    return Ploeg(naam, bestand, categorie, programma, datum, wedstrijd.id if wedstrijd else None,
                 competitie=rs.naam, strategie=bestaande.strategie if bestaande else None,
                 prestatiebasis=basis, id=bestaande.id if bestaande else None)


def ploeg_opslaan(db: Opslag, ploeg: Ploeg) -> Ploeg:
    """Gegevens opslaan. Bij een andere ploeg of wedstrijd (programma) vervallen onderdelen
    die daar niet op staan; de leden blijven."""
    if ploeg.id is not None:
        oud = db.ploeg(ploeg.id)
        if oud and (oud.regelset, oud.categorie, oud.programma) != (ploeg.regelset, ploeg.categorie, ploeg.programma):
            sleutels = {r.sleutel for r in _regels.laad(ploeg.regelset).programma(ploeg.categorie, ploeg.programma)}
            leden = db.ploeg_leden(ploeg.id)
            inzet = [i for i in db.ploeg_inzet(ploeg.id) if i.onderdeel in sleutels]
            db.ploeg_opslaan(ploeg)
            db.ploeg_opstelling_opslaan(ploeg.id, leden, inzet)
            return ploeg
    return db.ploeg_opslaan(ploeg)


# ============================================================
# De ploegpagina
# ============================================================
@dataclass(slots=True)
class Ploegpagina:
    ploeg: Ploeg
    regelset: Regelset
    ploegnaam: str
    programma: str                       # label
    wedstrijd: Wedstrijd | None
    matrix: Matrix
    rol: dict[str, str]                  # master_id -> 'deelnemer' / 'reserve' (alleen leden)
    inzet: set[tuple[str, str]]          # (master_id, onderdeel)
    stand: _opstelling.Stand
    fouten: list[Overtreding]
    waarschuwingen: list[Overtreding]
    namen: dict[str, str]                # master_id -> naam, voor de meldingen

    @property
    def basis_tekst(self) -> str:
        return PRESTATIEBASIS[self.ploeg.prestatiebasis].lower().replace("pr (", "PR (")

    @property
    def deelnemers(self) -> int:
        return sum(1 for r in self.rol.values() if r == "deelnemer")

    @property
    def reserves(self) -> int:
        return sum(1 for r in self.rol.values() if r == "reserve")

    def melding(self, o: Overtreding) -> str:
        """Tekst van een overtreding met de naam van de atleet erbij."""
        return f"{self.namen.get(o.atleet_id, 'Onbekende atleet')}: {o.tekst}" if o.atleet_id else o.tekst

    def overtredingen_van(self, master_id: str) -> list[Overtreding]:
        return [o for o in (*self.fouten, *self.waarschuwingen) if o.atleet_id == master_id]


def ploegpagina(db: Opslag, ploeg_id: int, leden: list[PloegLid] | None = None,
                inzet: list[Inzet] | None = None) -> Ploegpagina | None:
    """Pagina-gegevens. Zonder leden/inzet: zoals opgeslagen. RegelFout als het regelbestand
    niet (meer) te lezen is."""
    p = db.ploeg(ploeg_id)
    if p is None:
        return None
    if p.wedstrijd_id and (w := db.wedstrijd(p.wedstrijd_id)) is not None:
        wedstrijd = w
        if w.datum != p.datum:               # wedstrijd verzet: de ploeg verhuist mee
            p.datum = w.datum
            db.ploeg_opslaan(p)
    else:
        wedstrijd = None
    rs = _regels.laad(p.regelset)
    leden = db.ploeg_leden(ploeg_id) if leden is None else leden
    inzet = db.ploeg_inzet(ploeg_id) if inzet is None else inzet
    atleten: list[Atleet] = _opstelling.kandidaten(db, rs, p, leden)
    m = matrix(db, rs, p.categorie, p.programma, p.datum, atleten, p.prestatiebasis)
    alles = _opstelling.controleer(db, rs, p, leden, inzet, m)
    return Ploegpagina(
        p, rs, rs.ploeg(p.categorie).naam, programma_label(p.programma), wedstrijd, m,
        {lid.atleet_id: lid.rol for lid in leden}, {(i.atleet_id, i.onderdeel) for i in inzet},
        _opstelling.stand(m, inzet),
        [o for o in alles if o.ernst == "fout"], [o for o in alles if o.ernst == "waarschuwing"],
        {a.master_id: a.naam for a in atleten})


def opstelling_opslaan(db: Opslag, ploeg_id: int, form: Mapping) -> Ploegpagina:
    """Formulier van de ploegpagina opslaan en de nieuwe stand teruggeven.
    Ook een opstelling met fouten wordt opgeslagen: de trainer ziet wat er nog moet."""
    p = db.ploeg(ploeg_id)
    if p is None:
        raise OpslagFout(f"Ploeg {ploeg_id} bestaat niet.")
    rs = _regels.laad(p.regelset)
    huidige = db.ploeg_leden(ploeg_id)
    ids = [a.master_id for a in _opstelling.kandidaten(db, rs, p, huidige)]
    sleutels = [r.sleutel for r in rs.programma(p.categorie, p.programma)]
    leden, inzet = _opstelling.lees_formulier(form, ids, sleutels)
    db.ploeg_opstelling_opslaan(ploeg_id, leden, inzet)
    return ploegpagina(db, ploeg_id)
