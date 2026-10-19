"""Dataclass Atleet: persoonsgegevens, specialisatie.

De naam bestaat uit voornaam, tussenvoegsel (optioneel) en achternaam. `naam`
geeft de volledige naam ('Jan de Vries'); sorteren gaat standaard op achternaam
zonder tussenvoegsel, zoals in Nederland gebruikelijk, of op voornaam als dat in
Instellingen is gekozen (`instellingen.naam_sleutel`).

Hoort bij de tabel `atleet` in personen.db. Een atleet wordt in de hele app
aangeduid met zijn master_id. Het pseudoniem (atleet_ref) in prestaties.db en
testen.db is een opslagdetail van db/ en komt in de modellen niet voor.

Privacy: naam, geboortedatum, atletiek.nu-id en AU-licentienummer staan met
repr=False, zodat ze niet in logs of foutmeldingen belanden als een Atleet geprint wordt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Geslacht = Literal["M", "V", "X"]
GESLACHTEN: tuple[str, ...] = ("M", "V", "X")


@dataclass(slots=True)
class Atleet:
    voornaam: str = field(repr=False)
    achternaam: str = field(repr=False)             # zonder tussenvoegsel
    geslacht: Geslacht | None = None
    geboortedatum: str | None = field(default=None, repr=False)  # 'YYYY-MM-DD' of alleen 'YYYY'
    club: str | None = None
    atletieknu_id: str | None = field(default=None, repr=False)
    specialisatie: str | None = None
    actief: bool = True
    notities: str | None = field(default=None, repr=False)
    tussenvoegsel: str | None = field(default=None, repr=False)   # bv. 'de', 'van der'
    au_licentienummer: str | None = field(default=None, repr=False)   # licentienummer Atletiekunie, alleen cijfers
    master_id: str | None = None        # None zolang nog niet opgeslagen; db/ maakt hem aan
    aangemaakt_op: str | None = None    # gezet door de database

    def __post_init__(self) -> None:
        if self.tussenvoegsel is not None:
            self.tussenvoegsel = " ".join(self.tussenvoegsel.split()) or None
        if self.geslacht is not None and self.geslacht not in GESLACHTEN:
            raise ValueError(f"Onbekend geslacht {self.geslacht!r}; kies uit {GESLACHTEN}.")
        if self.master_id is not None and len(self.master_id) != 32:
            raise ValueError("master_id moet 32 hex-tekens zijn.")
        if self.geboortedatum is not None:
            _controleer_geboortedatum(self.geboortedatum)
        if self.au_licentienummer is not None:
            self.au_licentienummer = "".join(str(self.au_licentienummer).split()) or None
            if self.au_licentienummer is not None and not self.au_licentienummer.isdigit():
                raise ValueError("Het AU-licentienummer bestaat alleen uit cijfers.")

    @property
    def volledige_achternaam(self) -> str:
        """Achternaam met tussenvoegsel: 'de Vries'."""
        return f"{self.tussenvoegsel} {self.achternaam}" if self.tussenvoegsel else self.achternaam

    @property
    def naam(self) -> str:
        """Volledige naam: 'Jan de Vries'."""
        return f"{self.voornaam} {self.volledige_achternaam}"

    @property
    def geboortejaar(self) -> int | None:
        return int(self.geboortedatum[:4]) if self.geboortedatum else None

    def leeftijd_op(self, peildatum: date) -> int | None:
        """Leeftijd op een datum. Is alleen het geboortejaar bekend, dan het
        verschil in jaren (zoals de leeftijdscategorieën in de atletiek werken)."""
        if not self.geboortedatum:
            return None
        if len(self.geboortedatum) == 4:
            return peildatum.year - int(self.geboortedatum)
        geboren = date.fromisoformat(self.geboortedatum)
        verjaard = (peildatum.month, peildatum.day) >= (geboren.month, geboren.day)
        return peildatum.year - geboren.year - (0 if verjaard else 1)


def _controleer_geboortedatum(waarde: str) -> None:
    if len(waarde) == 4 and waarde.isdigit():
        return
    try:
        date.fromisoformat(waarde)
    except ValueError:
        raise ValueError("geboortedatum moet 'YYYY-MM-DD' of 'YYYY' zijn.") from None
