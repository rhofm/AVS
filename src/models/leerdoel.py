"""Dataclasses Leerdoel en LeerdoelScore.

Leerdoel hoort bij leerlijnen.db (de catalogus, zonder persoonsgegevens).
LeerdoelScore hoort bij leerdoelscores.db (lang formaat: één score per atleet
per leerdoel per datum). Atleten worden aangeduid met hun master_id; het
pseudoniem blijft binnen db/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Categorie = Literal["U10", "U12", "U14", "U16", "U18", "U20"]
CATEGORIEEN: tuple[str, ...] = ("U10", "U12", "U14", "U16", "U18", "U20")

LeerdoelBron = Literal["NA", "AU", "eigen"]
LEERDOEL_BRONNEN: tuple[str, ...] = ("NA", "AU", "eigen")

MIN_SCORE, MAX_SCORE = 1, 5


@dataclass(slots=True)
class Leerdoel:
    id: str                         # bijv. 'SPR-U10-01'
    leerlijn: str                   # code, bijv. 'SPR'
    categorie: str                  # eerste categorie waarin het doel aan bod komt
    volgorde: int
    omschrijving: str
    bron: str = "eigen"
    fase: str | None = None         # LTAD-fase, alleen bij bron 'AU'
    alleen_specialisten: bool = False
    actief: bool = True

    def __post_init__(self) -> None:
        if self.categorie not in CATEGORIEEN:
            raise ValueError(f"Onbekende categorie {self.categorie!r}; kies uit {CATEGORIEEN}.")
        if self.bron not in LEERDOEL_BRONNEN:
            raise ValueError(f"Onbekende bron {self.bron!r}; kies uit {LEERDOEL_BRONNEN}.")

    def geldt_voor(self, categorie: str) -> bool:
        """Of dit doel bij een atleet in `categorie` hoort (leerlijnen zijn doorlopend)."""
        return CATEGORIEEN.index(self.categorie) <= CATEGORIEEN.index(categorie)


@dataclass(slots=True)
class LeerdoelScore:
    atleet_id: str                  # master_id
    leerdoel_id: str
    score: int                      # 1 t/m 5, zie leerlijnen.db: scoreschaal
    datum: date
    notities: str | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.score, int) and MIN_SCORE <= self.score <= MAX_SCORE):
            raise ValueError(f"Score moet een geheel getal van {MIN_SCORE} t/m {MAX_SCORE} zijn, niet {self.score!r}.")
