"""Dataclasses voor een ploegopstelling: de ploeg zelf (Ploeg), wie erin zit (PloegLid) en wie wat doet (Inzet).

Horen bij personen.db (de ploegtabellen; zie docs/Ploegopstelling_ontwerp.md).
Een atleet heet hier, zoals overal in de modellen, met zijn master_id
(`atleet_id`). Een onderdeel is de programmasleutel uit het regelbestand
(bijv. '80mH', 'kogelstoten', '4x80m'), niet een onderdeel_id: welk onderdeel
met welke specificatie dat is, hangt af van de ploeg (zie ploeg/regels.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Rol = Literal["deelnemer", "reserve"]
ROLLEN: tuple[str, ...] = ("deelnemer", "reserve")

Beschikbaar = Literal["hele_dag", "ochtend", "middag"]
BESCHIKBAAR: tuple[str, ...] = ("hele_dag", "ochtend", "middag")

Prestatiebasis = Literal["seizoen", "pr", "12mnd"]
#: Welke prestatie telt voor de punten: (code, uitleg voor de trainer).
PRESTATIEBASIS: dict[str, str] = {
    "seizoen": "Beste van dit en vorig seizoen",
    "pr": "PR (beste ooit)",
    "12mnd": "Beste van de laatste 12 maanden",
}


@dataclass(slots=True)
class Ploeg:
    """Een ploeg voor één competitiewedstrijd (tabel `ploeg`).

    `regelset` is de bestandsnaam in config/ploeg_regels/ (zonder .yaml),
    `categorie` de ploeg daarin ('U16-V') en `programma` de wedstrijd
    ('wedstrijd_2'). `datum` is de wedstrijddag; met een gekoppelde wedstrijd
    (`wedstrijd_id`, prestaties.db) is dat de datum van die wedstrijd.
    """

    naam: str                       # bijv. 'U16 meisjes A'
    regelset: str
    categorie: str
    programma: str
    datum: date
    wedstrijd_id: int | None = None
    competitie: str | None = None   # naam uit het regelbestand, om te tonen
    strategie: str | None = None    # welke 'mentaliteit' de opstelling maakte (None = met de hand)
    prestatiebasis: Prestatiebasis = "seizoen"
    id: int | None = None
    aangemaakt_op: str | None = None

    def __post_init__(self) -> None:
        self.naam = " ".join((self.naam or "").split())
        if not self.naam:
            raise ValueError("Geef de ploeg een naam.")
        if not self.regelset or not self.categorie or not self.programma:
            raise ValueError("Een ploeg heeft een regelbestand, ploeg (categorie) en wedstrijd nodig.")
        if not isinstance(self.datum, date):
            raise ValueError("Een ploeg heeft een datum nodig.")
        if self.prestatiebasis not in PRESTATIEBASIS:
            raise ValueError(f"Onbekende prestatiebasis {self.prestatiebasis!r}; kies uit {tuple(PRESTATIEBASIS)}.")


@dataclass(slots=True)
class PloegLid:
    """Een atleet op het inschrijfformulier van een ploeg."""

    atleet_id: str
    rol: Rol = "deelnemer"
    beschikbaar: Beschikbaar = "hele_dag"

    def __post_init__(self) -> None:
        if len(self.atleet_id) != 32:
            raise ValueError("atleet_id moet een master_id van 32 hex-tekens zijn.")
        if self.rol not in ROLLEN:
            raise ValueError(f"Onbekende rol {self.rol!r}; kies uit {ROLLEN}.")
        if self.beschikbaar not in BESCHIKBAAR:
            raise ValueError(f"Onbekende beschikbaarheid {self.beschikbaar!r}; kies uit {BESCHIKBAAR}.")


@dataclass(slots=True)
class Inzet:
    """Atleet doet onderdeel (programmasleutel) voor de ploeg; bij estafettes één rij per loper."""

    atleet_id: str
    onderdeel: str
    groep: int | None = None        # groep bij een technisch onderdeel (9.1), als die bekend is
    vast: bool = False              # vastgezet door de trainer: de optimalisatie laat dit staan

    def __post_init__(self) -> None:
        if len(self.atleet_id) != 32:
            raise ValueError("atleet_id moet een master_id van 32 hex-tekens zijn.")
        if not self.onderdeel or not self.onderdeel.strip():
            raise ValueError("Een inzet heeft een onderdeel nodig.")
        if self.groep is not None and self.groep < 1:
            raise ValueError("Groep is 1, 2, ...")
