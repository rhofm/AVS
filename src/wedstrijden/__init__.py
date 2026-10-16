"""Wedstrijden: plannen van komende wedstrijden en wie er met welke onderdelen meedoet,
en de planning als lijst of kalender tonen.

Alle functies krijgen een open `Opslag` (db/queries.py) mee als eerste argument
en werken met modellen uit models/. Ze bevatten geen SQL.

    from wedstrijden import planning, kalender
"""

from . import kalender, planning

__all__ = ["kalender", "planning"]
