"""Dataclass Atleet: persoonsgegevens, specialisatie.

Hoort bij de tabel `atleet` in personen.db. Een atleet wordt in de hele app
aangeduid met zijn master_id. Het pseudoniem (atleet_ref) in prestaties.db en
testen.db is een opslagdetail van db/ en komt in de modellen niet voor.

Privacy: naam en geboortedatum staan met repr=False, zodat ze niet in logs of
foutmeldingen belanden als een Atleet geprint wordt.
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
    achternaam: str = field(repr=False)
    geslacht: Geslacht | None = None
    geboortedatum: str | None = field(default=None, repr=False)  # 'YYYY-MM-DD' of alleen 'YYYY'
    club: str | None = None
    atletieknu_id: str | None = field(default=None, repr=False)
    specialisatie: str | None = None
    actief: bool = True
    notities: str | None = field(default=None, repr=False)
    master_id: str | None = None        # None zolang nog niet opgeslagen; db/ maakt hem aan
    aangemaakt_op: str | None = None    # gezet door de database

    def __post_init__(self) -> None:
        if self.geslacht is not None and self.geslacht not in GESLACHTEN:
            raise ValueError(f"Onbekend geslacht {self.geslacht!r}; kies uit {GESLACHTEN}.")
        if self.master_id is not None and len(self.master_id) != 32:
            raise ValueError("master_id moet 32 hex-tekens zijn.")
        if self.geboortedatum is not None:
            _controleer_geboortedatum(self.geboortedatum)

    @property
    def naam(self) -> str:
        return f"{self.voornaam} {self.achternaam}"

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
