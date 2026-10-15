"""Geïmporteerde prestaties aan de juiste atleet (master_id) koppelen.

Importers lezen een uitslagpagina en leveren Prestatie-objecten zonder
master_id, met tijdelijke `bron_*`-velden (naam, atletiek.nu-id, geboortejaar,
club). Deze module zoekt bij elke prestatie de atleet in personen.db.

Volgorde van zoeken:
  1. atletiek.nu-id                      -> zeker
  2. naam + geboortejaar                 -> zeker (bij precies één treffer)
  3. naam + club                         -> zeker (bij precies één treffer)
  4. alleen naam                         -> NIET zeker: de trainer bevestigt
  5. niets gevonden                      -> onbekend: geen eigen atleet, of nieuw

Alleen zekere koppelingen gaan automatisch door. Een uitslag bevat ook
atleten van andere clubs; die horen niet in de database en blijven dus
'onbekend'. Na `bevestig()` wordt het atletiek.nu-id bij de atleet bewaard,
zodat de volgende import wel zeker is.

De bron-velden worden bij het koppelen gewist (Prestatie.gekoppeld()), zodat
er nooit een naam in prestaties.db terechtkomt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Literal

from db.queries import Opslag
from models import Atleet, Prestatie

Manier = Literal["atletieknu_id", "naam_en_jaar", "naam_en_club", "naam", "meerdere", "geen"]
ZEKERE_MANIEREN = ("atletieknu_id", "naam_en_jaar", "naam_en_club")


def normaliseer(naam: str | None) -> str:
    """Naam vergelijkbaar maken: kleine letters, zonder accenten, leestekens en
    dubbele spaties. 'Achternaam, Voornaam' wordt 'voornaam achternaam'."""
    if not naam:
        return ""
    if "," in naam:
        achter, _, voor = naam.partition(",")
        naam = f"{voor} {achter}"
    naam = unicodedata.normalize("NFKD", naam)
    naam = "".join(t for t in naam if not unicodedata.combining(t))
    naam = re.sub(r"[^\w\s']", " ", naam.lower())
    return " ".join(naam.split())


@dataclass
class Koppeling:
    """Resultaat van het zoeken naar één atleet."""
    manier: Manier
    atleet: Atleet | None = None
    kandidaten: list[Atleet] = field(default_factory=list)  # bij 'naam' of 'meerdere'

    @property
    def zeker(self) -> bool:
        return self.manier in ZEKERE_MANIEREN

    @property
    def master_id(self) -> str | None:
        return self.atleet.master_id if self.atleet else None


@dataclass
class KoppelResultaat:
    """Resultaat van een hele import, gesplitst voor de UI."""
    gekoppeld: list[Prestatie] = field(default_factory=list)                        # klaar om op te slaan
    te_controleren: list[tuple[Prestatie, Koppeling]] = field(default_factory=list)  # trainer kiest
    onbekend: list[Prestatie] = field(default_factory=list)                          # niet van de club, of nieuw


class Koppelaar:
    """Zoekt atleten bij geïmporteerde prestaties. Laadt alle atleten één keer."""

    def __init__(self, db: Opslag) -> None:
        self.db = db
        self._atleten = db.atleten(alleen_actief=False)
        self._per_naam: dict[str, list[Atleet]] = {}
        for a in self._atleten:
            self._per_naam.setdefault(normaliseer(a.naam), []).append(a)
        self._per_atletieknu_id = {a.atletieknu_id: a for a in self._atleten if a.atletieknu_id}

    def zoek(self, naam: str | None = None, atletieknu_id: str | None = None,
             geboortejaar: int | None = None, club: str | None = None) -> Koppeling:
        if atletieknu_id and atletieknu_id in self._per_atletieknu_id:
            return Koppeling("atletieknu_id", self._per_atletieknu_id[atletieknu_id])

        kandidaten = list(self._per_naam.get(normaliseer(naam), []))
        if not kandidaten:
            return Koppeling("geen")

        # Een kandidaat met een ánder atletiek.nu-id is een andere persoon met dezelfde naam.
        if atletieknu_id:
            kandidaten = [a for a in kandidaten if not a.atletieknu_id]
            if not kandidaten:
                return Koppeling("geen")

        if geboortejaar is not None:
            met_jaar = [a for a in kandidaten if a.geboortejaar == geboortejaar]
            if len(met_jaar) == 1:
                return Koppeling("naam_en_jaar", met_jaar[0])
            # Bekend jaar dat niet klopt: andere persoon.
            kandidaten = [a for a in kandidaten if a.geboortejaar is None or a.geboortejaar == geboortejaar]
            if not kandidaten:
                return Koppeling("geen")

        if club:
            met_club = [a for a in kandidaten if a.club and normaliseer(a.club) == normaliseer(club)]
            if len(met_club) == 1:
                return Koppeling("naam_en_club", met_club[0])

        if len(kandidaten) == 1:
            return Koppeling("naam", kandidaten[0], kandidaten)
        return Koppeling("meerdere", None, kandidaten)

    def zoek_bij(self, p: Prestatie) -> Koppeling:
        return self.zoek(p.bron_naam, p.bron_atletieknu_id, p.bron_geboortejaar, p.bron_club)

    def koppel(self, prestaties: Iterable[Prestatie]) -> KoppelResultaat:
        """Splits een import in gekoppeld / te controleren / onbekend."""
        uit = KoppelResultaat()
        for p in prestaties:
            if p.is_gekoppeld:
                uit.gekoppeld.append(p)
                continue
            k = self.zoek_bij(p)
            if k.zeker:
                uit.gekoppeld.append(p.gekoppeld(k.master_id))
            elif k.manier == "geen":
                uit.onbekend.append(p)
            else:
                uit.te_controleren.append((p, k))
        return uit


def koppel(db: Opslag, prestaties: Iterable[Prestatie]) -> KoppelResultaat:
    """Kortere schrijfwijze voor Koppelaar(db).koppel(prestaties)."""
    return Koppelaar(db).koppel(prestaties)


def bevestig(db: Opslag, p: Prestatie, master_id: str) -> Prestatie:
    """De trainer bevestigt dat een prestatie bij deze atleet hoort.

    Heeft de atleet nog geen atletiek.nu-id en levert de bron er wel een, dan
    wordt dat id bewaard, zodat dezelfde atleet de volgende keer zeker herkend
    wordt.
    """
    atleet = db.atleet(master_id)
    if atleet is None:
        raise ValueError("Onbekende atleet.")
    if p.bron_atletieknu_id and not atleet.atletieknu_id:
        if db.atleet_op_atletieknu_id(p.bron_atletieknu_id) is None:
            atleet.atletieknu_id = p.bron_atletieknu_id
            db.atleet_opslaan(atleet)
    return p.gekoppeld(master_id)
