"""Gegevens van een bestaande atleet aanpassen (pagina 'Aanpassen' op de landingspagina van een atleet).

Hetzelfde formulier als 'Nieuwe atleet' (zie nieuw.py), vooraf ingevuld, plus:
  - actief / niet actief (wie stopt met trainen: niet actief, alles blijft bewaard);
  - de groepen waar de atleet in zit;
  - verwijderen: wist de atleet en AL zijn gegevens uit alle databases
    (verzoek tot verwijdering, AVG). Alleen na het overtypen van de naam.
Het trainingsschema heeft een eigen pagina (trainingsschema.py).
Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from db.queries import Opslag, OpslagFout
from models import Atleet

from . import beheer
from .koppelen import normaliseer
from .nieuw import NieuweAtleetInvoer, NieuwFormulier, formulier, lees_formulier

#: Velden die op de pagina een naam hebben, voor de melding na opslaan.
VELDNAMEN = {
    "voornaam": "voornaam", "tussenvoegsel": "tussenvoegsel", "achternaam": "achternaam", "geslacht": "geslacht",
    "geboortedatum": "geboortedatum", "specialisatie": "specialisatie", "atletieknu_id": "atletiek.nu-id",
    "au_licentienummer": "AU-licentienummer", "club": "club", "actief": "actief",
}


def ingevuld_uit(db: Opslag, atleet: Atleet) -> dict:
    """De huidige gegevens van de atleet in de vorm van het formulier."""
    gd = atleet.geboortedatum or ""
    return {
        "voornaam": atleet.voornaam, "tussenvoegsel": atleet.tussenvoegsel or "", "achternaam": atleet.achternaam,
        "geslacht": atleet.geslacht or "",
        "geboortedatum": gd if len(gd) == 10 else "", "geboortejaar": gd if len(gd) == 4 else "",
        "specialisatie": atleet.specialisatie or "", "atletieknu_id": atleet.atletieknu_id or "",
        "au_licentienummer": atleet.au_licentienummer or "", "club": atleet.club or "",
        "groep": [str(g.id) for g in db.groepen_van_atleet(atleet.master_id)],
    }


def aanpasformulier(db: Opslag, master_id: str, ingevuld: Mapping | None = None, *,
                    peildatum: date | None = None) -> tuple[Atleet, NieuwFormulier, bool] | None:
    """(atleet, formulier, actief) — het formulier met de huidige gegevens, of met `ingevuld` na een fout."""
    atleet = db.atleet(master_id)
    if atleet is None:
        return None
    if ingevuld is None:
        return atleet, formulier(db, ingevuld_uit(db, atleet), peildatum=peildatum), atleet.actief
    return atleet, formulier(db, ingevuld, peildatum=peildatum), ingevuld.get("actief") == "1"


@dataclass
class Wijziging:
    velden: list[str]                 # gewijzigde velden (namen zoals op de pagina)
    groepen_erbij: list[str]
    groepen_eraf: list[str]

    @property
    def leeg(self) -> bool:
        return not self.velden and not self.groepen_erbij and not self.groepen_eraf

    @property
    def tekst(self) -> str:
        if self.leeg:
            return "Niets gewijzigd."
        delen = []
        if self.velden:
            delen.append("gewijzigd: " + ", ".join(self.velden))
        if self.groepen_erbij:
            delen.append("toegevoegd aan " + ", ".join(self.groepen_erbij))
        if self.groepen_eraf:
            delen.append("uit " + ", ".join(self.groepen_eraf) + " gehaald")
        return "Opgeslagen: " + "; ".join(delen) + "."


def opslaan(db: Opslag, master_id: str, invoer: NieuweAtleetInvoer, *, actief: bool) -> Wijziging:
    """Sla de gegevens en de groepen op. Geeft wat er veranderde. Het trainingsschema blijft ongemoeid."""
    atleet = db.atleet(master_id)
    if atleet is None:
        raise OpslagFout("Deze atleet bestaat niet (meer).")
    nieuw = Atleet(
        voornaam=invoer.voornaam, achternaam=invoer.achternaam, tussenvoegsel=invoer.tussenvoegsel,
        geslacht=invoer.geslacht, geboortedatum=invoer.geboortedatum, club=invoer.club,
        atletieknu_id=invoer.atletieknu_id, specialisatie=invoer.specialisatie, actief=actief,
        notities=atleet.notities, au_licentienummer=invoer.au_licentienummer, master_id=master_id, aangemaakt_op=atleet.aangemaakt_op,
    )
    velden = [naam for veld, naam in VELDNAMEN.items() if getattr(atleet, veld) != getattr(nieuw, veld)]
    if velden:
        beheer.bijwerken(db, nieuw)

    gekozen = set(invoer.groep_ids)
    erbij, eraf = [], []
    for g in sorted(db.groepen(), key=lambda g: g.naam.lower()):
        lid = master_id in g.leden
        if g.id in gekozen and not lid:
            g.voeg_toe(master_id)
            db.groep_opslaan(g)
            erbij.append(g.naam)
        elif lid and g.id not in gekozen:
            g.verwijder(master_id)
            db.groep_opslaan(g)
            eraf.append(g.naam)
    return Wijziging(velden, erbij, eraf)


def lees_en_opslaan(db: Opslag, master_id: str, form: Mapping, *, peildatum: date | None = None) -> Wijziging:
    """Formulier controleren (InvoerFout bij fouten) en opslaan."""
    invoer = lees_formulier(db, form, peildatum=peildatum, eigen_master_id=master_id)
    return opslaan(db, master_id, invoer, actief=form.get("actief") == "1")


def verwijderen(db: Opslag, master_id: str, bevestiging: str) -> Atleet:
    """Verwijder de atleet met al zijn gegevens, maar alleen als `bevestiging` zijn volledige naam is.

    Hoofdletters, accenten en dubbele spaties tellen niet mee. Geeft de verwijderde atleet terug (voor de melding).
    """
    atleet = db.atleet(master_id)
    if atleet is None:
        raise OpslagFout("Deze atleet bestaat niet (meer).")
    if normaliseer(bevestiging) != normaliseer(atleet.naam):
        raise OpslagFout(f"Typ de volledige naam ({atleet.naam}) over om te bevestigen.")
    beheer.verwijderen(db, master_id, bevestigd=True)
    return atleet
