"""De leden van een groep met hun leeftijdscategorie, gedeeld door de groepspagina's
(testen invullen, leerdoelen scoren, overzichten)."""

from __future__ import annotations

from datetime import date

from atleten.landingspagina import leeftijdscategorie
from db.queries import Opslag
from instellingen import op_naam
from models import Atleet, Groep


def leden_met_categorie(db: Opslag, groep: Groep, op: date) -> list[tuple[Atleet, str | None]]:
    """(atleet, leeftijdscategorie op `op`) voor elk lid dat nog bestaat, op naam (Instellingen)."""
    leden = [a for a in (db.atleet(mid) for mid in groep.leden) if a is not None]
    return [(a, leeftijdscategorie(a, op)) for a in op_naam(leden)]
