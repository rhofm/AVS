"""Alles rond één atleet: beheer, profiel, landingspagina, aanwezigheid, prestaties, testen en koppelen van imports.

Alle functies krijgen een open `Opslag` (db/queries.py) mee als eerste argument
en werken met modellen uit models/. Ze bevatten geen SQL.

    from atleten import beheer, profiel, landingspagina, aanwezigheid, prestaties, testen, koppelen
"""

from . import aanwezigheid, beheer, koppelen, landingspagina, prestaties, profiel, testen

__all__ = ["aanwezigheid", "beheer", "koppelen", "landingspagina", "prestaties", "profiel", "testen"]
