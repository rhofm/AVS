"""Strategie 1: zoveel mogelijk punten, ook als een atleet maar één onderdeel doet.

Eerst de punten; daarna zo min mogelijk inschrijvingen, zodat er geen atleten
zonder punten op een onderdeel staan.
"""

from __future__ import annotations


class Strategie:
    naam = "max_punten"
    titel = "Zoveel mogelijk punten"
    uitleg = "De sterkste opstelling; een atleet mag ook maar één onderdeel doen."

    def bouw(self, model) -> list[dict[int, float]]:
        return [model.puntendoel(), {v: -n for v, n in model.inschrijvingen().items()}]
