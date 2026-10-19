"""Het tijdschema (chronoloog) van de gekoppelde wedstrijd, vertaald naar de ploeg.

Voor een ploeg met een gekoppelde wedstrijd met tijdschema (wedstrijd_programma,
zie wedstrijden/chronoloog.py) zoekt `schema()` per atleet en per
programmaonderdeel de regels van het tijdschema op. Daarmee:

- **botsingen**: twee onderdelen die voor deze atleet tegelijk zijn (elke keuze
  van groep overlapt) kan een atleet niet allebei doen. De optimalisatie plant
  ze niet in (`x[a, e1] + x[a, e2] <= 1`); de controle waarschuwt.
- **dagdeel**: een lid dat alleen 's ochtends of 's middags kan
  (`PloegLid.beschikbaar`) doet geen onderdeel dat in het andere dagdeel begint.
  De middag begint om MIDDAG (13:00).
- **groepen** (9.1): heeft een technisch onderdeel meer groepen, dan krijgen de
  atleten van de ploeg elk een andere groep, waar mogelijk zonder botsing
  (`groepen_indelen()`).

Een regel van het tijdschema hoort bij een programmaonderdeel als de naam klopt
(naam + specificatie zoals bij de inschrijving, de naam zonder specificatie, of
de sleutel uit de puntentelling, bijv. '4x80m') en de categorie past
(`chronoloog.past_bij`). Welke categorie: bij 'materiaal: ploeg' die van de ploeg
(een U14 in de U16-ploeg loopt bij de U16), bij masters 'Masters', anders die
van de atleet. Kan een categorie niet gelezen worden, dan telt de regel mee.

Zonder gekoppelde wedstrijd of tijdschema is er geen schema: dan geen
botsingen, dagdelen of groepen. Niets wordt opgeslagen.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from db.queries import Opslag
from models import Atleet, Inzet, Ploeg, ProgrammaOnderdeel
from ploeg.regels import Regelset
from ploeg.vergelijk import Matrix, normaliseer
from wedstrijden.chronoloog import past_bij

MIDDAG = "13:00"                      # vanaf hier is het 's middags
_SPEC = re.compile(r"^[\d.]+(kg|g|cm)$")
_CATEGORIE = re.compile(r"^(U\d{1,2})-([MV])$")


@dataclass(slots=True)
class Schema:
    """Per atleet en programmaonderdeel de regels van het tijdschema (groepen = alternatieven)."""

    regels: dict[tuple[str, str], list[ProgrammaOnderdeel]] = field(default_factory=dict)

    def van(self, atleet_id: str, onderdeel: str) -> list[ProgrammaOnderdeel]:
        return self.regels.get((atleet_id, onderdeel), [])

    def tijden(self, onderdeel: str) -> list[str]:
        """Begintijden van een onderdeel over alle atleten, voor in de tabelkop ('10:30')."""
        return sorted({r.starttijd for (_, e), rs in self.regels.items() if e == onderdeel for r in rs})

    def botst(self, atleet_id: str, e1: str, e2: str) -> bool:
        """Kan de atleet e1 en e2 niet allebei doen (elke combinatie van groepen overlapt)?"""
        a, b = self.van(atleet_id, e1), self.van(atleet_id, e2)
        return bool(a and b) and all(x.overlapt(y) for x in a for y in b)

    def botsingen(self, atleet_id: str, onderdelen: Iterable[str]) -> list[tuple[str, str]]:
        return [(e1, e2) for e1, e2 in itertools.combinations(list(dict.fromkeys(onderdelen)), 2)
                if self.botst(atleet_id, e1, e2)]

    def past_dagdeel(self, atleet_id: str, onderdeel: str, beschikbaar: str) -> bool:
        """Kan de atleet dit onderdeel doen in zijn dagdeel? Zonder tijden: ja."""
        if beschikbaar == "hele_dag":
            return True
        rs = self.van(atleet_id, onderdeel)
        if not rs:
            return True
        ochtend = [r.starttijd < MIDDAG for r in rs]
        return any(ochtend) if beschikbaar == "ochtend" else not all(ochtend)

    def groepen(self, atleet_id: str, onderdeel: str) -> list[int]:
        return sorted({r.groep for r in self.van(atleet_id, onderdeel) if r.groep is not None})


def _tijdschema_categorie(regelset: Regelset, ploeg: str, atleet: Atleet, categorie: str | None
                          ) -> tuple[str | None, str | None]:
    """(leeftijd, geslacht) zoals het tijdschema ze noemt: ('U16', 'V'), ('Masters', 'M'), ('Senior', 'V')."""
    geslacht = atleet.geslacht
    if regelset.leeftijdsklassen == "masters":
        return "Masters", geslacht
    if regelset.materiaal == "ploeg" and (m := _CATEGORIE.match(ploeg)):
        return m.group(1), geslacht
    if categorie and (m := _CATEGORIE.match(categorie)):
        return m.group(1), geslacht
    if categorie and categorie.startswith("SEN"):
        return "Senior", geslacht
    return None, geslacht


def _namen(regelset: Regelset, ploeg: str, sleutel: str, categorie: str) -> tuple[set[str], str]:
    """Genormaliseerde namen die bij een programmaonderdeel horen, en de basisnaam."""
    info = regelset.onderdelen[sleutel]
    basis = normaliseer(info.naam)
    return {normaliseer(regelset.onderdeel_naam(ploeg, sleutel, categorie)), basis,
            normaliseer(info.punten_sleutel)}, basis


def _hoort_bij(naam: str, namen: set[str], basis: str) -> bool:
    n = normaliseer(naam)
    return n in namen or (n.startswith(basis) and bool(_SPEC.match(n[len(basis):])))


def schema(db: Opslag, regelset: Regelset, ploeg: Ploeg, matrix: Matrix) -> Schema | None:
    """Het schema voor de atleten in de matrix, of None zonder gekoppelde wedstrijd met tijdschema."""
    if ploeg.wedstrijd_id is None:
        return None
    regels = db.programma(ploeg.wedstrijd_id)
    if not regels:
        return None
    onderdeelnamen = {o.id: o.naam for o in db.onderdelen()}

    def naam_van(r: ProgrammaOnderdeel) -> str:
        return onderdeelnamen.get(r.onderdeel_id, "") if r.onderdeel_id is not None else (r.onderdeel_tekst or "")

    uit = Schema()
    for rij in matrix.rijen:
        leeftijd, geslacht = _tijdschema_categorie(regelset, ploeg.categorie, rij.atleet, rij.categorie)
        for r in matrix.regels:
            namen, basis = _namen(regelset, ploeg.categorie, r.sleutel, rij.categorie or ploeg.categorie)
            gevonden = [p for p in regels
                        if (_hoort_bij(naam_van(p), namen, basis)
                            or (p.onderdeel_tekst and _hoort_bij(p.onderdeel_tekst, namen, basis)))
                        and past_bij(p, leeftijd, geslacht) is not False]
            if gevonden:
                uit.regels[(rij.master_id, r.sleutel)] = gevonden
    return uit


# ============================================================
# Groepen bij technische onderdelen (9.1)
# ============================================================
def groepen_indelen(schema_: Schema | None, regelset: Regelset, inzet: Iterable[Inzet],
                    beschikbaar: Mapping[str, str] | None = None) -> list[Inzet]:
    """Geef atleten op een onderdeel met meer groepen elk een andere groep, met zo min mogelijk
    botsingen met hun andere onderdelen en in hun dagdeel (`beschikbaar`: atleet -> 'ochtend',
    'middag' of 'hele_dag'). Zonder groepen in het tijdschema: groep blijft leeg."""
    inzet = list(inzet)
    beschikbaar = beschikbaar or {}
    if schema_ is None:
        return [Inzet(i.atleet_id, i.onderdeel, None, i.vast) for i in inzet]
    per_atleet: dict[str, list[str]] = {}
    for i in inzet:
        per_atleet.setdefault(i.atleet_id, []).append(i.onderdeel)
    per_onderdeel: dict[str, list[Inzet]] = {}
    for i in inzet:
        per_onderdeel.setdefault(i.onderdeel, []).append(i)

    gekozen: dict[tuple[str, str], int | None] = {}
    for e, lijst in per_onderdeel.items():
        groepen = sorted(set.union(*(set(schema_.groepen(i.atleet_id, e)) for i in lijst)))
        if len(groepen) < 2 or regelset.onderdelen.get(e) is None or regelset.onderdelen[e].is_estafette:
            continue
        atleten = [i.atleet_id for i in lijst]

        def botsingen(a: str, g: int) -> int:
            mijn = [r for r in schema_.van(a, e) if r.groep == g]
            if not mijn:
                return 99                                          # deze groep is niet voor deze atleet
            anders = [r for o in per_atleet[a] if o != e for r in schema_.van(a, o)]
            dagdeel = beschikbaar.get(a, "hele_dag")
            buiten = dagdeel != "hele_dag" and any((x.starttijd < MIDDAG) != (dagdeel == "ochtend") for x in mijn)
            return sum(1 for x in mijn for y in anders if x.overlapt(y)) + (10 if buiten else 0)

        beste, beste_kosten = None, None
        verdelingen = itertools.permutations(groepen, len(atleten)) if len(atleten) <= len(groepen) else \
            [tuple(groepen[k % len(groepen)] for k in range(len(atleten)))]
        for verdeling in verdelingen:
            kosten = sum(botsingen(a, g) for a, g in zip(atleten, verdeling))
            if beste_kosten is None or kosten < beste_kosten:
                beste, beste_kosten = verdeling, kosten
        for a, g in zip(atleten, beste or ()):
            gekozen[(a, e)] = g
    return [Inzet(i.atleet_id, i.onderdeel, gekozen.get((i.atleet_id, i.onderdeel)), i.vast) for i in inzet]


def dagdeel_tekst(beschikbaar: str) -> str:
    return {"ochtend": "alleen 's ochtends", "middag": "alleen 's middags"}.get(beschikbaar, "de hele dag")


def beschikbaarheid(leden: Iterable) -> Mapping[str, str]:
    return {lid.atleet_id: lid.beschikbaar for lid in leden}
