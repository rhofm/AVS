"""Een hele groep in één keer scoren op een leerdoel (pagina 'Leerdoelen scoren' van een groep).

De trainer kiest één leerdoel (bijv. 'Starthouding blokstart', U14) en ziet daarna alle
atleten van de groep met hun laatste score. Eén formulier, één datum: alleen de scores
die anders zijn dan de laatste worden opgeslagen, zodat de geschiedenis niet volloopt
met herhalingen. Een lege keuze wist niets.

Welke leerdoelen er te kiezen zijn, volgt de categorieën van de atleten in de groep:
voor elke categorie die voorkomt de leerdoelen van die categorie.

Geen SQL: alles via `Opslag`. Het opslaan zelf gaat per atleet met dezelfde regels als
op de pagina van één atleet (`leerlijnen.voortgang`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping

from atleten.landingspagina import categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
from instellingen import naam_tekst
from leerlijnen.voortgang import VELD_PREFIX, leerdoelcategorie
from models import CATEGORIEEN, Atleet, Groep, Leerdoel, LeerdoelScore


@dataclass
class ScoreRij:
    atleet: Atleet
    categorie: str | None                # leeftijdscategorie van de atleet (U14, ...)
    score: LeerdoelScore | None          # laatste score op dit leerdoel; None = nog niet beoordeeld
    eigen_categorie: bool                # het leerdoel hoort bij de categorie van de atleet

    @property
    def waarde(self) -> int | None:
        return self.score.score if self.score else None

    @property
    def categorie_code(self) -> str | None:
        return categorie_code(self.categorie, self.atleet.geslacht)


@dataclass
class LeerlijnKeuze:
    code: str                            # 'SPR'
    naam: str                            # 'Sprint'
    doelen: list[Leerdoel] = field(default_factory=list)


@dataclass
class ScorePagina:
    groep: Groep
    keuzes: list[LeerlijnKeuze]          # te kiezen leerdoelen, per leerlijn
    leerdoel: Leerdoel | None            # het gekozen leerdoel; None = nog niets gekozen
    leerlijn_naam: str | None
    rijen: list[ScoreRij]                # leeg zolang er niets gekozen is
    scoreschaal: dict[int, str]
    vandaag: date

    @property
    def beoordeeld(self) -> int:
        return sum(1 for r in self.rijen if r.score)


def _leden(db: Opslag, groep: Groep, vandaag: date) -> list[tuple[Atleet, str | None]]:
    uit = []
    for mid in groep.leden:
        a = db.atleet(mid)
        if a is not None:
            uit.append((a, leeftijdscategorie(a, vandaag)))
    uit.sort(key=lambda x: naam_tekst(x[0]))
    return uit


def scorepagina(db: Opslag, groep: Groep, leerdoel_id: str | None = None, *,
                peildatum: date | None = None) -> ScorePagina:
    """De keuzelijst van leerdoelen en, bij een gekozen leerdoel, de atleten met hun laatste score.

    Een onbekend of niet-actief leerdoel in `leerdoel_id` geeft een OpslagFout.
    """
    vandaag = peildatum or date.today()
    leden = _leden(db, groep, vandaag)
    categorieen = {leerdoelcategorie(cat) for _, cat in leden}
    categorieen.discard(None)
    namen = dict(db.leerdoel_leerlijnen())
    blokken = {code: LeerlijnKeuze(code, naam) for code, naam in namen.items()}
    for cat in sorted(categorieen, key=CATEGORIEEN.index):
        for d in db.leerdoelen(cat):
            blokken[d.leerlijn].doelen.append(d)
    keuzes = [b for b in blokken.values() if b.doelen]

    leerdoel = None
    rijen: list[ScoreRij] = []
    if leerdoel_id:
        leerdoel = db.leerdoel(leerdoel_id)
        if leerdoel is None or not leerdoel.actief:
            raise OpslagFout(f"Leerdoel {leerdoel_id!r} bestaat niet.")
        for a, cat in leden:
            laatste = db.laatste_leerdoelscores(a.master_id).get(leerdoel.id)
            rijen.append(ScoreRij(a, cat, laatste, leerdoelcategorie(cat) == leerdoel.categorie))
    return ScorePagina(groep, keuzes, leerdoel, namen.get(leerdoel.leerlijn) if leerdoel else None, rijen,
                       db.scoreschaal(), vandaag)


def scores_opslaan(db: Opslag, groep: Groep, leerdoel_id: str, formulier: Mapping[str, str],
                   datum: date) -> int:
    """Verwerk het formulier. Geeft het aantal opgeslagen scores.

    Velden heten 'score-<master_id>' met waarde '1' … '5', of '' (niets kiezen).
    Alleen leden van de groep tellen; een onbekende of niet-lid master_id is een fout
    en dan wordt er niets opgeslagen. Alleen scores die anders zijn dan de laatste
    worden opgeslagen.
    """
    leerdoel = db.leerdoel(leerdoel_id)
    if leerdoel is None or not leerdoel.actief:
        raise OpslagFout(f"Leerdoel {leerdoel_id!r} bestaat niet.")
    nieuw = []
    for veld, waarde in formulier.items():
        if not veld.startswith(VELD_PREFIX) or not str(waarde).strip():
            continue
        master_id = veld[len(VELD_PREFIX):]
        if master_id not in groep.leden:
            raise OpslagFout("Een van de atleten zit niet (meer) in deze groep.")
        try:
            score = int(waarde)
        except ValueError:
            raise OpslagFout(f"Score moet 1 t/m 5 zijn, niet {waarde!r}.") from None
        vorige = db.laatste_leerdoelscores(master_id).get(leerdoel.id)
        if vorige is not None and vorige.score == score:
            continue
        nieuw.append(LeerdoelScore(master_id, leerdoel.id, score, datum))      # ValueError bij score buiten 1-5
    if nieuw:
        db.leerdoelscores_opslaan(nieuw)
    return len(nieuw)
