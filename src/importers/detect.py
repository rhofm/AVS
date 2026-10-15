"""Automatische detectie: probeert elke importer tot er een can_handle(url) is."""

from __future__ import annotations

# Importeren registreert de importers bij Importer (via __init_subclass__).
# Een nieuwe importer: maak een subklasse van Importer en importeer de module hier.
from . import atletieknu_prs, atletieknu_wedstrijd, seltec  # noqa: F401
from .base import Importer, ImportFout


def kies_importer(url: str, log=None) -> Importer:
    """Een instantie van de eerste importer die de link aankan; anders ImportFout."""
    for klasse in Importer.importers():
        if klasse.can_handle(url):
            return klasse(log=log)
    raise ImportFout(f"Deze link wordt (nog) niet herkend: {url}\n"
                     "Ondersteund: atletiek.nu-profielen en -wedstrijden, en Seltec-wedstrijden.")


def importeer(url: str, log=None):
    """Kies de juiste importer en parse de link in één keer."""
    return kies_importer(url, log=log).parse(url)
