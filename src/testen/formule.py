"""Scoreformules voor testen: een kleine, veilige rekenmachine.

Toegestaan: getallen (12 of 12.5 of 12,5), + - * / ^, sqrt( ), haakjes, een
minteken voor een getal of haakje, en de namen:

    L, T of M   het resultaat van het onderdeel: lengte (m), tijd (s) of gewicht (kg)
    C1, C2, ... de parameters van het onderdeel (het aantal kies je zelf)

Voorbeeld: `C1 * sqrt(L) + C2`. Er wordt nooit `eval()` gebruikt: de tekst wordt
zelf gelezen (tokens -> boom) en de boom wordt uitgerekend. Een fout in de formule
of een onmogelijke berekening (delen door nul, wortel van een negatief getal) geeft
een FormuleFout met een uitleg in gewone taal.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

MAX_LENGTE = 300          # tekens in een formule
MAX_DIEPTE = 40           # haakjes binnen haakjes

_TOKEN = re.compile(r"\s*(?:(?P<getal>\d+(?:[.,]\d+)?|[.,]\d+)|(?P<naam>[A-Za-z][A-Za-z0-9_]*)|(?P<teken>[-+*/^()]))")


class FormuleFout(ValueError):
    """De formule klopt niet, of kan met dit resultaat niet worden uitgerekend."""


@dataclass(frozen=True)
class _Token:
    soort: str        # 'getal' | 'naam' | 'teken' | 'einde'
    waarde: str
    plek: int         # positie in de tekst (voor de foutmelding)


def _tokens(tekst: str) -> list[_Token]:
    uit: list[_Token] = []
    i = 0
    while i < len(tekst):
        if tekst[i:].strip() == "":
            break
        m = _TOKEN.match(tekst, i)
        if not m:
            teken = tekst[i:].lstrip()[0]
            raise FormuleFout(f"Onbekend teken {teken!r}. Toegestaan: getallen, + - * / ^, sqrt( ), haakjes, "
                              "het resultaat (L, T of M) en parameters (C1, C2, ...).")
        soort = m.lastgroup
        uit.append(_Token(soort, m.group(soort), m.start(soort)))
        i = m.end()
    uit.append(_Token("einde", "", len(tekst)))
    return uit


class Formule:
    """Een gelezen formule. `Formule("C1 * L", 1, "L").bereken(8.5, [2])` = 17.

    tekst:            de formule zoals getypt
    aantal_parameters: C1 t/m Cn mogen voorkomen
    variabele:        de naam van het resultaat voor dit onderdeel: 'L', 'T' of 'M'
    """

    def __init__(self, tekst: str, aantal_parameters: int = 0, variabele: str = "L"):
        self.tekst = tekst.strip()
        self.aantal_parameters = aantal_parameters
        self.variabele = variabele.upper()
        if not self.tekst:
            raise FormuleFout("De formule is leeg.")
        if len(self.tekst) > MAX_LENGTE:
            raise FormuleFout(f"De formule is te lang (meer dan {MAX_LENGTE} tekens).")
        self._tokens = _tokens(self.tekst)
        self._pos = 0
        self._diepte = 0
        self._gebruikt: set[str] = set()
        self._boom = self._expressie()
        if self._kijk().soort != "einde":
            raise FormuleFout(self._onverwacht(self._kijk()))
        if self.variabele not in self._gebruikt:
            raise FormuleFout(f"De formule gebruikt het resultaat ({self.variabele}) niet.")

    # ------------------------------------------------------------------ lezen
    def _kijk(self) -> _Token:
        return self._tokens[self._pos]

    def _neem(self) -> _Token:
        t = self._tokens[self._pos]
        self._pos += 1
        return t

    def _is_teken(self, *tekens: str) -> bool:
        t = self._kijk()
        return t.soort == "teken" and t.waarde in tekens

    @staticmethod
    def _onverwacht(t: _Token) -> str:
        if t.soort == "einde":
            return "De formule is niet af (er mist iets aan het einde)."
        return f"Onverwacht {t.waarde!r} op plek {t.plek + 1}."

    def _expressie(self):                       # term (('+' | '-') term)*
        links = self._term()
        while self._is_teken("+", "-"):
            op = self._neem().waarde
            links = (op, links, self._term())
        return links

    def _term(self):                            # eenvoudig (('*' | '/') eenvoudig)*
        links = self._eenvoudig()
        while self._is_teken("*", "/"):
            op = self._neem().waarde
            links = (op, links, self._eenvoudig())
        return links

    def _eenvoudig(self):                       # ('-' | '+') eenvoudig | macht
        if self._is_teken("-", "+"):
            op = self._neem().waarde
            rest = self._eenvoudig()
            return ("neg", rest) if op == "-" else rest
        return self._macht()

    def _macht(self):                           # atoom ('^' eenvoudig)?   (rechts-associatief)
        grondtal = self._atoom()
        if self._is_teken("^"):
            self._neem()
            return ("^", grondtal, self._eenvoudig())
        return grondtal

    def _atoom(self):
        t = self._neem()
        if t.soort == "getal":
            return ("getal", float(t.waarde.replace(",", ".")))
        if t.soort == "naam":
            return self._naam(t)
        if t.soort == "teken" and t.waarde == "(":
            return self._tussen_haakjes()
        raise FormuleFout(self._onverwacht(t))

    def _tussen_haakjes(self):
        self._diepte += 1
        if self._diepte > MAX_DIEPTE:
            raise FormuleFout("Te veel haakjes binnen elkaar.")
        binnen = self._expressie()
        if not self._is_teken(")"):
            raise FormuleFout("Een haakje is niet gesloten." if self._kijk().soort == "einde"
                              else self._onverwacht(self._kijk()))
        self._neem()
        self._diepte -= 1
        return binnen

    def _naam(self, t: _Token):
        naam = t.waarde
        if naam.lower() == "sqrt":
            if not self._is_teken("("):
                raise FormuleFout("Na sqrt hoort een haakje: sqrt(...).")
            self._neem()
            return ("sqrt", self._tussen_haakjes())
        hoofd = naam.upper()
        if hoofd in ("L", "T", "M"):
            if hoofd != self.variabele:
                raise FormuleFout(f"Het resultaat van dit onderdeel heet {self.variabele}, niet {hoofd}.")
            self._gebruikt.add(hoofd)
            return ("var",)
        m = re.fullmatch(r"C(\d+)", hoofd)
        if m:
            n = int(m.group(1))
            if not 1 <= n <= self.aantal_parameters:
                hoeveel = (f"Er {'is' if self.aantal_parameters == 1 else 'zijn'} {self.aantal_parameters} "
                           f"parameter{'' if self.aantal_parameters == 1 else 's'}" if self.aantal_parameters
                           else "Er zijn geen parameters")
                raise FormuleFout(f"{hoofd} bestaat niet. {hoeveel}; verhoog het aantal parameters of pas de formule aan.")
            return ("par", n - 1)
        raise FormuleFout(f"Onbekende naam {naam!r}. Gebruik {self.variabele} voor het resultaat, C1, C2, ... voor "
                          "parameters en sqrt( ) voor een wortel.")

    # ------------------------------------------------------------ uitrekenen
    def bereken(self, resultaat: float, parameters: Sequence[float] = ()) -> float:
        """De score bij dit resultaat. FormuleFout bij delen door nul, wortel van een negatief getal, enz."""
        if len(parameters) < self.aantal_parameters:
            raise FormuleFout(f"Er zijn {self.aantal_parameters} parameters nodig, maar er zijn er {len(parameters)}.")
        try:
            waarde = self._reken(self._boom, float(resultaat), list(parameters))
        except OverflowError:
            raise FormuleFout("Het getal wordt te groot om uit te rekenen.") from None
        if isinstance(waarde, complex) or not math.isfinite(waarde):
            raise FormuleFout("De uitkomst is geen gewoon getal.")
        return float(waarde)

    def _reken(self, knoop, x: float, par: list[float]):
        soort = knoop[0]
        if soort == "getal":
            return knoop[1]
        if soort == "var":
            return x
        if soort == "par":
            return float(par[knoop[1]])
        if soort == "neg":
            return -self._reken(knoop[1], x, par)
        if soort == "sqrt":
            binnen = self._reken(knoop[1], x, par)
            if binnen < 0:
                raise FormuleFout("Wortel van een negatief getal bij dit resultaat.")
            return math.sqrt(binnen)
        a = self._reken(knoop[1], x, par)
        b = self._reken(knoop[2], x, par)
        if soort == "+":
            return a + b
        if soort == "-":
            return a - b
        if soort == "*":
            return a * b
        if soort == "/":
            if b == 0:
                raise FormuleFout("Delen door nul bij dit resultaat.")
            return a / b
        if soort == "^":
            try:
                return a ** b
            except ZeroDivisionError:
                raise FormuleFout("Delen door nul bij dit resultaat.") from None
        raise FormuleFout(f"Onbekende bewerking {soort!r}.")      # kan niet: de parser maakt alleen bovenstaande
