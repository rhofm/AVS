"""Atleten combineren tot groepen: leden van een groep toevoegen en verwijderen.

Voor de pagina 'Atleten wijzigen' (knop 'Wijzigen' bij de atletenlijst op de
landingspagina van een groep). Het formulier stuurt de volledige nieuwe
ledenlijst mee (één vinkje per atleet); `leden_opslaan()` slaat die op en
meldt wie erbij kwam en wie eraf ging.

Een atleet uit de groep halen verwijdert niets anders: aanwezigheid, PR's en
leerdoelscores blijven bij de atleet bewaard. Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from atleten.landingspagina import categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
from models import Atleet, Groep


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
        return "Atleten gewijzigd: " + "; ".join(delen) + "."


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
    sorteer = lambda a: (a.achternaam.lower(), a.voornaam.lower())   # noqa: E731
    return Wijziging(sorted(toegevoegd, key=sorteer), sorted(verwijderd, key=sorteer))
