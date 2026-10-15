"""Alles rond één atleet: beheer, profiel, prestaties, testen en koppelen van imports.

Alle functies krijgen een open `Opslag` (db/queries.py) mee als eerste argument
en werken met modellen uit models/. Ze bevatten geen SQL.

    from atleten import beheer, profiel, prestaties, testen, koppelen
"""

from . import beheer, koppelen, prestaties, profiel, testen

__all__ = ["beheer", "koppelen", "prestaties", "profiel", "testen"]
