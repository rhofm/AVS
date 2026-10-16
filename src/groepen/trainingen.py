"""Trainingen van een groep: de lijst, één training, en de aanwezigheid invullen.

Pagina's:
  * alle trainingen van een groep (komend en geweest), met per training de stand
    van de aanwezigheid en een link om die in te vullen;
  * één training: datum, onderwerp, inhoud, periodeplan en wie er was;
  * aanwezigheid invullen: één regel per atleet, vooraf ingevuld volgens
    `groepen.absentie.absentielijst()` (opgeslagen status gaat voor, anders
    'aanwezig' als de atleet die dag volgens zijn schema traint).

Opslaan bewaart elke gekozen status expliciet, ook 'aanwezig' (geen rij =
'nog niet ingevuld'). 'blessure' is gezondheidsinformatie: de reden blijft kort
en feitelijk, geen diagnose. Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Mapping

from atleten.aanwezigheid import NIET_INGEVULD, STATUS_TEKST
from atleten.landingspagina import categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
from models import ABSENTIE_STATUSSEN, Absentie, Atleet, Groep, Periodeplan, Training

from .absentie import absentielijst

STATUS_VELD = "status-"
REDEN_VELD = "reden-"
MAX_REDEN = 80                        # kort en feitelijk


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

    @property
    def telling(self) -> dict[str, int]:
        c = Counter(d.status for d in self.deelnemers)
        return {s: c.get(s, 0) for s in (*ABSENTIE_STATUSSEN, NIET_INGEVULD)}


def trainingpagina(db: Opslag, training_id: int, *, peildatum: date | None = None) -> TrainingPagina | None:
    t = db.training(training_id)
    if t is None:
        return None
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
    return TrainingPagina(t, groep, periode, (t.datum - vandaag).days, deelnemers, _stand(db, groep, t),
                          alle[i - 1] if i > 0 else None, alle[i + 1] if i + 1 < len(alle) else None)


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
