"""Testresultaten van een atleet vastleggen en weergeven (op basis van een sjabloon).

Het sjabloon (YAML) zegt welke onderdelen er zijn en hoe een meting een score wordt; de
database (testen.db) bewaart de metingen én de uitgerekende scores van dat moment. Een
latere wijziging van een formule verandert dus nooit stilletjes oude scores.

Hoofdwaarde (`Testresultaat.waarde`, voor 'beste' en vooruitgang): de totaalscore als de
scores worden opgeteld, anders de meting van het eerste onderdeel. `Test.eenheid` en
`Test.lager_is_beter` horen daarbij en worden bij elk resultaat gelijk gehouden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Sequence

from db.queries import Opslag, OpslagFout
from models import Test, TestDeel, Testresultaat

from . import sjabloon as sj
from .formule import FormuleFout
from .sjabloon import Bibliotheek, Onderdeel, Sjabloon, SjabloonFout


def lees_waarde(tekst: str | float | int | None) -> float | None:
    """'12,5' -> 12.5; leeg -> None. ValueError bij iets wat geen (eindig, niet-negatief) getal is."""
    if tekst is None or (isinstance(tekst, str) and not tekst.strip()):
        return None
    x = float(str(tekst).strip().replace(",", ".")) if not isinstance(tekst, (int, float)) else float(tekst)
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"{tekst!r} is geen geldig resultaat")
    return x


# ------------------------------------------------------------------ test <-> sjabloon
def hoofd_eenheid(s: Sjabloon) -> tuple[str, bool]:
    """(eenheid, lager_is_beter) van de hoofdwaarde van een sjabloon."""
    if s.telt_totaal:
        return "punten", False
    eerste = s.onderdelen[0]
    return eerste.eenheid, eerste.lager_is_beter


def test_voor_sjabloon(db: Opslag, s: Sjabloon) -> Test:
    """De `test`-rij bij dit sjabloon; wordt aangemaakt of bijgewerkt (naam, eenheid) als dat nodig is.

    Een bestaande test zonder sjabloon met dezelfde naam (van vóór de sjablonen) wordt aan dit sjabloon
    gekoppeld, zodat de oude resultaten blijven staan.
    """
    eenheid, lager = hoofd_eenheid(s)
    bestaand = db.test_op_sjabloon(s.slug)
    if bestaand is None:
        op_naam = db.test_op_naam(s.naam)
        if op_naam is not None and op_naam.sjabloon not in (None, s.slug):
            raise OpslagFout(f"De naam '{s.naam}' hoort al bij een andere test.")
        bestaand = op_naam
    if bestaand is None:
        return db.test_opslaan(Test(s.naam, eenheid, lager, None, s.slug))
    gewijzigd = (bestaand.naam, bestaand.eenheid, bestaand.lager_is_beter, bestaand.sjabloon) != (s.naam, eenheid, lager, s.slug)
    if gewijzigd:
        if bestaand.eenheid != eenheid and db.aantal_testresultaten(bestaand.id):
            raise OpslagFout("Er zijn al resultaten met een andere eenheid; het totaal optellen kan niet meer "
                             "worden aan- of uitgezet.")
        bestaand.naam, bestaand.eenheid, bestaand.lager_is_beter, bestaand.sjabloon = s.naam, eenheid, lager, s.slug
        db.test_opslaan(bestaand)
    return bestaand


def wijziging_toegestaan(db: Opslag, oud: Sjabloon, nieuw: Sjabloon) -> None:
    """SjabloonFout als een wijziging bestaande resultaten onbruikbaar zou maken.

    Zijn er al resultaten op deze test, dan mag je namen en formules wijzigen, maar niet het aantal
    onderdelen, hun volgorde/soort, of het totaal aan- of uitzetten (de eenheid van de hoofdwaarde).
    """
    test = db.test_op_sjabloon(oud.slug) or db.test_op_naam(oud.naam)
    if test is None or not db.aantal_testresultaten(test.id):
        return
    problemen = []
    if [o.soort for o in oud.onderdelen] != [o.soort for o in nieuw.onderdelen]:
        problemen.append("Er zijn al resultaten met deze test: het aantal onderdelen en hun soort (lengte, tijd, "
                         "gewicht) en volgorde kunnen niet meer worden gewijzigd. Maak er een nieuwe test van "
                         "(andere naam) als je dat wilt.")
    if hoofd_eenheid(oud) != hoofd_eenheid(nieuw):
        problemen.append("Er zijn al resultaten met deze test: het totaal optellen kan niet meer worden aan- of "
                         "uitgezet.")
    if problemen:
        raise SjabloonFout(problemen)


def sjabloon_opslaan(db: Opslag, s: Sjabloon, datamap: Path | str | None = None, *,
                     bibliotheek: Bibliotheek | None = None) -> Sjabloon:
    """Bewaar een (nieuw of aangepast) sjabloon als YAML; weigert wijzigingen die bestaande resultaten breken."""
    s.controleer()
    bib = bibliotheek or sj.laad_bibliotheek(datamap)
    oud = bib.vind(s.slug)
    if oud is not None:
        wijziging_toegestaan(db, oud.sjabloon, s)
    bewaard = sj.opslaan(s, datamap, bibliotheek=bib)
    test = db.test_op_sjabloon(bewaard.slug)
    if test is not None:                                  # naam en eenheid van de test volgen het sjabloon
        test_voor_sjabloon(db, bewaard)
    return bewaard


def sjabloon_verwijderen(db: Opslag, slug: str, datamap: Path | str | None = None) -> bool:
    """Verwijder een eigen sjabloon, als er geen resultaten op zijn. SjabloonFout als dat niet kan."""
    test = db.test_op_sjabloon(slug)
    if test is not None and db.aantal_testresultaten(test.id):
        raise SjabloonFout("Er zijn al resultaten met deze test; het sjabloon blijft bewaard.")
    if test is not None:
        db.test_verwijderen(test.id)
    return sj.verwijderen(slug, datamap)


# ------------------------------------------------------------------ vastleggen
def resultaat_vastleggen(db: Opslag, master_id: str, s: Sjabloon, datum: date, invoer: Sequence[str | float | None],
                         notities: str | None = None) -> Testresultaat:
    """Leg een resultaat vast: één invoer per onderdeel van het sjabloon (leeg = niet gedaan).

    Rekent de scores uit. OpslagFout met uitleg als de invoer niet klopt; er wordt dan niets opgeslagen.
    Met een totaalscore moeten alle onderdelen met een formule zijn ingevuld.
    """
    if db.atleet(master_id) is None:
        raise OpslagFout("Onbekende atleet.")
    if datum > date.today():
        raise OpslagFout("De datum mag niet in de toekomst liggen.")
    if len(invoer) != len(s.onderdelen):
        raise OpslagFout(f"Verwacht {len(s.onderdelen)} resultaten, kreeg er {len(invoer)}.")
    waarden: list[float | None] = []
    for o, ruw in zip(s.onderdelen, invoer):
        try:
            waarden.append(lees_waarde(ruw))
        except ValueError:
            raise OpslagFout(f"{o.naam}: '{ruw}' is geen geldig getal ({o.eenheid}).") from None
    if all(w is None for w in waarden):
        raise OpslagFout("Vul minstens één resultaat in.")
    if s.telt_totaal:
        ontbreekt = [o.naam for o, w in zip(s.onderdelen, waarden) if o.heeft_formule and w is None]
        if ontbreekt:
            raise OpslagFout("Voor de totaalscore moeten alle onderdelen met een score zijn ingevuld; "
                             f"nog leeg: {', '.join(ontbreekt)}.")
    try:
        scores, totaal = s.scores(waarden)
    except FormuleFout as e:
        raise OpslagFout(f"De score kan niet worden uitgerekend: {e}") from None
    ingevuld = [i for i, w in enumerate(waarden) if w is not None]
    hoofd = totaal if s.telt_totaal else waarden[ingevuld[0]]
    losse_score = next((sc for sc in scores if sc is not None), None) if s.aantal_formules == 1 else None
    test = test_voor_sjabloon(db, s)
    r = Testresultaat(master_id, test.id, datum, hoofd, (notities or "").strip() or None,
                      score=totaal if s.telt_totaal else losse_score,
                      delen=[TestDeel(i, waarden[i], scores[i]) for i in ingevuld])
    return db.testresultaat_opslaan(r)


# ------------------------------------------------------------------ weergeven
@dataclass
class DeelRegel:
    naam: str
    eenheid: str
    waarde: float
    score: float | None


@dataclass
class ResultaatRegel:
    resultaat: Testresultaat
    test: Test
    sjabloon: Sjabloon | None            # None = test zonder (of met verdwenen) sjabloon
    delen: list[DeelRegel] = field(default_factory=list)

    @property
    def is_totaal(self) -> bool:
        return self.sjabloon is not None and self.sjabloon.telt_totaal


def resultaatregels(db: Opslag, master_id: str, *, datamap: Path | str | None = None,
                    bibliotheek: Bibliotheek | None = None, test_id: int | None = None) -> list[ResultaatRegel]:
    """De resultaten van een atleet, nieuwste eerst, met de namen en eenheden uit het sjabloon."""
    bib = bibliotheek or sj.laad_bibliotheek(datamap)
    testen = {t.id: t for t in db.testen()}
    uit = []
    for r in reversed(db.testresultaten(master_id, test_id)):
        test = testen[r.test_id]
        bron = bib.vind(test.sjabloon)
        s = bron.sjabloon if bron else None
        delen = []
        for d in r.delen:
            if s is not None and d.deel < len(s.onderdelen):
                o = s.onderdelen[d.deel]
                delen.append(DeelRegel(o.naam, o.eenheid, d.waarde, d.score))
            else:                                          # sjabloon weg of korter: toch tonen wat er is
                delen.append(DeelRegel(f"Onderdeel {d.deel + 1}", "", d.waarde, d.score))
        uit.append(ResultaatRegel(r, test, s, delen))
    return uit
