"""Strategieën ('mentaliteiten') voor het maken van een opstelling.

Elke strategie is een module met een klasse `Strategie` met:
    naam   korte code, gaat in ploeg.strategie (zo is een opstelling achteraf te verklaren)
    titel  wat de trainer ziet
    uitleg één zin over wat de strategie doet
    bouw(model) -> lijst van doelen; mag eigen variabelen en eisen aan het model
                   toevoegen (zie ploeg/optimaliseer.py, Model)

Een nieuwe strategie: maak een module in deze map en zet hem in STRATEGIEEN
hieronder (expliciet, zodat PyInstaller hem meeneemt in de .exe).
"""

from __future__ import annotations

from . import iedereen_meedoen, max_punten, minimaal_twee

STRATEGIEEN = {s.naam: s for s in (max_punten.Strategie(), iedereen_meedoen.Strategie(), minimaal_twee.Strategie())}


def strategie(naam: str):
    """De strategie met deze naam; KeyError als hij niet bestaat."""
    return STRATEGIEEN[naam]
