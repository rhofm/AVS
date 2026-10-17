"""Het atletenoverzicht (pagina 'Atleten'): zoeken en filteren op naam, categorie, groep en specialisatie.

Eén zoekvak doorzoekt alles tegelijk: elk woord moet ergens voorkomen
(naam, categorie zoals 'U16V', groepsnaam of specialisatie), zonder op
hoofdletters of accenten te letten. 'u16 sprint' vindt dus U16-atleten in een
sprintgroep of met specialisatie sprint. Daarnaast twee keuzelijsten om precies
op categorie en groep te filteren.

De sorteersleutels per kolom gaan mee naar de pagina (data-sort), zodat
static/sorteer.js op elke kolom kan sorteren. Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date

from db.queries import Opslag
from models import Atleet, Groep

from .landingspagina import categorie_code, leeftijdscategorie

#: Volgorde van de categorieën voor sorteren en de keuzelijst.
CATEGORIE_VOLGORDE: tuple[str, ...] = ("U8", "U10", "U12", "U14", "U16", "U18", "U20", "Senior")


def plat(tekst: str | None) -> str:
    """Kleine letters, zonder accenten en dubbele spaties: 'Zoë  van Dijk' -> 'zoe van dijk'."""
    tekst = unicodedata.normalize("NFKD", tekst or "")
    return " ".join("".join(c for c in tekst if not unicodedata.combining(c)).lower().split())


@dataclass
class AtleetRij:
    atleet: Atleet
    categorie: str | None              # 'U16' (zonder geslacht), voor het filter
    code: str | None                   # 'U16V', zoals getoond
    groepen: list[Groep] = field(default_factory=list)

    @property
    def zoektekst(self) -> str:
        """Alles waarop gezocht kan worden, plat gemaakt."""
        delen = [self.atleet.naam, self.code or "", self.atleet.specialisatie or ""]
        delen += [g.naam for g in self.groepen]
        return plat(" ".join(delen))

    # ---- sorteersleutels (data-sort) ----
    @property
    def sort_naam(self) -> str:
        """Op achternaam zonder tussenvoegsel, zoals in Nederland gebruikelijk."""
        return plat(f"{self.atleet.achternaam} {self.atleet.voornaam} {self.atleet.tussenvoegsel or ''}")

    @property
    def sort_categorie(self) -> str:
        """Getal: jongste categorie eerst, binnen een categorie M voor V. Leeg = onbekend (onderaan)."""
        if self.categorie not in CATEGORIE_VOLGORDE:
            return ""
        extra = {"M": 1, "V": 2}.get(self.atleet.geslacht or "", 3)
        return str(CATEGORIE_VOLGORDE.index(self.categorie) * 10 + extra)

    @property
    def sort_specialisatie(self) -> str:
        return plat(self.atleet.specialisatie)

    @property
    def sort_groepen(self) -> str:
        return plat(", ".join(sorted(g.naam for g in self.groepen)))


@dataclass
class Overzicht:
    rijen: list[AtleetRij]             # na zoeken en filteren, op achternaam
    totaal: int                        # zonder zoeken/filteren (wel met het actief-vinkje)
    zoek: str
    categorie: str                     # gekozen filter, '' = alle
    groep_id: int | None               # gekozen filter, None = alle
    ook_inactief: bool
    categorieen: list[str]             # keuzelijst: alleen categorieën die voorkomen
    groepen: list[Groep]               # keuzelijst: alle groepen

    @property
    def gefilterd(self) -> bool:
        return bool(self.zoek or self.categorie or self.groep_id)


def past(rij: AtleetRij, zoek: str = "", categorie: str = "", groep_id: int | None = None) -> bool:
    """Voldoet deze rij aan het zoekvak en de filters?"""
    if categorie and rij.categorie != categorie:
        return False
    if groep_id is not None and groep_id not in {g.id for g in rij.groepen}:
        return False
    hooiberg = rij.zoektekst
    return all(woord in hooiberg for woord in plat(zoek).split())


def atletenoverzicht(db: Opslag, *, zoek: str = "", categorie: str = "", groep_id: int | None = None,
                     ook_inactief: bool = False, peildatum: date | None = None) -> Overzicht:
    vandaag = peildatum or date.today()
    alle = []
    for a in db.atleten(alleen_actief=not ook_inactief):
        cat = leeftijdscategorie(a, vandaag)
        alle.append(AtleetRij(a, cat, categorie_code(cat, a.geslacht), db.groepen_van_atleet(a.master_id)))
    alle.sort(key=lambda r: r.sort_naam)
    aanwezig = {r.categorie for r in alle if r.categorie}
    categorie = categorie if categorie in CATEGORIE_VOLGORDE else ""
    groepen = sorted(db.groepen(), key=lambda g: plat(g.naam))
    if groep_id is not None and groep_id not in {g.id for g in groepen}:
        groep_id = None
    return Overzicht(
        rijen=[r for r in alle if past(r, zoek, categorie, groep_id)],
        totaal=len(alle), zoek=(zoek or "").strip(), categorie=categorie, groep_id=groep_id,
        ook_inactief=ook_inactief,
        categorieen=[c for c in CATEGORIE_VOLGORDE if c in aanwezig or c == categorie],
        groepen=groepen,
    )
