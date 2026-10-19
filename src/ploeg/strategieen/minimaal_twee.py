"""Strategie 3: zoveel mogelijk punten, maar wie meedoet doet minstens twee onderdelen.

Een estafette telt mee als onderdeel. Daarna zo min mogelijk inschrijvingen
boven dat minimum.
"""

from __future__ import annotations

MINIMUM = 2


class Strategie:
    naam = "minimaal_twee"
    titel = "Minstens twee onderdelen"
    uitleg = "Zoveel mogelijk punten, maar elke atleet die meedoet, doet minstens twee onderdelen."

    def bouw(self, model) -> list[dict[int, float]]:
        maximaal = model.regelset.max_onderdelen_per_atleet
        for a in model.atleten:
            eigen = model.van_atleet(a)
            if not eigen:
                continue
            estafettes = model.estafettes.get(a, 0)
            z = model.variabele(lb=1 if estafettes else 0)      # atleet doet mee
            # som x + estafettes >= 2 z   en   som x <= maximaal * z
            model.eis({**{v: 1 for v in eigen}, z: -MINIMUM}, -estafettes, float("inf"))
            model.eis({**{v: 1 for v in eigen}, z: -maximaal}, float("-inf"), 0)
        return [model.puntendoel(), {v: -n for v, n in model.inschrijvingen().items()}]
