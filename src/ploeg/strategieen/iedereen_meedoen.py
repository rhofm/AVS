"""Strategie 2: zoveel mogelijk atleten op zoveel mogelijk onderdelen.

Eerst zoveel mogelijk atleten die meedoen, dan zoveel mogelijk inschrijvingen
(tot 3 per atleet, binnen het maximum per onderdeel), en pas dan de punten.
"""

from __future__ import annotations

import math


class Strategie:
    naam = "iedereen_meedoen"
    titel = "Iedereen doet mee"
    uitleg = "Zoveel mogelijk atleten op zoveel mogelijk onderdelen; daarbinnen de meeste punten."

    def bouw(self, model) -> list[dict[int, float]]:
        meedoen = {}
        for a in model.atleten:
            eigen = model.van_atleet(a)
            if not eigen:
                continue
            z = model.variabele()                               # atleet doet mee
            model.eis({z: 1, **{v: -1 for v in eigen}}, -math.inf, 0)   # z <= som x
            meedoen[z] = 1
        return [meedoen, model.inschrijvingen(), model.puntendoel()]
