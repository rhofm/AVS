"""Wedstrijden: plannen van komende wedstrijden en wie er met welke onderdelen meedoet.

Alle functies krijgen een open `Opslag` (db/queries.py) mee als eerste argument
en werken met modellen uit models/. Ze bevatten geen SQL.

    from wedstrijden import planning
"""

from . import planning

__all__ = ["planning"]
