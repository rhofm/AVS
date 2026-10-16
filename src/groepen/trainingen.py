"""Trainingen van een groep: de lijst, één training, en de aanwezigheid invullen.

Pagina's:
  * alle trainingen van een groep (komend en geweest), met per training de stand
    van de aanwezigheid en een link om die in te vullen;
  * één training: datum, onderwerp, warming-up, kern A, kern B, cooling-down,
    notities, afwijkende trainingen voor enkele atleten, periodeplan en wie er was;
  * aanwezigheid invullen: één regel per atleet, vooraf ingevuld volgens
    `groepen.absentie.absentielijst()` (opgeslagen status gaat voor, anders
    'aanwezig' als de atleet die dag volgens zijn schema traint).

Opslaan bewaart elke gekozen status expliciet, ook 'aanwezig' (geen rij =
'nog niet ingevuld'). 'blessure' is gezondheidsinformatie: de reden blijft kort
en feitelijk, geen diagnose. Geen SQL: alles via `Opslag`.

Trainingen automatisch aanmaken
-------------------------------
Heeft een groep vaste trainingsdagen (`Groep.trainingsdagen`), dan maakt
`trainingen_aanvullen()` voor elke trainingsdag een training aan, van vandaag
tot `WEKEN_VOORUIT` weken vooruit. Is de app een tijd niet geopend, dan worden
gemiste trainingen tot `MAX_DAGEN_TERUG` dagen terug alsnog aangemaakt, maar
nooit vóór de eerste training van de groep (een nieuwe groep begint vandaag).
Er komt nooit een tweede training op dezelfde datum, en bestaande trainingen
worden niet aangepast. `trainingen_opruimen()` haalt na het wijzigen van de
dagen de toekomstige trainingen weg op dagen die niet meer gelden, maar alleen
als ze nog leeg zijn (geen onderwerp, notities, onderdelen, periodeplan,
afwijkende varianten of aanwezigheid).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Mapping

from atleten.aanwezigheid import NIET_INGEVULD, STATUS_TEKST
from atleten.landingspagina import categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
from models import ABSENTIE_STATUSSEN, DAGEN, TRAININGSONDERDELEN, Absentie, Atleet, Groep, Periodeplan, Training

from .absentie import absentielijst

STATUS_VELD = "status-"
REDEN_VELD = "reden-"
MAX_REDEN = 80                        # kort en feitelijk
WEKEN_VOORUIT = 4                     # zo ver vooruit worden trainingen automatisch aangemaakt
MAX_DAGEN_TERUG = 14                  # gemiste trainingen tot zo ver terug alsnog aanmaken


# ============================================================
# Trainingen automatisch aanmaken voor de vaste trainingsdagen
# ============================================================
def trainingen_aanvullen(db: Opslag, groep: Groep, *, peildatum: date | None = None,
                         weken_vooruit: int = WEKEN_VOORUIT) -> list[Training]:
    """Maak de ontbrekende trainingen aan op de vaste trainingsdagen van de groep. Geeft de nieuwe.

    Van vandaag tot `weken_vooruit` weken vooruit; heeft de groep al eerdere
    trainingen, dan ook gemiste dagen tot MAX_DAGEN_TERUG terug (niet vóór de
    eerste training). Zonder vaste dagen gebeurt er niets.
    """
    if groep.id is None or not groep.trainingsdagen:
        return []
    vandaag = peildatum or date.today()
    bestaand = db.trainingen(groep.id)
    datums = {t.datum for t in bestaand}
    eerdere = [t.datum for t in bestaand if t.datum < vandaag]
    begin = max(vandaag - timedelta(days=MAX_DAGEN_TERUG), min(eerdere)) if eerdere else vandaag
    eind = vandaag + timedelta(weeks=weken_vooruit)
    nieuw = []
    dag = begin
    while dag <= eind:
        if DAGEN[dag.weekday()] in groep.trainingsdagen and dag not in datums:
            nieuw.append(db.training_opslaan(Training(groep.id, dag)))
        dag += timedelta(days=1)
    return nieuw


def trainingen_opruimen(db: Opslag, groep: Groep, *, peildatum: date | None = None) -> list[Training]:
    """Na het wijzigen van de vaste dagen: lege toekomstige trainingen op dagen die niet meer gelden weghalen.

    Alleen trainingen vanaf vandaag waarin niets is ingevuld (zie _leeg); al het
    andere blijft staan. Zonder vaste dagen gebeurt er niets.
    """
    if groep.id is None or not groep.trainingsdagen:
        return []
    weg = [t for t in db.trainingen(groep.id, van=peildatum or date.today())
           if DAGEN[t.datum.weekday()] not in groep.trainingsdagen and _leeg(db, t)]
    for t in weg:
        db.training_verwijderen(t.id)
    return weg


def _leeg(db: Opslag, t: Training) -> bool:
    """Niets ingevuld: geen onderwerp, notities of onderdelen (warming-up … cooling-down),
    geen periodeplan, geen afwijkende varianten en geen aanwezigheid."""
    return (not t.onderwerp and not t.notities and not t.onderdelen and t.periodeplan_id is None
            and not db.varianten(t.id) and not db.absenties(t.id))


def alle_trainingen_aanvullen(db: Opslag, groepen: Iterable[Groep] | None = None, *,
                              peildatum: date | None = None) -> int:
    """trainingen_aanvullen() voor alle groepen (of de opgegeven). Geeft het aantal nieuwe trainingen."""
    return sum(len(trainingen_aanvullen(db, g, peildatum=peildatum))
               for g in (db.groepen() if groepen is None else groepen))


# ============================================================
# Stand van de aanwezigheid op één training
# ============================================================
@dataclass
class Stand:
    telling: dict[str, int]           # per status (ABSENTIE_STATUSSEN)
    verwacht: int                     # leden die die dag volgens hun schema trainen

    @property
    def ingevuld(self) -> int:
        return sum(self.telling.values())

    @property
    def aanwezig(self) -> int:
        return self.telling["aanwezig"]


def _stand(db: Opslag, groep: Groep, t: Training) -> Stand:
    c = Counter(a.status for a in db.absenties(t.id))
    verwacht = sum(1 for m in groep.leden if db.trainingsschema(m).traint_op(t.datum))
    return Stand({s: c.get(s, 0) for s in ABSENTIE_STATUSSEN}, verwacht)


# ============================================================
# Lijst met trainingen
# ============================================================
@dataclass
class TrainingRegel:
    training: Training
    dagen_tot: int                    # negatief = geweest
    periode: str | None
    stand: Stand

    @property
    def geweest(self) -> bool:
        return self.dagen_tot < 0


@dataclass
class Trainingenlijst:
    groep: Groep
    komend: list[TrainingRegel]       # vandaag en later, eerstvolgende eerst
    geweest: list[TrainingRegel]      # nieuwste eerst

    @property
    def nog_invullen(self) -> int:
        """Trainingen tot en met vandaag zonder één ingevulde status."""
        vandaag = [r for r in self.komend if r.dagen_tot == 0]
        return sum(1 for r in self.geweest + vandaag if r.stand.ingevuld == 0)


def trainingenlijst(db: Opslag, groep: Groep, *, peildatum: date | None = None) -> Trainingenlijst:
    vandaag = peildatum or date.today()
    plannen = {p.id: p.naam for p in db.periodeplannen(groep.id)}
    regels = [TrainingRegel(t, (t.datum - vandaag).days, plannen.get(t.periodeplan_id), _stand(db, groep, t))
              for t in db.trainingen(groep.id)]
    return Trainingenlijst(groep, [r for r in regels if not r.geweest],
                           sorted((r for r in regels if r.geweest), key=lambda r: r.training.datum, reverse=True))


# ============================================================
# Eén training
# ============================================================
@dataclass
class Deelnemer:
    atleet: Atleet
    status: str                       # een van ABSENTIE_STATUSSEN of NIET_INGEVULD
    reden: str | None = None
    verwacht: bool = False            # training ligt nog in de toekomst: 'niet ingevuld' heet dan 'verwacht'

    @property
    def status_tekst(self) -> str:
        return "Verwacht" if self.verwacht and self.status == NIET_INGEVULD else STATUS_TEKST[self.status]


@dataclass
class TrainingPagina:
    training: Training
    groep: Groep
    periode: Periodeplan | None
    dagen_tot: int
    deelnemers: list[Deelnemer]       # opgeslagen statussen + ingeroosterd maar niet ingevuld
    stand: Stand
    vorige: Training | None
    volgende: Training | None
    varianten: list[tuple[Training, list[Atleet]]] = field(default_factory=list)   # afwijkend: (training, atleten)

    @property
    def starttijd(self) -> str | None:
        """Begintijd uit de vaste trainingsdagen van de groep ('18:30'), als die er is."""
        return self.groep.trainingsdagen.get(DAGEN[self.training.datum.weekday()])

    @property
    def telling(self) -> dict[str, int]:
        c = Counter(d.status for d in self.deelnemers)
        return {s: c.get(s, 0) for s in (*ABSENTIE_STATUSSEN, NIET_INGEVULD)}


def trainingpagina(db: Opslag, training_id: int, *, peildatum: date | None = None) -> TrainingPagina | None:
    t = db.training(training_id)
    if t is None:
        return None
    if t.is_afwijkend:                      # een variant toont de pagina van de gewone training
        t = db.training(t.hoofdtraining_id)
    groep = db.groep(t.groep_id)
    vandaag = peildatum or date.today()
    opgeslagen = {a.atleet_id: a for a in db.absenties(t.id)}
    deelnemers = []
    for mid in [*groep.leden, *(m for m in opgeslagen if m not in groep.leden)]:
        a = db.atleet(mid)
        if a is None:
            continue
        if mid in opgeslagen:
            deelnemers.append(Deelnemer(a, opgeslagen[mid].status, opgeslagen[mid].reden))
        elif db.trainingsschema(mid).traint_op(t.datum):
            deelnemers.append(Deelnemer(a, NIET_INGEVULD, verwacht=t.datum > vandaag))
    alle = db.trainingen(groep.id)
    i = next(n for n, x in enumerate(alle) if x.id == t.id)
    periode = next((p for p in db.periodeplannen(groep.id) if p.id == t.periodeplan_id), None)
    varianten = [(v, [a for a in (db.atleet(m) for m in v.atleten) if a is not None]) for v in db.varianten(t.id)]
    return TrainingPagina(t, groep, periode, (t.datum - vandaag).days, deelnemers, _stand(db, groep, t),
                          alle[i - 1] if i > 0 else None, alle[i + 1] if i + 1 < len(alle) else None, varianten)


# ============================================================
# Training bewerken: onderdelen en afwijkende trainingen (varianten)
# ============================================================
#: Velden van het bewerkformulier, in volgorde: (veldnaam, titel, maximale lengte).
TEKSTVELDEN: tuple[tuple[str, str, int], ...] = (
    ("onderwerp", "Onderwerp", 120),
    *((veld, titel, 10_000) for veld, titel in TRAININGSONDERDELEN),
    ("notities", "Notities", 10_000),
)
ATLEET_VELD = "atleet"


@dataclass
class Keuzeatleet:
    """Een lid van de groep in de keuze 'voor wie is deze afwijkende training'."""
    atleet: Atleet
    gekozen: bool
    elders: str | None = None         # staat al in een andere variant (onderwerp of 'een andere afwijkende training')


@dataclass
class Bewerkformulier:
    hoofd: Training                   # de gewone training van die dag
    groep: Groep
    waarden: dict[str, str]           # veldnaam -> tekst zoals in het formulier
    variant: Training | None = None   # bestaande variant die bewerkt wordt
    is_variant: bool = False          # variant: bestaand of nieuw
    atleten: list[Keuzeatleet] = field(default_factory=list)

    @property
    def nieuw(self) -> bool:
        return self.is_variant and self.variant is None

    @property
    def starttijd(self) -> str | None:
        return self.groep.trainingsdagen.get(DAGEN[self.hoofd.datum.weekday()])

    @property
    def velden(self) -> list[tuple[str, str, int, str]]:
        """(veld, titel, maxlengte, waarde) voor het template."""
        return [(v, titel, n, self.waarden.get(v, "")) for v, titel, n in TEKSTVELDEN]


def _waarden(t: Training) -> dict[str, str]:
    return {v: getattr(t, v) or "" for v, _, _ in TEKSTVELDEN}


def _keuze(db: Opslag, groep: Groep, hoofd: Training, variant: Training | None,
           gekozen: Iterable[str]) -> list[Keuzeatleet]:
    gekozen = set(gekozen)
    elders = {m: (v.onderwerp or "een andere afwijkende training")
              for v in db.varianten(hoofd.id) if variant is None or v.id != variant.id for m in v.atleten}
    uit = []
    for mid in groep.leden:
        a = db.atleet(mid)
        if a is not None:
            uit.append(Keuzeatleet(a, mid in gekozen, elders.get(mid)))
    return uit


def bewerkformulier(db: Opslag, training_id: int, *, formulier: Mapping[str, str] | None = None,
                    gekozen: Iterable[str] | None = None) -> Bewerkformulier | None:
    """Formulier voor een gewone training of een bestaande variant. formulier/gekozen: opnieuw tonen na een fout."""
    t = db.training(training_id)
    if t is None:
        return None
    hoofd = db.training(t.hoofdtraining_id) if t.is_afwijkend else t
    groep = db.groep(hoofd.groep_id)
    waarden = {v: str(formulier.get(v, "")) for v, _, _ in TEKSTVELDEN} if formulier is not None else _waarden(t)
    if not t.is_afwijkend:
        return Bewerkformulier(hoofd, groep, waarden)
    keuze = _keuze(db, groep, hoofd, t, t.atleten if gekozen is None else gekozen)
    return Bewerkformulier(hoofd, groep, waarden, variant=t, is_variant=True, atleten=keuze)


def variantformulier(db: Opslag, hoofd_id: int, *, formulier: Mapping[str, str] | None = None,
                     gekozen: Iterable[str] = ()) -> Bewerkformulier | None:
    """Formulier voor een nieuwe afwijkende training, ingevuld met de gewone training als begin."""
    hoofd = db.training(hoofd_id)
    if hoofd is None or hoofd.is_afwijkend:
        return None
    groep = db.groep(hoofd.groep_id)
    if formulier is not None:
        waarden = {v: str(formulier.get(v, "")) for v, _, _ in TEKSTVELDEN}
    else:
        waarden = _waarden(hoofd)
        waarden["onderwerp"] = ""                     # een eigen naam, bijv. 'Revalidatie' of 'Meerkamp'
    return Bewerkformulier(hoofd, groep, waarden, is_variant=True,
                           atleten=_keuze(db, groep, hoofd, None, gekozen))


def _lees(formulier: Mapping[str, str]) -> dict[str, str | None]:
    uit = {}
    for veld, titel, maximaal in TEKSTVELDEN:
        tekst = str(formulier.get(veld, "") or "").replace("\r\n", "\n").strip()
        if len(tekst) > maximaal:
            raise OpslagFout(f"{titel} is te lang (maximaal {maximaal} tekens).")
        uit[veld] = tekst or None
    return uit


def training_bewerken(db: Opslag, training_id: int, formulier: Mapping[str, str],
                      gekozen: Iterable[str] | None = None) -> Training:
    """Sla de teksten van een gewone training of variant op; bij een variant ook de atleten (`gekozen`)."""
    t = db.training(training_id)
    if t is None:
        raise OpslagFout(f"Training {training_id} bestaat niet.")
    for veld, tekst in _lees(formulier).items():
        setattr(t, veld, tekst)
    if t.is_afwijkend:
        t.atleten = [m for m in (gekozen or []) if m]
    return db.training_opslaan(t)        # controleert varianten: groep, minstens één atleet, niet dubbel


def variant_toevoegen(db: Opslag, hoofd_id: int, formulier: Mapping[str, str], gekozen: Iterable[str]) -> Training:
    """Nieuwe afwijkende training bij een gewone training, voor de gekozen atleten."""
    hoofd = db.training(hoofd_id)
    if hoofd is None or hoofd.is_afwijkend:
        raise OpslagFout("Een afwijkende training hoort bij een gewone training.")
    velden = _lees(formulier)
    return db.training_opslaan(Training(hoofd.groep_id, hoofd.datum, hoofdtraining_id=hoofd.id,
                                        atleten=[m for m in gekozen if m], **velden))


def variant_verwijderen(db: Opslag, variant_id: int) -> Training:
    """Haal een afwijkende training weg (de atleten volgen dan weer de gewone). Geeft de gewone training."""
    v = db.training(variant_id)
    if v is None or not v.is_afwijkend:
        raise OpslagFout("Alleen een afwijkende training kan hier worden verwijderd.")
    db.training_verwijderen(v.id)
    return db.training(v.hoofdtraining_id)


# ============================================================
# Aanwezigheid invullen
# ============================================================
@dataclass
class InvulRegel:
    atleet: Atleet
    categorie: str | None
    status: str | None                # voorgestelde of opgeslagen status; None = niets kiezen
    reden: str | None
    ingeroosterd: bool                # traint die weekdag volgens zijn schema
    opgeslagen: bool                  # er staat al een status in de database
    lid: bool = True                  # False = niet (meer) in de groep, wel een opgeslagen status

    @property
    def categorie_code(self) -> str | None:
        return categorie_code(self.categorie, self.atleet.geslacht)

    @property
    def veld(self) -> str:
        return self.atleet.master_id


@dataclass
class Invulformulier:
    training: Training
    groep: Groep
    regels: list[InvulRegel]
    al_ingevuld: bool                 # er is al minstens één status opgeslagen

    @property
    def statussen(self) -> list[tuple[str, str]]:
        return [(s, STATUS_TEKST[s]) for s in ABSENTIE_STATUSSEN]


def invulformulier(db: Opslag, training_id: int, *, peildatum: date | None = None) -> Invulformulier | None:
    """Het formulier voor één training: alle leden, ingeroosterden voorgesteld als 'aanwezig'."""
    t = db.training(training_id)
    if t is None:
        return None
    groep = db.groep(t.groep_id)
    vandaag = peildatum or date.today()
    opgeslagen = {a.atleet_id for a in db.absenties(t.id)}
    voorstel = {a.atleet_id: a for a in absentielijst(db, t.id)}     # opgeslagen + ingeroosterd
    regels = []
    for mid in [*groep.leden, *(m for m in voorstel if m not in groep.leden)]:
        a = db.atleet(mid)
        if a is None:
            continue
        v = voorstel.get(mid)
        regels.append(InvulRegel(a, leeftijdscategorie(a, vandaag), v.status if v else None, v.reden if v else None,
                                 db.trainingsschema(mid).traint_op(t.datum), mid in opgeslagen, mid in groep.leden))
    return Invulformulier(t, groep, regels, bool(opgeslagen))


def aanwezigheid_opslaan(db: Opslag, training_id: int, formulier: Mapping[str, str]) -> int:
    """Verwerk het formulier. Geeft het aantal opgeslagen statussen.

    Velden: 'status-<master_id>' (aanwezig/afgemeld/afwezig/blessure of leeg) en
    'reden-<master_id>'. Alleen leden van de groep en atleten die al een status
    op deze training hebben tellen mee; een lege keuze slaat niets op.
    De reden wordt afgekapt op MAX_REDEN tekens en vervalt bij 'aanwezig'.
    """
    t = db.training(training_id)
    if t is None:
        raise OpslagFout(f"Training {training_id} bestaat niet.")
    groep = db.groep(t.groep_id)
    toegestaan = set(groep.leden) | {a.atleet_id for a in db.absenties(t.id)}
    nieuw = []
    for veld, waarde in formulier.items():
        if not veld.startswith(STATUS_VELD):
            continue
        mid = veld[len(STATUS_VELD):]
        status = str(waarde).strip()
        if mid not in toegestaan or not status:
            continue
        if status not in ABSENTIE_STATUSSEN:
            raise OpslagFout(f"Onbekende status {status!r}.")
        reden = " ".join(str(formulier.get(REDEN_VELD + mid, "")).split())[:MAX_REDEN] or None
        nieuw.append(Absentie(t.id, mid, status, None if status == "aanwezig" else reden))
    if nieuw:
        db.absenties_opslaan(nieuw)
    return len(nieuw)
