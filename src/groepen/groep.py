"""Atleten combineren tot groepen: leden, starttijden per weekdag en het weekrooster.

Voor de pagina 'Atleten wijzigen' (knop 'Wijzigen' bij de atletenlijst op de
landingspagina van een groep). Het formulier stuurt de volledige nieuwe
ledenlijst mee (één vinkje per atleet); `leden_opslaan()` slaat die op en
meldt wie erbij kwam en wie eraf ging.

Een atleet uit de groep halen verwijdert niets anders: aanwezigheid, PR's en
leerdoelscores blijven bij de atleet bewaard. Geen SQL: alles via `Opslag`.

Starttijden en trainingsschema
------------------------------
Een groep heeft per weekdag een starttijd of niets (`Groep.starttijden`). Een
atleet kan in meerdere groepen zitten. Komt een atleet in een groep, of krijgt
een groep een extra trainingsdag, dan worden die dagen AANGEVULD in het
trainingsschema van de atleet (dat bepaalt de absentielijst). Er wordt nooit
een dag uit een schema gehaald: of iemand op een dag niet meer komt, kan per
atleet verschillen. Dat pas je aan op de pagina 'Trainingsschema'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Mapping

from atleten.landingspagina import categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
from models import DAGEN, Atleet, Groep, Trainingsschema


@dataclass
class Kandidaat:
    atleet: Atleet
    categorie: str | None
    andere_groepen: list[str] = field(default_factory=list)

    @property
    def categorie_code(self) -> str | None:
        return categorie_code(self.categorie, self.atleet.geslacht)


@dataclass
class LedenFormulier:
    groep: Groep
    leden: list[Kandidaat]            # nu in de groep (ook niet-actieve), op achternaam
    overigen: list[Kandidaat]         # actieve atleten die nog niet in de groep zitten, op achternaam


def ledenformulier(db: Opslag, groep_id: int, *, peildatum: date | None = None) -> LedenFormulier | None:
    groep = db.groep(groep_id)
    if groep is None:
        return None
    vandaag = peildatum or date.today()

    def kandidaat(a: Atleet) -> Kandidaat:
        anderen = [g.naam for g in db.groepen_van_atleet(a.master_id) if g.id != groep.id]
        return Kandidaat(a, leeftijdscategorie(a, vandaag), anderen)

    leden = [kandidaat(a) for a in (db.atleet(m) for m in groep.leden) if a is not None]
    binnen = set(groep.leden)
    overigen = [kandidaat(a) for a in db.atleten(alleen_actief=True) if a.master_id not in binnen]
    return LedenFormulier(groep, leden, overigen)


@dataclass
class Wijziging:
    toegevoegd: list[Atleet]
    verwijderd: list[Atleet]
    schema_aangevuld: list[Atleet] = field(default_factory=list)   # trainingsschema kreeg dagen van de groep erbij

    @property
    def leeg(self) -> bool:
        return not self.toegevoegd and not self.verwijderd

    @property
    def tekst(self) -> str:
        """Korte melding voor na het opslaan."""
        if self.leeg:
            return "Niets gewijzigd."
        delen = []
        if self.toegevoegd:
            delen.append(f"{len(self.toegevoegd)} toegevoegd ({', '.join(a.naam for a in self.toegevoegd)})")
        if self.verwijderd:
            delen.append(f"{len(self.verwijderd)} verwijderd ({', '.join(a.naam for a in self.verwijderd)})")
        tekst = "Atleten gewijzigd: " + "; ".join(delen) + "."
        if self.schema_aangevuld:
            tekst += f" Trainingsschema aangevuld voor {len(self.schema_aangevuld)} atleet/atleten."
        return tekst


def leden_opslaan(db: Opslag, groep_id: int, gekozen: Iterable[str]) -> Wijziging:
    """Maak de leden van de groep precies `gekozen` (master_ids). Onbekende ids geven een fout."""
    groep = db.groep(groep_id)
    if groep is None:
        raise OpslagFout(f"Groep {groep_id} bestaat niet.")
    nieuw = list(dict.fromkeys(m.strip() for m in gekozen if m and m.strip()))
    atleten = {}
    for m in nieuw:
        a = db.atleet(m) if len(m) == 32 else None
        if a is None:
            raise OpslagFout("Onbekende atleet in de keuze.")
        atleten[m] = a
    oud = set(groep.leden)
    toegevoegd = [atleten[m] for m in nieuw if m not in oud]
    verwijderd = [a for a in (db.atleet(m) for m in groep.leden if m not in atleten) if a is not None]
    if toegevoegd or verwijderd:
        groep.leden = nieuw
        db.groep_opslaan(groep)
    aangevuld = [a for a in toegevoegd if schema_aanvullen(db, a.master_id, groep.trainingsdagen)]
    sorteer = lambda a: (a.achternaam.lower(), a.voornaam.lower())   # noqa: E731
    return Wijziging(sorted(toegevoegd, key=sorteer), sorted(verwijderd, key=sorteer), sorted(aangevuld, key=sorteer))


# ============================================================
# Starttijden per weekdag
# ============================================================
def schema_aanvullen(db: Opslag, master_id: str, dagen: Iterable[str]) -> list[str]:
    """Zet `dagen` aan in het trainingsschema van de atleet (er gaat niets uit). Geeft de nieuwe dagen."""
    schema = db.trainingsschema(master_id)
    erbij = [d for d in DAGEN if d in set(dagen) and not schema.traint_op(d)]
    if erbij:
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(master_id, schema.dagen + erbij))
    return erbij


@dataclass
class TijdenWijziging:
    erbij: list[str]                  # dagen waarop de groep nu ook traint
    eraf: list[str]                   # dagen die vervielen
    gewijzigd: list[str]              # zelfde dag, andere tijd
    schema_aangevuld: int = 0         # aantal leden dat dagen in het trainingsschema bijkreeg

    @property
    def leeg(self) -> bool:
        return not (self.erbij or self.eraf or self.gewijzigd)

    @property
    def tekst(self) -> str:
        if self.leeg:
            return "Trainingstijden niet gewijzigd."
        tekst = "Trainingstijden opgeslagen."
        if self.schema_aangevuld:
            tekst += f" Trainingsschema aangevuld voor {self.schema_aangevuld} atleet/atleten."
        if self.eraf:
            tekst += (f" Let op: {', '.join(self.eraf)} vervalt voor de groep; pas zo nodig het "
                      "trainingsschema van de atleten aan.")
        return tekst


def starttijden_opslaan(db: Opslag, groep_id: int, tijden: Mapping[str, str | None],
                        leden_bijwerken: bool = True) -> TijdenWijziging:
    """Zet de starttijden van een groep, bijv. {'dinsdag': '18:30', 'donderdag': '19:00'}.

    Dagen die niet in `tijden` staan of leeg zijn: geen training. Ongeldige tijd
    of dag geeft OpslagFout (en er wordt niets opgeslagen). Met leden_bijwerken
    krijgen alle leden de nieuwe trainingsdagen in hun trainingsschema.
    """
    groep = db.groep(groep_id)
    if groep is None:
        raise OpslagFout(f"Groep {groep_id} bestaat niet.")
    oud = dict(groep.starttijden)
    try:
        groep.zet_starttijden(dict(tijden))
    except ValueError as e:
        raise OpslagFout(str(e)) from None
    nieuw = groep.starttijden
    w = TijdenWijziging([d for d in nieuw if d not in oud], [d for d in oud if d not in nieuw],
                        [d for d in nieuw if d in oud and oud[d] != nieuw[d]])
    if w.leeg:
        return w
    db.groep_opslaan(groep)
    if leden_bijwerken and w.erbij:
        w.schema_aangevuld = sum(1 for m in groep.leden if schema_aanvullen(db, m, w.erbij))
    return w


# ============================================================
# Weekrooster van één atleet (over al zijn groepen)
# ============================================================
@dataclass(frozen=True)
class RoosterRegel:
    dag: str                          # 'dinsdag'
    tijd: str                         # '18:30'
    groep_id: int
    groep: str                        # naam, zoals in de app


def rooster(db: Opslag, master_id: str) -> list[RoosterRegel]:
    """Alle groepstrainingen van de atleet in een week, op dag en tijd gesorteerd."""
    regels = [RoosterRegel(d, t, g.id, g.naam)
              for g in db.groepen_van_atleet(master_id) for d, t in g.starttijden.items()]
    return sorted(regels, key=lambda r: (DAGEN.index(r.dag), r.tijd, r.groep.lower()))
