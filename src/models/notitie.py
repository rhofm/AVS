"""Dataclass Notitie: een vrije notitie over een atleet (iets gezien op training of wedstrijd).

Hoort bij notities.db. In de database staat de atleet als pseudoniem
(atleet_ref); in dit model altijd als master_id (`atleet_id`).
De tekst staat niet in repr(), zodat hij niet per ongeluk in logs belandt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True)
class Notitie:
    atleet_id: str                                 # master_id
    datum: date                                    # waar de notitie over gaat (training/wedstrijd)
    inhoud: str = field(repr=False)                # vrije tekst, mag lang zijn
    id: int | None = None
    aangemaakt_op: str | None = None               # door de database ingevuld
    bijgewerkt_op: str | None = None               # None = nooit aangepast

    def __post_init__(self) -> None:
        self.inhoud = (self.inhoud or "").strip()
        if not self.inhoud:
            raise ValueError("Een notitie mag niet leeg zijn.")

    def samenvatting(self, max_tekens: int = 80) -> str:
        """Eerste regel, ingekort tot max_tekens. Voor lijsten in de UI."""
        regel = self.inhoud.splitlines()[0]
        return regel if len(regel) <= max_tekens else regel[: max_tekens - 1].rstrip() + "…"
