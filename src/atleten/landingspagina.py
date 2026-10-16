"""Gegevens voor de landingspagina van één atleet (de eerste pagina die je ziet
als je een atleet aanklikt).

Opbouw volgens de schets:

    Atleet [naam]                    [specialisatie]
    Trainingsschema  ma di wo do vr za zo   (+ gekoppelde groepstrainingen)
    Opmerkingen [blessures]          Wedstrijden / doelen [planning]
    daaronder: PR's, testen (uit profiel.py) en de stand op de leerdoelen

Bouwt voort op `profiel.profiel()`; deze module voegt alleen toe wat de
landingspagina extra nodig heeft. Geen SQL: alles via `Opslag`.
De UI krijgt kant-en-klare tekst (bijv. '12,93') en hoeft niets te weten van
eenheden, pseudoniemen of losse databases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from db.queries import Opslag
from leerlijnen.voortgang import LeerlijnBlok, samenvatting
from models import DAGEN, Atleet, Notitie, Trainingsschema, Wedstrijd

from .aanwezigheid import aanwezigheid
from .prestaties import toon_waarde
from .profiel import AtleetProfiel, profiel

DAG_KORT: dict[str, str] = {
    "maandag": "Ma", "dinsdag": "Di", "woensdag": "Wo", "donderdag": "Do",
    "vrijdag": "Vr", "zaterdag": "Za", "zondag": "Zo",
}


def leeftijdscategorie(atleet: Atleet, peildatum: date) -> str | None:
    """Atletiekcategorie (U10 … U20, 'Senior') voor het kalenderjaar van de peildatum.

    Telt met de leeftijd die de atleet dít jaar bereikt, zoals de Atletiekunie:
    wie dit jaar 14 of 15 wordt, is U16. Zonder geboortedatum: None.
    """
    if atleet.geboortejaar is None:
        return None
    leeftijd_dit_jaar = peildatum.year - atleet.geboortejaar
    if leeftijd_dit_jaar >= 20:
        return "Senior"
    return f"U{max(leeftijd_dit_jaar // 2 * 2 + 2, 8)}"


@dataclass
class SchemaDag:
    """Eén kolom van het trainingsschema."""
    dag: str                          # 'maandag'
    kort: str                         # 'Ma'
    traint: bool
    vandaag: bool = False
    gekoppeld: list[str] = field(default_factory=list)   # groepstrainingen deze week, bijv. 'U16 – Sprint'


@dataclass
class Blessuremelding:
    """Een training waarop de atleet als 'blessure' is gemeld. Alleen de korte reden, geen diagnose."""
    datum: date
    reden: str | None


@dataclass
class WedstrijdPlanning:
    wedstrijd: Wedstrijd
    onderdelen: list[str]             # [] = gaat mee, onderdelen volgen later
    dagen_tot: int


@dataclass
class PRTekst:
    onderdeel: str
    categorie: str | None
    waarde: str                       # al opgemaakt: '12,93', '4,80 m'


@dataclass
class AtleetLandingspagina:
    profiel: AtleetProfiel
    categorie: str | None
    schema: list[SchemaDag]
    trainingen_per_week: int
    notities: list[Notitie]
    aantal_notities: int
    blessures: list[Blessuremelding]
    wedstrijden: list[WedstrijdPlanning]
    prs: list[PRTekst]
    leerdoelen: list[LeerlijnBlok] = field(default_factory=list)   # stand per leerlijn (leerdoelscores.db)
    aanwezig_pct: float | None = None   # aanwezig op ingevulde trainingen, laatste 12 weken

    @property
    def atleet(self) -> Atleet:
        return self.profiel.atleet

    @property
    def categorie_code(self) -> str | None:
        """Bijv. 'U16V'."""
        return categorie_code(self.categorie, self.atleet.geslacht)

    @property
    def categorie_groep(self) -> str | None:
        return categorie_groep(self.categorie, self.atleet.geslacht)

    @property
    def geslacht(self) -> str | None:
        """'Meisje', 'Jongen', 'Vrouw', 'Man' of 'X'."""
        return geslacht_tekst(self.atleet.geslacht, self.categorie)

    @property
    def fase(self) -> str | None:
        """Fase uit de leerlijn: pupillen BMO, U14/U16 wedstrijdgericht, daarna specialisatie."""
        return fase_van(self.categorie)


FASES: tuple[str, ...] = ("BMO", "Wedstrijdgericht", "Specialisatie")

_GESLACHT_JEUGD = {"M": "Jongen", "V": "Meisje", "X": "X"}
_GESLACHT_SENIOR = {"M": "Man", "V": "Vrouw", "X": "X"}
_GROEP_JEUGD = {"M": "jongens", "V": "meisjes"}
_GROEP_SENIOR = {"M": "mannen", "V": "vrouwen"}
#: Vanaf deze categorieën heet het mannen/vrouwen in plaats van jongens/meisjes.
VOLWASSEN = ("U18", "U20", "Senior")


def categorie_code(categorie: str | None, geslacht: str | None) -> str | None:
    """Categorie met geslacht: ('U16', 'V') -> 'U16V', ('Senior', 'M') -> 'SenM'.

    Bij geslacht X of onbekend alleen de categorie ('U16', 'Senior').
    """
    if categorie is None:
        return None
    if geslacht not in ("M", "V"):
        return categorie
    return f"{'Sen' if categorie == 'Senior' else categorie}{geslacht}"


def geslacht_tekst(geslacht: str | None, categorie: str | None) -> str | None:
    """'Meisje' / 'Jongen' t/m U16, 'Vrouw' / 'Man' vanaf U18 (en zonder bekende leeftijd), 'X'."""
    if geslacht is None:
        return None
    jeugd = categorie is not None and categorie not in VOLWASSEN
    return (_GESLACHT_JEUGD if jeugd else _GESLACHT_SENIOR)[geslacht]


def categorie_groep(categorie: str | None, geslacht: str | None) -> str | None:
    """Groep onder de code: 'meisjes'/'jongens' t/m U16, 'vrouwen'/'mannen' vanaf U18 (None bij X/onbekend)."""
    if categorie is None or geslacht not in ("M", "V"):
        return None
    return (_GROEP_SENIOR if categorie in VOLWASSEN else _GROEP_JEUGD)[geslacht]


def fase_van(categorie: str | None) -> str | None:
    if categorie is None:
        return None
    if categorie in ("U8", "U10", "U12"):
        return "BMO"
    if categorie in ("U14", "U16"):
        return "Wedstrijdgericht"
    return "Specialisatie"


def _schema(db: Opslag, master_id: str, schema: Trainingsschema, vandaag: date) -> list[SchemaDag]:
    """Trainingsdagen plus de groepstrainingen van deze week (maandag t/m zondag)."""
    maandag = vandaag - timedelta(days=vandaag.weekday())
    zondag = maandag + timedelta(days=6)
    gekoppeld: dict[str, list[str]] = {d: [] for d in DAGEN}
    for g in db.groepen_van_atleet(master_id):
        for t in db.trainingen(g.id, van=maandag, tot=zondag):
            tekst = f"{g.naam} – {t.onderwerp}" if t.onderwerp else g.naam
            gekoppeld[DAGEN[t.datum.weekday()]].append(tekst)
    return [
        SchemaDag(d, DAG_KORT[d], schema.traint_op(d), vandaag.weekday() == i, gekoppeld[d])
        for i, d in enumerate(DAGEN)
    ]


def _blessures(db: Opslag, master_id: str, vanaf: date) -> list[Blessuremelding]:
    uit = []
    for a in db.absenties_van_atleet(master_id):
        if a.status != "blessure":
            continue
        t = db.training(a.training_id)
        if t is not None and t.datum >= vanaf:
            uit.append(Blessuremelding(t.datum, a.reden))
    return sorted(uit, key=lambda b: b.datum, reverse=True)


def _wedstrijden(db: Opslag, master_id: str, vandaag: date) -> list[WedstrijdPlanning]:
    namen = {o.id: o.naam for o in db.onderdelen()}
    per_wedstrijd: dict[int, list[str]] = {}
    for i in db.inschrijvingen(master_id):
        lijst = per_wedstrijd.setdefault(i.wedstrijd_id, [])
        if i.onderdeel_id is not None:
            lijst.append(namen[i.onderdeel_id])
    uit = []
    for wid, onderdelen in per_wedstrijd.items():
        w = db.wedstrijd(wid)
        if w is not None and w.datum >= vandaag:
            uit.append(WedstrijdPlanning(w, sorted(onderdelen), (w.datum - vandaag).days))
    return sorted(uit, key=lambda p: (p.wedstrijd.datum, p.wedstrijd.naam))


def landingspagina(db: Opslag, master_id: str, *, peildatum: date | None = None,
                   aantal_notities: int = 5, blessure_weken: int = 8) -> AtleetLandingspagina | None:
    """Alles voor de landingspagina van één atleet, of None als de atleet niet bestaat.

    aantal_notities: zoveel recente opmerkingen tonen (de rest via 'alle notities').
    blessure_weken:  blessuremeldingen van zoveel weken terug tonen.
    """
    vandaag = peildatum or date.today()
    p = profiel(db, master_id, peildatum=vandaag)
    if p is None:
        return None
    schema = db.trainingsschema(master_id)
    notities = db.notities(master_id)
    categorie = leeftijdscategorie(p.atleet, vandaag)
    return AtleetLandingspagina(
        profiel=p,
        categorie=categorie,
        schema=_schema(db, master_id, schema, vandaag),
        trainingen_per_week=schema.aantal_per_week,
        notities=notities[:aantal_notities],
        aantal_notities=len(notities),
        blessures=_blessures(db, master_id, vandaag - timedelta(weeks=blessure_weken)),
        wedstrijden=_wedstrijden(db, master_id, vandaag),
        prs=[PRTekst(r.onderdeel.naam, r.onderdeel.categorie, toon_waarde(r.waarde, r.onderdeel.eenheid))
             for r in p.prs],
        leerdoelen=samenvatting(db, master_id, categorie),
        aanwezig_pct=aanwezigheid(db, master_id, peildatum=vandaag).percentage,
    )
