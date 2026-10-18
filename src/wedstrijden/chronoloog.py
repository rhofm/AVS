"""Het tijdschema (chronoloog) van een wedstrijd: per atleet wanneer hij/zij moet,
per regel welke atleten meedoen, en botsingen in de planning.

Het tijdschema staat in prestaties.db (wedstrijd_programma). Wie waar meedoet
volgt uit de inschrijvingen (onderdeel) en de categorie van de atleet op de dag
van de wedstrijd (leeftijd + geslacht uit personen.db). Niets hiervan wordt
opgeslagen: het wordt elke keer uitgerekend.

Koppelen gaat zo:
  * de regel moet hetzelfde onderdeel hebben als een inschrijving van de atleet;
  * staat er een categorie bij de regel ('Meisjes U16', 'JU14'), dan moet die
    passen bij de atleet. Kan de app de categorie niet lezen (bijv. 'JPA'), dan
    telt de regel wel mee maar met zeker=False: controleer dat zelf;
  * zijn er meerdere groepen (groep 1, 2, ...) van hetzelfde onderdeel en de
    atleet staat nog niet in een groep, dan komen alle groepen in zijn schema.
    Die groepen botsen onderling niet (de atleet doet er maar één).

Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import combinations

from atleten.landingspagina import leeftijdscategorie
from db.queries import Opslag, OpslagFout
from instellingen import tijd as toon_tijd
from models import Atleet, ProgrammaOnderdeel, Wedstrijd, lees_categorie


# ============================================================
# Past een regel bij een atleet?
# ============================================================
def past_bij(regel: ProgrammaOnderdeel, categorie: str | None, geslacht: str | None) -> bool | None:
    """True = past, False = past niet, None = niet te zeggen (categorie onleesbaar of atleet onbekend).

    categorie/geslacht van de atleet: bijv. 'U16' en 'V' (geslacht 'M', 'V' of 'X').
    Een regel voor meer categorieën ('U18-M, U16-M, U16-V', zoals bij Seltec) past als één
    ervan past; past er geen, dan False; anders None.
    """
    if not regel.categorie:
        return True                                   # voor iedereen
    delen = [d.strip() for d in regel.categorie.split(",") if d.strip()]
    if len(delen) > 1:
        uitkomsten = [_past_bij_categorie(d, categorie, geslacht) for d in delen]
        if True in uitkomsten:
            return True
        return None if None in uitkomsten else False
    return _past_bij_categorie(regel.categorie, categorie, geslacht)


def _past_bij_categorie(tekst: str, categorie: str | None, geslacht: str | None) -> bool | None:
    """past_bij voor één categorie-tekst."""
    leeftijd, regel_geslacht = lees_categorie(tekst)
    if leeftijd is None and regel_geslacht is None:
        return None                                   # onleesbaar
    if leeftijd is not None:
        if categorie is None:
            return None                               # geboortedatum onbekend
        if leeftijd != categorie:
            return False
    if regel_geslacht is not None and geslacht in ("M", "V") and regel_geslacht != geslacht:
        return False
    if regel_geslacht is not None and geslacht not in ("M", "V"):
        return None                                   # geslacht X of onbekend: zelf kijken
    return True


@dataclass(frozen=True)
class SchemaRegel:
    regel: ProgrammaOnderdeel
    zeker: bool                       # False: categorie niet met zekerheid te koppelen
    andere_groep_mogelijk: bool = False   # er zijn meer groepen van dit onderdeel/ronde

    @property
    def sleutel(self) -> tuple:
        """Regels met dezelfde sleutel zijn alternatieven (groep 1 of 2): de atleet doet er één."""
        r = self.regel
        return (r.onderdeel_id or r.onderdeel_tekst, r.categorie or "", r.ronde, r.datum)


def _categorie(atleet: Atleet, w: Wedstrijd) -> str | None:
    return leeftijdscategorie(atleet, w.datum)


def _schema(regels: list[ProgrammaOnderdeel], onderdelen: set[int], categorie: str | None,
            geslacht: str | None) -> list[SchemaRegel]:
    gekozen = []
    for r in regels:
        if r.onderdeel_id is None or r.onderdeel_id not in onderdelen:
            continue
        past = past_bij(r, categorie, geslacht)
        if past is False:
            continue
        gekozen.append((r, past is True))
    per_sleutel: dict[tuple, int] = {}
    for r, _ in gekozen:
        k = (r.onderdeel_id, r.categorie or "", r.ronde, r.datum)
        per_sleutel[k] = per_sleutel.get(k, 0) + 1
    return [SchemaRegel(r, zeker, per_sleutel[(r.onderdeel_id, r.categorie or "", r.ronde, r.datum)] > 1)
            for r, zeker in gekozen]


# ============================================================
# Per atleet
# ============================================================
def persoonlijk_schema(db: Opslag, wedstrijd_id: int, master_id: str) -> list[SchemaRegel]:
    """Wanneer moet deze atleet op deze wedstrijd? Op dag en tijd.

    Alleen onderdelen waarvoor de atleet is ingeschreven. Ingeschreven zonder
    onderdeel ('gaat mee, onderdelen volgen'): leeg schema.
    """
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    a = db.atleet(master_id)
    if a is None:
        raise OpslagFout(f"Atleet {master_id} bestaat niet.")
    onderdelen = {i.onderdeel_id for i in db.inschrijvingen(master_id)
                  if i.wedstrijd_id == wedstrijd_id and i.onderdeel_id is not None}
    return _schema(db.programma(wedstrijd_id), onderdelen, _categorie(a, w), a.geslacht)


# ============================================================
# Per regel van het tijdschema
# ============================================================
@dataclass
class OverzichtRegel:
    regel: ProgrammaOnderdeel
    atleten: list[Atleet] = field(default_factory=list)        # zeker
    misschien: list[Atleet] = field(default_factory=list)      # categorie niet zeker te koppelen


def overzicht(db: Opslag, wedstrijd_id: int) -> list[OverzichtRegel]:
    """Het hele tijdschema, met per regel welke van onze ingeschreven atleten meedoen."""
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    regels = db.programma(wedstrijd_id)
    uit = {r.id: OverzichtRegel(r) for r in regels}
    per_atleet: dict[str, set[int]] = {}
    for i in db.deelnemers(wedstrijd_id):
        if i.onderdeel_id is not None:
            per_atleet.setdefault(i.atleet_id, set()).add(i.onderdeel_id)
    sorteer = lambda a: (a.achternaam.lower(), a.voornaam.lower())   # noqa: E731
    for mid, onderdelen in per_atleet.items():
        a = db.atleet(mid)
        if a is None:
            continue
        for s in _schema(regels, onderdelen, _categorie(a, w), a.geslacht):
            (uit[s.regel.id].atleten if s.zeker else uit[s.regel.id].misschien).append(a)
    for o in uit.values():
        o.atleten.sort(key=sorteer)
        o.misschien.sort(key=sorteer)
    return list(uit.values())


# ============================================================
# Botsingen
# ============================================================
@dataclass(frozen=True)
class Botsing:
    atleet: Atleet
    eerste: ProgrammaOnderdeel
    tweede: ProgrammaOnderdeel
    pauze: int | None                 # minuten tussen einde eerste en begin tweede; None = overlap/onbekend

    @property
    def tekst(self) -> str:
        a, b = self.eerste, self.tweede
        kern = (f"{self.atleet.naam}: {toon_tijd(a.starttijd)} {a.omschrijving} "
                f"en {toon_tijd(b.starttijd)} {b.omschrijving}")
        if self.pauze is None:
            return f"{kern} lopen tegelijk."
        return f"{kern}: maar {self.pauze} min ertussen."


def botsingen(db: Opslag, wedstrijd_id: int, min_pauze: int = 0) -> list[Botsing]:
    """Atleten met onderdelen die tegelijk lopen, of met minder dan `min_pauze` minuten ertussen.

    Zonder duur telt alleen dezelfde begintijd als botsing (de pauze is dan
    onbekend). Groepen van hetzelfde onderdeel (de atleet doet er één) botsen niet.
    """
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    regels = db.programma(wedstrijd_id)
    per_atleet: dict[str, set[int]] = {}
    for i in db.deelnemers(wedstrijd_id):
        if i.onderdeel_id is not None:
            per_atleet.setdefault(i.atleet_id, set()).add(i.onderdeel_id)
    uit = []
    for mid, onderdelen in per_atleet.items():
        a = db.atleet(mid)
        if a is None:
            continue
        schema = _schema(regels, onderdelen, _categorie(a, w), a.geslacht)
        for x, y in combinations(schema, 2):
            if x.sleutel == y.sleutel:
                continue                                   # groep 1 of groep 2: alternatieven
            eerste, tweede = sorted((x.regel, y.regel), key=lambda r: r.begin)
            if eerste.overlapt(tweede):
                uit.append(Botsing(a, eerste, tweede, None))
            elif eerste.einde is not None and min_pauze > 0:
                pauze = int((tweede.begin - eerste.einde).total_seconds() // 60)
                if pauze < min_pauze:
                    uit.append(Botsing(a, eerste, tweede, pauze))
    return sorted(uit, key=lambda b: (b.eerste.begin, b.atleet.achternaam.lower(), b.atleet.voornaam.lower()))


def dagen(regels: list[ProgrammaOnderdeel]) -> list[date]:
    """De dagen van een (meerdaags) tijdschema, op volgorde."""
    return sorted({r.datum for r in regels})
