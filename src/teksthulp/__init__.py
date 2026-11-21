"""Tekst vergelijkbaar of veilig maken, op één plek.

  * plat(): om te zoeken, sorteren en vergelijken ('Zoë  van Dijk' -> 'zoe van dijk');
  * slug(): voor een bestandsnaam, alleen a-z en 0-9 ('Zoë van Dijk' -> 'zoe_van_dijk').

Geen afhankelijkheden van de rest van AVS, zodat elke module dit kan gebruiken.
"""

from __future__ import annotations

import re
import unicodedata


def plat(tekst: str | None) -> str:
    """Kleine letters, zonder accenten en dubbele spaties: 'Zoë  van Dijk' -> 'zoe van dijk'.
    Letters zonder accent-variant ('ø', 'ß') blijven staan."""
    tekst = unicodedata.normalize("NFKD", tekst or "")
    return " ".join("".join(c for c in tekst if not unicodedata.combining(c)).lower().split())


def slug(tekst: str | None, *, scheiding: str = "_", standaard: str = "", max_lengte: int | None = None) -> str:
    """Alleen a-z en 0-9, de rest wordt `scheiding`: 'Zoë van Dijk' -> 'zoe_van_dijk'.

    Wat geen gewone letter is ('ø', '日') valt weg. Leeg resultaat -> `standaard`.
    """
    ascii_ = unicodedata.normalize("NFKD", tekst or "").encode("ascii", "ignore").decode().lower()
    uit = re.sub(r"[^a-z0-9]+", scheiding, ascii_).strip(scheiding)
    if max_lengte is not None:
        uit = uit[:max_lengte]
    return uit or standaard
