"""Gegevens voor de landingspagina van één groep (de eerste pagina die je ziet
als je een groep aanklikt).

Opbouw:

    Groep [naam]                         [aantal atleten]
    Trainingsdagen   ma di wo do vr za zo   (+ hoeveel atleten die dag)
    Atleten: naam, categorie, specialisatie en per weekdag of de atleet traint:
             met deze groep, of ergens anders (andere groep of zelf)
    Komende wedstrijden              Komende trainingen
    Leerdoelen (gemiddeld)           Aanwezigheid per trainingsdag
    daaronder een link naar het overzicht met PR's en testresultaten

Trainingsdagen van een groep staan (nog) niet als vast gegeven in de database.
Ze worden afgeleid uit de trainingen van de groep rond vandaag; heeft de groep
nog geen trainingen, dan uit de trainingsschema's van de leden (dagen waarop
minstens de helft van de leden traint).

Geen SQL: alles via `Opslag`. De UI krijgt kant-en-klare gegevens.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from atleten.landingspagina import DAG_KORT, categorie_code, leeftijdscategorie
from db.queries import Opslag
from leerlijnen.voortgang import leerdoelenpagina
from models import ABSENTIE_STATUSSEN, DAGEN, Atleet, Groep, Periodeplan, Training, Trainingsschema
from wedstrijden.kalender import PlanningRegel, wedstrijdplanning

#: Waar de trainingsdagen vandaan komen.
BRON_TRAININGEN = "trainingen"
BRON_SCHEMA = "schema"

#: Soorten cel in de dagenkolommen van de atletenlijst.
MET_GROEP = "groep"
ELDERS = "elders"


# ============================================================
# Gegevens voor het template
# ============================================================
@dataclass
class GroepDag:
    """Eén kolom van het weekoverzicht van de groep."""
    dag: str                          # 'dinsdag'
    kort: str                         # 'Di'
    groep_traint: bool
    vandaag: bool = False
    aantal_atleten: int = 0           # leden die volgens hun schema die dag (met de groep) trainen


@dataclass
class LidDag:
    """Eén cel in de atletenlijst: traint de atleet die dag, en zo ja waar."""
    soort: str | None                 # MET_GROEP, ELDERS of None (traint niet)
    andere_groepen: list[str] = field(default_factory=list)   # bij ELDERS: groepen die dan trainen

    @property
    def uitleg(self) -> str:
        if self.soort == MET_GROEP:
            return "traint met de groep"
        if self.soort == ELDERS:
            return "traint elders" + (f" ({', '.join(self.andere_groepen)})" if self.andere_groepen else "")
        return "traint niet"


@dataclass
class GroepLid:
    atleet: Atleet
    categorie: str | None             # 'U16'
    dagen: list[LidDag]               # maandag t/m zondag

    @property
    def categorie_code(self) -> str | None:
        return categorie_code(self.categorie, self.atleet.geslacht)

    @property
    def met_groep(self) -> int:
        return sum(1 for d in self.dagen if d.soort == MET_GROEP)

    @property
    def elders(self) -> int:
        return sum(1 for d in self.dagen if d.soort == ELDERS)


@dataclass
class KomendeTraining:
    training: Training
    dagen_tot: int
    verwacht: int                     # leden die die weekdag volgens hun schema trainen
    periode: str | None = None        # naam van het periodeplan
    ingevuld: int = 0                 # al opgeslagen statussen (aanwezigheid)

    @property
    def geweest(self) -> bool:
        """Training van de afgelopen week waarvan de aanwezigheid nog niet is ingevuld."""
        return self.dagen_tot < 0


@dataclass
class LeerlijnGemiddelde:
    """Stand van de groep op één leerlijn: het gemiddelde over de beoordeelde atleten."""
    code: str                         # 'SPR'
    naam: str                         # 'Sprint'
    gemiddelde_score: float           # gemiddelde score 1-5
    zelfstandig_pct: float            # gemiddeld aandeel leerdoelen op 'zelfstandig' of hoger (0-100)
    beoordeeld: int                   # atleten met minstens één score op deze leerlijn


@dataclass
class DagAanwezigheid:
    """Aanwezigheid op één weekdag, over de trainingen van de groep in de periode."""
    dag: str
    kort: str
    trainingen: int                   # trainingen op deze weekdag in de periode
    ingevulde_trainingen: int         # waarvan de absentie (deels) is ingevuld
    telling: dict[str, int]           # per status, opgeteld over de trainingen

    @property
    def ingevuld(self) -> int:
        return sum(self.telling.values())

    @property
    def percentage(self) -> float | None:
        """Aanwezig als percentage van de ingevulde statussen; None als er niets is ingevuld."""
        return round(100 * self.telling["aanwezig"] / self.ingevuld, 1) if self.ingevuld else None

    @property
    def gemiddeld_aanwezig(self) -> float | None:
        """Gemiddeld aantal aanwezigen per ingevulde training."""
        return self.telling["aanwezig"] / self.ingevulde_trainingen if self.ingevulde_trainingen else None


@dataclass
class GroepLandingspagina:
    groep: Groep
    dagen: list[GroepDag]
    dagen_bron: str | None            # BRON_TRAININGEN, BRON_SCHEMA of None (niets bekend)
    leden: list[GroepLid]
    wedstrijden: list[PlanningRegel]  # komende wedstrijden met minstens één lid
    aantal_wedstrijden: int           # alle komende (de lijst kan ingekort zijn)
    trainingen: list[KomendeTraining]   # eerst niet-ingevulde van de afgelopen week, dan de komende
    leerdoelen: list[LeerlijnGemiddelde]
    aanwezigheid: list[DagAanwezigheid]
    aanwezigheid_van: date
    periode: Periodeplan | None = None   # het periodeplan waar vandaag in valt
    vandaag: date = field(default_factory=date.today)

    @property
    def trainingsdagen(self) -> list[GroepDag]:
        return [d for d in self.dagen if d.groep_traint]

    @property
    def categorieen(self) -> list[str]:
        """De categorieën in de groep, jong naar oud: ['U14', 'U16']."""
        volgorde = ["U8", "U10", "U12", "U14", "U16", "U18", "U20", "Senior"]
        aanwezig = {l.categorie for l in self.leden if l.categorie}
        return [c for c in volgorde if c in aanwezig]

    @property
    def leerdoelen_beoordeeld(self) -> int:
        return max((b.beoordeeld for b in self.leerdoelen), default=0)

    @property
    def aanwezig_pct(self) -> float | None:
        """Aanwezig over alle trainingsdagen samen."""
        aanwezig = sum(d.telling["aanwezig"] for d in self.aanwezigheid)
        ingevuld = sum(d.ingevuld for d in self.aanwezigheid)
        return round(100 * aanwezig / ingevuld, 1) if ingevuld else None

    @property
    def periode_week(self) -> int | None:
        """In welke week van het huidige periodeplan we zitten (1 = eerste week)."""
        if self.periode is None:
            return None
        return (self.vandaag - self.periode.startdatum).days // 7 + 1


# ============================================================
# Trainingsdagen
# ============================================================
def trainingsdagen(db: Opslag, groep: Groep, vandaag: date, *, weken_terug: int = 8,
                   weken_vooruit: int = 4, schemas: dict[str, Trainingsschema] | None = None,
                   ) -> tuple[set[str], str | None]:
    """De weekdagen waarop de groep traint, en waar dat uit is afgeleid.

    1. De weekdagen van de trainingen van de groep van `weken_terug` weken terug
       tot `weken_vooruit` weken vooruit.
    2. Geen trainingen: de dagen waarop minstens de helft van de leden traint
       volgens het trainingsschema.
    Geeft (dagen, BRON_TRAININGEN | BRON_SCHEMA | None).
    """
    trainingen = db.trainingen(groep.id, van=vandaag - timedelta(weeks=weken_terug),
                               tot=vandaag + timedelta(weeks=weken_vooruit))
    if trainingen:
        return {DAGEN[t.datum.weekday()] for t in trainingen}, BRON_TRAININGEN
    if not groep.leden:
        return set(), None
    schemas = schemas or {m: db.trainingsschema(m) for m in groep.leden}
    telling = Counter(d for s in schemas.values() for d in s.dagen)
    drempel = max(1, (len(groep.leden) + 1) // 2)
    dagen = {d for d, n in telling.items() if n >= drempel}
    return dagen, (BRON_SCHEMA if dagen else None)


def _leden(db: Opslag, groep: Groep, groepsdagen: set[str], schemas: dict[str, Trainingsschema],
           vandaag: date) -> list[GroepLid]:
    """Per lid de categorie en per weekdag: met de groep, elders of niet."""
    andere_dagen: dict[int, tuple[str, set[str]]] = {}     # groep_id -> (naam, dagen); één keer per groep

    def dagen_van(g: Groep) -> set[str]:
        if g.id not in andere_dagen:
            andere_dagen[g.id] = (g.naam, trainingsdagen(db, g, vandaag)[0])
        return andere_dagen[g.id][1]

    uit = []
    for mid in groep.leden:
        a = db.atleet(mid)
        if a is None:
            continue
        schema = schemas[mid]
        anderen = [g for g in db.groepen_van_atleet(mid) if g.id != groep.id]
        dagen = []
        for d in DAGEN:
            if not schema.traint_op(d):
                dagen.append(LidDag(None))
            elif d in groepsdagen:
                dagen.append(LidDag(MET_GROEP))
            else:
                dagen.append(LidDag(ELDERS, [g.naam for g in anderen if d in dagen_van(g)]))
        uit.append(GroepLid(a, leeftijdscategorie(a, vandaag), dagen))
    return uit


# ============================================================
# Komend: wedstrijden en trainingen
# ============================================================
def _trainingen(db: Opslag, groep: Groep, schemas: dict[str, Trainingsschema], vandaag: date,
                weken: int, aantal: int, dagen_terug: int = 7) -> list[KomendeTraining]:
    """De komende trainingen (max. `aantal`), met daarvoor de trainingen van de afgelopen
    `dagen_terug` dagen waarvan de aanwezigheid nog helemaal niet is ingevuld."""
    plannen = {p.id: p.naam for p in db.periodeplannen(groep.id)}
    open_trainingen = [t for t in db.trainingen(groep.id, van=vandaag - timedelta(days=dagen_terug),
                                                tot=vandaag - timedelta(days=1))
                       if not db.absenties(t.id)]
    komend = db.trainingen(groep.id, van=vandaag, tot=vandaag + timedelta(weeks=weken))[:aantal]
    uit = []
    for t in open_trainingen + komend:
        verwacht = sum(1 for s in schemas.values() if s.traint_op(t.datum))
        uit.append(KomendeTraining(t, (t.datum - vandaag).days, verwacht, plannen.get(t.periodeplan_id),
                                   len(db.absenties(t.id))))
    return uit


# ============================================================
# Leerdoelen: gemiddelde over de atleten
# ============================================================
def _leerdoelen(db: Opslag, leden: list[GroepLid]) -> list[LeerlijnGemiddelde]:
    """Per leerlijn het gemiddelde over de atleten die erop beoordeeld zijn.

    Elke atleet telt met de leerdoelen van zijn eigen categorie, zodat een
    groep met U14 en U16 samen toch één zinnig getal geeft.
    """
    scores: dict[str, list[float]] = {}
    aandelen: dict[str, list[float]] = {}
    for lid in leden:
        p = leerdoelenpagina(db, lid.atleet.master_id, lid.categorie)
        if p is None:
            continue
        for b in p.leerlijnen:
            if not b.beoordeeld:
                continue
            scores.setdefault(b.code, []).append(b.gemiddelde)
            aandelen.setdefault(b.code, []).append(100 * b.zelfstandig / b.aantal)
    uit = []
    for code, naam in db.leerdoel_leerlijnen():                # vaste volgorde van de leerlijnen
        if code in scores:
            s, a = scores[code], aandelen[code]
            uit.append(LeerlijnGemiddelde(code, naam, round(sum(s) / len(s), 1), round(sum(a) / len(a), 1), len(s)))
    return uit


# ============================================================
# Aanwezigheid per trainingsdag
# ============================================================
def _aanwezigheid(db: Opslag, groep: Groep, van: date, tot: date) -> list[DagAanwezigheid]:
    """Per weekdag met trainingen: de opgetelde statussen van de trainingen tussen van en tot."""
    per_dag: dict[str, DagAanwezigheid] = {}
    for t in db.trainingen(groep.id, van=van, tot=tot):
        d = DAGEN[t.datum.weekday()]
        regel = per_dag.setdefault(d, DagAanwezigheid(d, DAG_KORT[d], 0, 0, {s: 0 for s in ABSENTIE_STATUSSEN}))
        regel.trainingen += 1
        statussen = db.absenties(t.id)
        if statussen:
            regel.ingevulde_trainingen += 1
        for a in statussen:
            regel.telling[a.status] += 1
    return [per_dag[d] for d in DAGEN if d in per_dag]


# ============================================================
# Alles bij elkaar
# ============================================================
def landingspagina(db: Opslag, groep_id: int, *, peildatum: date | None = None,
                   aantal_wedstrijden: int = 5, aantal_trainingen: int = 6,
                   weken_trainingen: int = 4, weken_aanwezigheid: int = 12) -> GroepLandingspagina | None:
    """Alles voor de landingspagina van één groep, of None als de groep niet bestaat.

    aantal_wedstrijden / aantal_trainingen: zoveel komende tonen.
    weken_trainingen:   trainingen tot zoveel weken vooruit.
    weken_aanwezigheid: aanwezigheid over zoveel weken terug (t/m vandaag).
    """
    groep = db.groep(groep_id)
    if groep is None:
        return None
    vandaag = peildatum or date.today()
    schemas = {m: db.trainingsschema(m) for m in groep.leden}
    groepsdagen, bron = trainingsdagen(db, groep, vandaag, schemas=schemas)

    dagen = [GroepDag(d, DAG_KORT[d], d in groepsdagen, vandaag.weekday() == i,
                      sum(1 for s in schemas.values() if s.traint_op(d)) if d in groepsdagen else 0)
             for i, d in enumerate(DAGEN)]
    leden = _leden(db, groep, groepsdagen, schemas, vandaag)

    komend = wedstrijdplanning(db, groep.leden, van=vandaag, peildatum=vandaag).komend if groep.leden else []
    van_aanwezigheid = vandaag - timedelta(weeks=weken_aanwezigheid)
    periode = next((p for p in db.periodeplannen(groep.id) if p.bevat(vandaag)), None)

    return GroepLandingspagina(
        groep=groep,
        dagen=dagen,
        dagen_bron=bron,
        leden=leden,
        wedstrijden=komend[:aantal_wedstrijden],
        aantal_wedstrijden=len(komend),
        trainingen=_trainingen(db, groep, schemas, vandaag, weken_trainingen, aantal_trainingen),
        leerdoelen=_leerdoelen(db, leden),
        aanwezigheid=_aanwezigheid(db, groep, van_aanwezigheid, vandaag),
        aanwezigheid_van=van_aanwezigheid,
        periode=periode,
        vandaag=vandaag,
    )


def overzicht(db: Opslag, *, peildatum: date | None = None) -> list[tuple[Groep, list[str]]]:
    """Alle groepen met hun trainingsdagen (korte namen), voor de pagina 'Groepen'."""
    vandaag = peildatum or date.today()
    uit = []
    for g in db.groepen():
        dagen, _ = trainingsdagen(db, g, vandaag)
        uit.append((g, [DAG_KORT[d] for d in DAGEN if d in dagen]))
    return uit
