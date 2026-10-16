"""Een nieuwe atleet met de hand toevoegen (pagina 'Nieuwe atleet' bij het atletenoverzicht).

Het formulier vraagt de persoonsgegevens, de specialisatie, het atletiek.nu-id
en meteen de groepen en trainingsdagen, zodat de atleet direct op de juiste
absentielijsten komt. `lees_formulier()` controleert de invoer, `aanmaken()`
slaat alles op. Bestaat er al iemand met dezelfde naam (en hetzelfde
geboortejaar), dan volgt `beheer.DubbeleAtleet` en vraagt de pagina om bevestiging.

Privacy: namen, geboortedatum en atletiek.nu-id gaan alleen naar personen.db
(via `Opslag`); het trainingsschema krijgt alleen het pseudoniem.
Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping

from db.queries import Opslag, OpslagFout
from models import DAGEN, GESLACHTEN, Atleet, Groep, Trainingsschema

from .beheer import nieuwe_atleet
from .landingspagina import DAG_KORT

#: Suggesties voor het veld specialisatie (vrij invulbaar).
SPECIALISATIES: tuple[str, ...] = ("Sprint", "Horden", "Midden- en lange afstand", "Springen", "Werpen",
                                   "Meerkamp")
VELDEN: tuple[str, ...] = ("voornaam", "tussenvoegsel", "achternaam", "geslacht", "geboortedatum",
                           "geboortejaar", "specialisatie", "atletieknu_id", "club")


class InvoerFout(OpslagFout):
    """Een of meer velden kloppen niet. `fouten` = {veld: melding}."""

    def __init__(self, fouten: dict[str, str]) -> None:
        super().__init__(" ".join(fouten.values()))
        self.fouten = fouten


@dataclass
class NieuweAtleetInvoer:
    voornaam: str
    achternaam: str
    tussenvoegsel: str | None = None
    geslacht: str | None = None
    geboortedatum: str | None = None              # 'YYYY-MM-DD' of 'YYYY'
    specialisatie: str | None = None
    atletieknu_id: str | None = None
    club: str | None = None
    groep_ids: list[int] = field(default_factory=list)
    dagen: list[str] = field(default_factory=list)


@dataclass
class GroepKeuze:
    groep: Groep
    gekozen: bool


@dataclass
class DagKeuze:
    dag: str
    kort: str
    gekozen: bool


@dataclass
class NieuwFormulier:
    waarden: dict[str, str]                       # wat er in de tekstvelden staat
    groepen: list[GroepKeuze]
    dagen: list[DagKeuze]
    specialisaties: tuple[str, ...] = SPECIALISATIES
    vandaag: date = field(default_factory=date.today)


def formulier(db: Opslag, ingevuld: Mapping | None = None, *, peildatum: date | None = None) -> NieuwFormulier:
    """Het (lege of al ingevulde) formulier. `ingevuld` is bijv. request.form na een fout."""
    ingevuld = ingevuld or {}
    lijst = (lambda k: ingevuld.getlist(k)) if hasattr(ingevuld, "getlist") else (lambda k: ingevuld.get(k) or [])
    gekozen_groepen = {str(g) for g in lijst("groep")}
    gekozen_dagen = set(lijst("dag"))
    return NieuwFormulier(
        waarden={v: str(ingevuld.get(v) or "") for v in VELDEN},
        groepen=[GroepKeuze(g, str(g.id) in gekozen_groepen) for g in sorted(db.groepen(), key=lambda g: g.naam.lower())],
        dagen=[DagKeuze(d, DAG_KORT[d], d in gekozen_dagen) for d in DAGEN],
        vandaag=peildatum or date.today(),
    )


def _schoon(tekst) -> str | None:
    tekst = " ".join(str(tekst or "").split())
    return tekst or None


def lees_formulier(db: Opslag, form: Mapping, *, peildatum: date | None = None,
                   eigen_master_id: str | None = None) -> NieuweAtleetInvoer:
    """Controleer het formulier. Geeft InvoerFout met een melding per veld als er iets niet klopt.

    eigen_master_id: bij aanpassen de atleet zelf, zodat zijn eigen atletiek.nu-id niet als 'al in gebruik' telt.
    """
    vandaag = peildatum or date.today()
    lijst = (lambda k: form.getlist(k)) if hasattr(form, "getlist") else (lambda k: form.get(k) or [])
    fouten: dict[str, str] = {}

    voornaam, achternaam = _schoon(form.get("voornaam")), _schoon(form.get("achternaam"))
    if not voornaam:
        fouten["voornaam"] = "Vul een voornaam in."
    if not achternaam:
        fouten["achternaam"] = "Vul een achternaam in."

    geslacht = _schoon(form.get("geslacht"))
    if geslacht is not None and geslacht not in GESLACHTEN:
        fouten["geslacht"] = "Kies M, V of X."

    geboortedatum = None
    datum_tekst, jaar_tekst = _schoon(form.get("geboortedatum")), _schoon(form.get("geboortejaar"))
    if datum_tekst:
        try:
            d = date.fromisoformat(datum_tekst)
            if d > vandaag or d.year < 1900:
                raise ValueError
            geboortedatum = d.isoformat()
        except ValueError:
            fouten["geboortedatum"] = "Vul een geldige geboortedatum in (niet in de toekomst)."
    elif jaar_tekst:
        if jaar_tekst.isdigit() and 1900 <= int(jaar_tekst) <= vandaag.year:
            geboortedatum = jaar_tekst
        else:
            fouten["geboortejaar"] = f"Vul een geboortejaar in tussen 1900 en {vandaag.year}."

    atletieknu_id = _schoon(form.get("atletieknu_id"))
    if atletieknu_id is not None:
        if not atletieknu_id.isdigit():
            fouten["atletieknu_id"] = "Het atletiek.nu-id bestaat alleen uit cijfers."
        else:
            bestaand = db.atleet_op_atletieknu_id(atletieknu_id)
            if bestaand is not None and bestaand.master_id != eigen_master_id:
                fouten["atletieknu_id"] = f"Dit atletiek.nu-id hoort al bij {bestaand.naam}."

    groep_ids: list[int] = []
    bekend = {g.id for g in db.groepen()}
    for g in lijst("groep"):
        if not str(g).isdigit() or int(g) not in bekend:
            fouten["groep"] = "Een van de gekozen groepen bestaat niet (meer)."
            break
        groep_ids.append(int(g))

    dagen = [d for d in DAGEN if d in set(lijst("dag"))]
    if set(lijst("dag")) - set(DAGEN):
        fouten["dag"] = "Onbekende trainingsdag gekozen."

    if fouten:
        raise InvoerFout(fouten)
    return NieuweAtleetInvoer(
        voornaam=voornaam, achternaam=achternaam, tussenvoegsel=_schoon(form.get("tussenvoegsel")),
        geslacht=geslacht, geboortedatum=geboortedatum, specialisatie=_schoon(form.get("specialisatie")),
        atletieknu_id=atletieknu_id, club=_schoon(form.get("club")),
        groep_ids=list(dict.fromkeys(groep_ids)), dagen=dagen,
    )


def aanmaken(db: Opslag, invoer: NieuweAtleetInvoer, *, toch_aanmaken: bool = False) -> Atleet:
    """Maak de atleet aan, zet hem/haar in de gekozen groepen en sla het trainingsschema op.

    Geeft beheer.DubbeleAtleet als er al iemand met dezelfde naam bestaat (tenzij toch_aanmaken).
    """
    gegevens = {k: getattr(invoer, k) for k in ("tussenvoegsel", "geslacht", "geboortedatum", "specialisatie",
                                                "atletieknu_id", "club") if getattr(invoer, k) is not None}
    atleet = nieuwe_atleet(db, invoer.voornaam, invoer.achternaam, toch_aanmaken=toch_aanmaken, **gegevens)
    for gid in invoer.groep_ids:
        g = db.groep(gid)
        if g is not None:
            g.voeg_toe(atleet.master_id)
            db.groep_opslaan(g)
    if invoer.dagen:
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(atleet.master_id, invoer.dagen))
    return atleet
