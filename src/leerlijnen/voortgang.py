"""Voortgang van één atleet op de leerdoelen (leerlijnen.db + leerdoelscores.db).

Voor de pagina 'Leerdoelen' (bereikbaar vanaf de landingspagina van een atleet):
per leerlijn de leerdoelen van de leeftijdscategorie van de atleet, met de
laatste score (1-5). Dezelfde pagina heeft een bewerkstand; `scores_opslaan()`
verwerkt dat formulier.

Geen SQL: alles via `Opslag`. Geen naam of master_id in leerlijnen.db of
leerdoelscores.db; dat regelt `Opslag` met pseudoniemen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping

from db.queries import Opslag, OpslagFout
from models import CATEGORIEEN, Atleet, Leerdoel, LeerdoelScore

#: Vanaf deze score telt een leerdoel als 'zelfstandig' (zie scoreschaal).
ZELFSTANDIG = 4
VELD_PREFIX = "score-"


def leerdoelcategorie(categorie: str | None) -> str | None:
    """Leeftijdscategorie (U8 … Senior) naar een categorie van de leerlijnen (U10 … U20)."""
    if categorie is None:
        return None
    if categorie in CATEGORIEEN:
        return categorie
    return CATEGORIEEN[-1] if categorie == "Senior" else CATEGORIEEN[0]


@dataclass
class LeerdoelRegel:
    leerdoel: Leerdoel
    score: LeerdoelScore | None          # None = nog niet beoordeeld
    eigen_categorie: bool                # hoort bij de categorie van de atleet (niet een eerdere)

    @property
    def waarde(self) -> int | None:
        return self.score.score if self.score else None


@dataclass
class LeerlijnBlok:
    code: str                            # 'SPR'
    naam: str                            # 'Sprint'
    regels: list[LeerdoelRegel] = field(default_factory=list)

    @property
    def aantal(self) -> int:
        return len(self.regels)

    @property
    def beoordeeld(self) -> int:
        return sum(1 for r in self.regels if r.score)

    @property
    def zelfstandig(self) -> int:
        return sum(1 for r in self.regels if r.waarde is not None and r.waarde >= ZELFSTANDIG)

    @property
    def gemiddelde(self) -> float | None:
        w = [r.waarde for r in self.regels if r.waarde is not None]
        return sum(w) / len(w) if w else None


@dataclass
class LeerdoelenPagina:
    atleet: Atleet
    categorie: str | None                # leerlijncategorie (U10 … U20); None = onbekend, alles getoond
    doorlopend: bool                     # ook doelen uit eerdere categorieën
    scoreschaal: dict[int, str]
    leerlijnen: list[LeerlijnBlok]
    vandaag: date

    @property
    def aantal(self) -> int:
        return sum(b.aantal for b in self.leerlijnen)

    @property
    def zelfstandig(self) -> int:
        return sum(b.zelfstandig for b in self.leerlijnen)

    @property
    def beoordeeld(self) -> int:
        return sum(b.beoordeeld for b in self.leerlijnen)


def leerdoelenpagina(db: Opslag, master_id: str, categorie: str | None, *, doorlopend: bool = False,
                     peildatum: date | None = None) -> LeerdoelenPagina | None:
    """De leerdoelen van een atleet met de laatste scores, of None als de atleet niet bestaat.

    categorie:  leeftijdscategorie van de atleet (zie landingspagina.leeftijdscategorie);
                None = onbekend: dan alle leerdoelen.
    doorlopend: ook de doelen uit eerdere categorieën tonen.
    """
    atleet = db.atleet(master_id)
    if atleet is None:
        return None
    cat = leerdoelcategorie(categorie)
    doelen = db.leerdoelen(cat, doorlopend=doorlopend) if cat else db.leerdoelen()
    laatste = db.laatste_leerdoelscores(master_id)
    blokken = {code: LeerlijnBlok(code, naam) for code, naam in db.leerdoel_leerlijnen()}
    for d in doelen:
        blokken[d.leerlijn].regels.append(LeerdoelRegel(d, laatste.get(d.id), cat is None or d.categorie == cat))
    return LeerdoelenPagina(
        atleet=atleet, categorie=cat, doorlopend=doorlopend, scoreschaal=db.scoreschaal(),
        leerlijnen=[b for b in blokken.values() if b.regels], vandaag=peildatum or date.today(),
    )


def samenvatting(db: Opslag, master_id: str, categorie: str | None) -> list[LeerlijnBlok]:
    """Per leerlijn de stand voor de landingspagina (alleen leerlijnen met minstens één score)."""
    p = leerdoelenpagina(db, master_id, categorie)
    return [b for b in p.leerlijnen if b.beoordeeld] if p else []


def scores_opslaan(db: Opslag, master_id: str, formulier: Mapping[str, str], datum: date) -> int:
    """Verwerk het formulier van de bewerkstand. Geeft het aantal opgeslagen scores.

    Velden heten 'score-<leerdoel_id>' met waarde '1' … '5', of '' (niets kiezen).
    Alleen scores die anders zijn dan de laatste worden opgeslagen, zodat de
    geschiedenis niet volloopt met herhalingen. Een lege keuze wist niets.
    """
    laatste = db.laatste_leerdoelscores(master_id)
    nieuw = []
    for veld, waarde in formulier.items():
        if not veld.startswith(VELD_PREFIX) or not str(waarde).strip():
            continue
        leerdoel_id = veld[len(VELD_PREFIX):]
        try:
            score = int(waarde)
        except ValueError:
            raise OpslagFout(f"Score voor {leerdoel_id} moet 1 t/m 5 zijn, niet {waarde!r}.") from None
        vorige = laatste.get(leerdoel_id)
        if vorige is not None and vorige.score == score:
            continue
        nieuw.append(LeerdoelScore(master_id, leerdoel_id, score, datum))
    if nieuw:
        db.leerdoelscores_opslaan(nieuw)
    return len(nieuw)
