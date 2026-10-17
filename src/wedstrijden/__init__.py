"""Wedstrijden: plannen van komende wedstrijden en wie er met welke onderdelen meedoet,
de planning als lijst of kalender tonen, en het overzicht van alle wedstrijden.

Alle functies krijgen een open `Opslag` (db/queries.py) mee als eerste argument
en werken met modellen uit models/. Ze bevatten geen SQL.

    from wedstrijden import planning, kalender, overzicht
"""

from . import kalender, overzicht, planning

__all__ = ["kalender", "overzicht", "planning"]
