"""Leerlijnen: waar een atleet staat op de leerdoelen (leerlijnen.db + leerdoelscores.db).

    from leerlijnen import overzicht, voortgang

overzicht: de catalogus per onderdeel of categorie (pagina 'Leerlijnen').
voortgang: de scores van één atleet (pagina 'Leerdoelen' van een atleet).
"""

from . import overzicht, voortgang

__all__ = ["overzicht", "voortgang"]
