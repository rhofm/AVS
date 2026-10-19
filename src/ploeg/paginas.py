"""Gegevens voor de ploegpagina's in de UI (menu 'Ploegen').

- `overzicht()`: alle ploegen, nieuwste wedstrijddag eerst.
- `formulier()` / `lees_formulier()`: nieuwe ploeg of gegevens wijzigen
  (naam, competitie + ploeg, welke wedstrijd, datum of gekoppelde wedstrijd,
  prestatiebasis).
- `ploegpagina()`: de matrix atleten x onderdelen met de opstelling, de punten
  en de controle (met het tijdschema van de gekoppelde wedstrijd: botsingen,
  dagdelen, groepen); `opstelling_opslaan()` slaat het formulier van die pagina op.
- `optimaliseren()`: één ploeg laten maken; `dagpagina()` / `dag_optimaliseren()`:
  alle ploegen van één dag na elkaar (de eerste kiest eerst, 10.10).

De templates krijgen alleen deze dataclasses; SQL en regels blijven in db/ en ploeg/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Mapping

from db.queries import Opslag, OpslagFout
from models import PRESTATIEBASIS, VOORKEUREN, Atleet, Inzet, Ploeg, PloegLid, Wedstrijd
from ploeg import inschrijven as _inschrijven
from ploeg import opstelling as _opstelling
from ploeg import optimaliseer as _optimaliseer
from ploeg import strategieen as _strategieen
from ploeg import regels as _regels
from ploeg import tijdschema as _tijdschema
from ploeg import voorkeuren as _voorkeuren
from ploeg.regels import Overtreding, RegelFout, Regelset
from ploeg.vergelijk import Matrix, matrix, normaliseer


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
    zelfde_dag: int = 1             # aantal ploegen op deze dag (meer dan 1: samen te maken)


def overzicht(db: Opslag, vandaag: date) -> list[OverzichtRegel]:
    uit = []
    for p in db.ploegen():
        try:
            rs = _regels.laad(p.regelset)
            ploegnaam, competitie, programma = rs.ploeg(p.categorie).naam, rs.naam, rs.programma_naam(p.programma)
        except RegelFout:
            ploegnaam, competitie, programma = p.categorie, p.competitie or p.regelset, programma_label(p.programma)
        leden = db.ploeg_leden(p.id)
        uit.append(OverzichtRegel(
            p, competitie, ploegnaam, programma,
            db.wedstrijd(p.wedstrijd_id) if p.wedstrijd_id else None,
            sum(1 for lid in leden if lid.rol == "deelnemer"), sum(1 for lid in leden if lid.rol == "reserve"),
            p.datum < vandaag))
    per_dag: dict[date, int] = {}
    for r in uit:
        per_dag[r.ploeg.datum] = per_dag.get(r.ploeg.datum, 0) + 1
    for r in uit:
        r.zelfde_dag = per_dag[r.ploeg.datum]
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
    gezien: set[tuple[str, str]] = set()
    for bestand in _regels.bestanden():
        try:
            rs = _regels.laad(bestand)
        except RegelFout as e:
            f.regelfouten.append(str(e))
            continue
        for sleutel, p in rs.ploegen.items():
            f.ploegen.append(Keuze(f"{bestand}|{sleutel}", p.naam, rs.naam))
            for prog in p.programmas:
                if (rs.naam, prog) not in gezien:
                    gezien.add((rs.naam, prog))
                    f.programmas.append(Keuze(prog, rs.programma_naam(prog), rs.naam))
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
                               + ", ".join(rs.programma_naam(p) for p in rs.programmas(categorie)) + ".")
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


def _gewenst(db: Opslag, ploeg: Ploeg | None) -> _inschrijven.Gewenst:
    """Inschrijvingen die bij de opgeslagen opstelling horen ({} zonder ploeg of leesbaar regelbestand)."""
    if ploeg is None or ploeg.id is None:
        return {}
    try:
        rs = _regels.laad(ploeg.regelset)
    except RegelFout:
        return {}
    return _inschrijven.gewenst(db, rs, ploeg, db.ploeg_leden(ploeg.id), db.ploeg_inzet(ploeg.id))


def ploeg_opslaan(db: Opslag, ploeg: Ploeg) -> Ploeg:
    """Gegevens opslaan. Bij een andere ploeg of wedstrijd (programma) vervallen onderdelen
    die daar niet op staan; de leden blijven. Een andere gekoppelde wedstrijd: de
    inschrijvingen van de ploeg verhuizen mee."""
    if ploeg.id is None:
        return db.ploeg_opslaan(ploeg)
    oud = db.ploeg(ploeg.id)
    oud_gewenst = _gewenst(db, oud)
    if oud and (oud.regelset, oud.categorie, oud.programma) != (ploeg.regelset, ploeg.categorie, ploeg.programma):
        sleutels = {r.sleutel for r in _regels.laad(ploeg.regelset).programma(ploeg.categorie, ploeg.programma)}
        leden = db.ploeg_leden(ploeg.id)
        inzet = [i for i in db.ploeg_inzet(ploeg.id) if i.onderdeel in sleutels]
        db.ploeg_opslaan(ploeg)
        db.ploeg_opstelling_opslaan(ploeg.id, leden, inzet)
    else:
        db.ploeg_opslaan(ploeg)
    if oud is not None and oud.wedstrijd_id != ploeg.wedstrijd_id:
        _inschrijven.synchroniseer(db, oud, oud_gewenst, {})            # weg van de oude wedstrijd
        oud_gewenst = {}
    _inschrijven.synchroniseer(db, ploeg, oud_gewenst, _gewenst(db, ploeg))
    return ploeg


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
    schema: _tijdschema.Schema | None = None          # tijdschema van de gekoppelde wedstrijd
    beschikbaar: dict[str, str] = field(default_factory=dict)        # master_id -> dagdeel (leden)
    groep: dict[tuple[str, str], int] = field(default_factory=dict)  # (master_id, onderdeel) -> groep
    andere_ploegen: list[Ploeg] = field(default_factory=list)        # andere ploegen op dezelfde dag
    voorkeuren: _voorkeuren.Voorkeuren = field(default_factory=dict)  # (master_id, onderdeel) -> wat geldt

    @property
    def strategieen(self) -> list:
        return list(_strategieen.STRATEGIEEN.values())

    @property
    def strategie_titel(self) -> str | None:
        s = _strategieen.STRATEGIEEN.get(self.ploeg.strategie or "")
        return s.titel if s else None

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

    def tijden(self, onderdeel: str) -> str:
        """Begintijd(en) uit het tijdschema voor de tabelkop, bijv. '10:30' of '10:30 / 13:15'."""
        return " / ".join(self.schema.tijden(onderdeel)) if self.schema else ""

    @property
    def zonder_leeftijdsfactor(self) -> int:
        """Masters: aantal cellen met een prestatie maar zonder leeftijdsfactor (punten zonder age grading)."""
        if not self.regelset.leeftijdsfactoren:
            return 0
        return sum(1 for r in self.matrix.rijen for c in r.cellen.values()
                   if c.waarde is not None and c.punten is not None and c.leeftijdsfactor is None)


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
    schema = _tijdschema.schema(db, rs, p, m) if wedstrijd is not None else None
    voorkeuren = _voorkeuren.effectief(db, rs, p, [a.master_id for a in atleten])
    alles = _opstelling.controleer(db, rs, p, leden, inzet, m, schema, voorkeuren)
    return Ploegpagina(
        p, rs, rs.ploeg(p.categorie).naam, rs.programma_naam(p.programma), wedstrijd, m,
        {lid.atleet_id: lid.rol for lid in leden}, {(i.atleet_id, i.onderdeel) for i in inzet},
        _opstelling.stand(m, inzet),
        [o for o in alles if o.ernst == "fout"], [o for o in alles if o.ernst == "waarschuwing"],
        {a.master_id: a.naam for a in atleten}, schema,
        {lid.atleet_id: lid.beschikbaar for lid in leden},
        {(i.atleet_id, i.onderdeel): i.groep for i in inzet if i.groep is not None},
        [q for q in db.ploegen(p.datum) if q.id != p.id], voorkeuren)


def opstelling_opslaan(db: Opslag, ploeg_id: int, form: Mapping
                       ) -> tuple[Ploegpagina, _inschrijven.Wijzigingen]:
    """Formulier van de ploegpagina opslaan en de nieuwe stand teruggeven, met wat er op
    de gekoppelde wedstrijd is veranderd. Ook een opstelling met fouten wordt opgeslagen:
    de trainer ziet wat er nog moet."""
    huidig = ploegpagina(db, ploeg_id)
    if huidig is None:
        raise OpslagFout(f"Ploeg {ploeg_id} bestaat niet.")
    p, rs = huidig.ploeg, huidig.regelset
    huidige = db.ploeg_leden(ploeg_id)
    oud = _inschrijven.gewenst(db, rs, p, huidige, db.ploeg_inzet(ploeg_id))
    ids = [r.master_id for r in huidig.matrix.rijen]
    sleutels = [r.sleutel for r in rs.programma(p.categorie, p.programma)]
    leden, inzet = _opstelling.lees_formulier(form, ids, sleutels)
    inzet = _tijdschema.groepen_indelen(huidig.schema, rs, inzet, {lid.atleet_id: lid.beschikbaar for lid in leden})
    db.ploeg_opstelling_opslaan(ploeg_id, leden, inzet)
    wijzigingen = _inschrijven.synchroniseer(db, p, oud, _inschrijven.gewenst(db, rs, p, leden, inzet))
    return ploegpagina(db, ploeg_id), wijzigingen


def ploeg_verwijderen(db: Opslag, ploeg_id: int) -> None:
    """Ploeg verwijderen; de inschrijvingen die de ploeg op de gekoppelde wedstrijd zette, gaan mee."""
    p = db.ploeg(ploeg_id)
    if p is None:
        return
    _inschrijven.synchroniseer(db, p, _gewenst(db, p), {})
    db.ploeg_verwijderen(ploeg_id)


# ============================================================
# Optimaliseren
# ============================================================
@dataclass(slots=True)
class Optimalisatie:
    pagina: Ploegpagina
    wijzigingen: _inschrijven.Wijzigingen
    strategie: str                       # titel
    voor: int                            # totaal voor het optimaliseren
    na: int


def optimaliseren(db: Opslag, ploeg_id: int, strategie: str, vastzetten: bool = False,
                  alleen_aangevinkt: bool = True, uitsluiten: set[str] | None = None) -> Optimalisatie:
    """Opstelling maken met een strategie en opslaan (ook op de gekoppelde wedstrijd).

    alleen_aangevinkt: alleen de atleten die nu deelnemer zijn gebruiken (de 'aanwezigen');
    staat er nog niemand in de ploeg, dan alle atleten die mogen.
    uitsluiten: deze atleten niet gebruiken en uit de ploeg halen (al in een eerdere ploeg van
    de dag, zie dag_optimaliseren). Standaard: wie in een andere ploeg van die dag staat.
    OptimalisatieFout als er geen oplossing is; KeyError bij een onbekende strategie.
    """
    s = _strategieen.strategie(strategie)
    pg = ploegpagina(db, ploeg_id)
    if pg is None:
        raise OpslagFout(f"Ploeg {ploeg_id} bestaat niet.")
    p, rs = pg.ploeg, pg.regelset
    leden, inzet = db.ploeg_leden(ploeg_id), db.ploeg_inzet(ploeg_id)
    if uitsluiten is not None:
        andere = set(uitsluiten)
        leden = [lid for lid in leden if lid.atleet_id not in andere]
        inzet = [i for i in inzet if i.atleet_id not in andere]
    else:
        andere = {lid.atleet_id for q in db.ploegen(p.datum) if q.id != p.id for lid in db.ploeg_leden(q.id)}
    deelnemers = [lid.atleet_id for lid in leden if lid.rol == "deelnemer"]
    mag = {r.master_id for r in pg.matrix.rijen if r.toegestaan}
    if alleen_aangevinkt and deelnemers:
        atleten = [a for a in deelnemers if a in mag]
    else:
        atleten = [r.master_id for r in pg.matrix.rijen
                   if r.toegestaan and r.atleet.actief and r.master_id not in andere]
    oud = _inschrijven.gewenst(db, rs, p, db.ploeg_leden(ploeg_id), db.ploeg_inzet(ploeg_id))
    r = _optimaliseer.optimaliseer(pg.matrix, rs, s, atleten, leden, inzet, vastzetten, pg.schema,
                                   pg.voorkeuren)
    db.ploeg_opstelling_opslaan(ploeg_id, r.leden, r.inzet)
    p.strategie = s.naam
    db.ploeg_opslaan(p)
    wijzigingen = _inschrijven.synchroniseer(db, p, oud, _inschrijven.gewenst(db, rs, p, r.leden, r.inzet))
    nieuw = ploegpagina(db, ploeg_id)
    return Optimalisatie(nieuw, wijzigingen, s.titel, pg.stand.totaal, nieuw.stand.totaal)


# ============================================================
# Alle ploegen van één dag
# ============================================================
@dataclass(slots=True)
class DagRegel:
    ploeg: Ploeg
    ploegnaam: str                       # 'U16 meisjes'
    programma: str
    strategie: str                       # code; standaard de laatst gebruikte of max_punten
    deelnemers: int
    fout: str | None = None              # regelbestand niet te lezen


@dataclass(slots=True)
class Dagpagina:
    datum: date
    regels: list[DagRegel]

    @property
    def strategieen(self) -> list:
        return list(_strategieen.STRATEGIEEN.values())


def dagpagina(db: Opslag, datum: date) -> Dagpagina:
    """De ploegen van een dag in de standaardvolgorde (op naam: A voor B)."""
    regels = []
    for p in sorted(db.ploegen(datum), key=lambda q: q.naam.lower()):
        deelnemers = sum(1 for lid in db.ploeg_leden(p.id) if lid.rol == "deelnemer")
        strategie = p.strategie if p.strategie in _strategieen.STRATEGIEEN else "max_punten"
        try:
            rs = _regels.laad(p.regelset)
            regels.append(DagRegel(p, rs.ploeg(p.categorie).naam, rs.programma_naam(p.programma), strategie,
                                   deelnemers))
        except RegelFout as e:
            regels.append(DagRegel(p, p.categorie, programma_label(p.programma), strategie, deelnemers, str(e)))
    return Dagpagina(datum, regels)


def lees_dagformulier(form: Mapping, dag: Dagpagina) -> list[tuple[int, str]]:
    """[(ploeg_id, strategie)] in de gekozen volgorde. Velden: `volgorde-<id>` (1, 2, ...) en
    `strategie-<id>`. Een ploeg met 'overslaan' als strategie doet niet mee. InvoerFout bij onzin."""
    fouten: dict[str, str] = {}
    keuzes = []
    for k, r in enumerate(dag.regels):
        pid = r.ploeg.id
        strategie = form.get(f"strategie-{pid}") or r.strategie
        if strategie == "overslaan":
            continue
        if strategie not in _strategieen.STRATEGIEEN:
            fouten[f"strategie-{pid}"] = f"Onbekende strategie voor {r.ploeg.naam}."
        tekst = (form.get(f"volgorde-{pid}") or str(k + 1)).strip()
        if not tekst.isdigit():
            fouten[f"volgorde-{pid}"] = f"Volgorde van {r.ploeg.naam} is een getal (1 = eerst)."
            continue
        keuzes.append((int(tekst), k, pid, strategie))
    if fouten:
        raise InvoerFout(fouten)
    return [(pid, strategie) for _, _, pid, strategie in sorted(keuzes)]


def dag_optimaliseren(db: Opslag, keuzes: list[tuple[int, str]], vastzetten: bool = False
                      ) -> list[Optimalisatie]:
    """Ploegen na elkaar laten maken (design: A eerst, dan B uit wie over is). Een atleet komt
    in hoogstens één ploeg (10.10): wie in een eerdere ploeg staat, gaat uit de latere.
    Elke ploeg kiest uit alle atleten die mogen (niet alleen de aangevinkte)."""
    gebruikt: set[str] = set()
    uit = []
    for pid, strategie in keuzes:
        o = optimaliseren(db, pid, strategie, vastzetten=vastzetten, alleen_aangevinkt=False,
                          uitsluiten=set(gebruikt))
        uit.append(o)
        gebruikt |= {lid.atleet_id for lid in db.ploeg_leden(pid)}
    for o in uit:                                   # de pagina's zoals het nu is (na de latere ploegen)
        o.pagina = ploegpagina(db, o.pagina.ploeg.id)
    return uit


# ============================================================
# Voorkeuren
# ============================================================
@dataclass(slots=True)
class VoorkeurCel:
    sleutel: str
    ploeg: str                           # ingesteld voor deze ploeg: voorkeur, 'neutraal' of '' (vaste geldt)
    vast: str | None                     # vaste voorkeur van de atleet voor dit onderdeel
    nvt: bool = False                    # atleet mag dit onderdeel niet doen


@dataclass(slots=True)
class VoorkeurRij:
    atleet: Atleet
    lid: bool
    cellen: list[VoorkeurCel]


@dataclass(slots=True)
class Voorkeurpagina:
    ploeg: Ploeg
    ploegnaam: str
    regels: list                          # Programmaregels (kolommen)
    rijen: list[VoorkeurRij]
    keuzes: dict[str, str] = field(default_factory=lambda: dict(VOORKEUREN))


def voorkeurpagina(db: Opslag, ploeg_id: int) -> Voorkeurpagina | None:
    """Per atleet die mag (en per lid) en per onderdeel: de voorkeur voor deze ploeg en de vaste."""
    pg = ploegpagina(db, ploeg_id)
    if pg is None:
        return None
    eigen = db.ploeg_voorkeuren(ploeg_id)
    rs = pg.regelset
    rijen = []
    for rij in pg.matrix.rijen:
        a = rij.atleet
        vast = {normaliseer(n): v for n, v in db.atleet_voorkeuren(a.master_id).items()}
        cellen = [VoorkeurCel(r.sleutel, eigen.get((a.master_id, r.sleutel), ""),
                              vast.get(normaliseer(rs.onderdelen[r.sleutel].naam)), rij.cellen[r.sleutel].nvt)
                  for r in pg.matrix.regels]
        rijen.append(VoorkeurRij(a, a.master_id in pg.rol, cellen))
    rijen.sort(key=lambda r: not r.lid)                  # leden eerst, verder op naam
    return Voorkeurpagina(pg.ploeg, pg.ploegnaam, pg.matrix.regels, rijen)


def voorkeuren_opslaan(db: Opslag, ploeg_id: int, form: Mapping) -> int:
    """Voorkeuren van de ploegpagina opslaan; geeft het aantal ingestelde voorkeuren."""
    vp = voorkeurpagina(db, ploeg_id)
    if vp is None:
        raise OpslagFout(f"Ploeg {ploeg_id} bestaat niet.")
    gelezen = _voorkeuren.lees_ploegformulier(form, [r.atleet.master_id for r in vp.rijen],
                                              [r.sleutel for r in vp.regels])
    # voorkeuren van atleten die hier (nu) niet op de pagina staan, blijven bewaard
    zichtbaar = {r.atleet.master_id for r in vp.rijen}
    bewaard = {k: v for k, v in db.ploeg_voorkeuren(ploeg_id).items() if k[0] not in zichtbaar}
    db.ploeg_voorkeuren_opslaan(ploeg_id, {**bewaard, **gelezen})
    return len(gelezen)


@dataclass(slots=True)
class AtleetVoorkeuren:
    atleet: Atleet
    groepen: dict[str, list[str]]        # 'Lopen' -> ['60 meter', ...]
    gekozen: dict[str, str]              # onderdeelnaam -> voorkeur
    keuzes: dict[str, str] = field(default_factory=lambda: dict(VOORKEUREN))


def atleet_voorkeuren(db: Opslag, master_id: str) -> AtleetVoorkeuren | None:
    a = db.atleet(master_id)
    if a is None:
        return None
    groepen = _voorkeuren.onderdeelnamen()
    gekozen = db.atleet_voorkeuren(master_id)
    bekend = {normaliseer(n) for namen in groepen.values() for n in namen}
    los = [n for n in gekozen if normaliseer(n) not in bekend]        # niet meer in een regelbestand
    if los:
        groepen = {**groepen, "Overig": sorted({*groepen.get("Overig", []), *los})}
    # gekozen op de getoonde naam (hoofdletters/spaties uit een ander bestand mogen verschillen)
    per_norm = {normaliseer(n): v for n, v in gekozen.items()}
    gekozen = {n: per_norm[normaliseer(n)] for namen in groepen.values() for n in namen if normaliseer(n) in per_norm}
    return AtleetVoorkeuren(a, groepen, gekozen)


def atleet_voorkeuren_opslaan(db: Opslag, master_id: str, form: Mapping) -> int:
    av = atleet_voorkeuren(db, master_id)
    if av is None:
        raise OpslagFout("Deze atleet bestaat niet (meer).")
    gelezen = _voorkeuren.lees_atleetformulier(form, [n for namen in av.groepen.values() for n in namen])
    db.atleet_voorkeuren_opslaan(master_id, gelezen)
    return len(gelezen)
