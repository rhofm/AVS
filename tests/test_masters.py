"""Masters (35+): categorie van een atleet (M35, V40, ...) en welke regels van een tijdschema bij hem horen.

Alleen nepgegevens.
"""

from datetime import date

import pytest

from atleten import landingspagina
from models import Atleet, ProgrammaOnderdeel, lees_categorie
from wedstrijden import chronoloog

DAG = date(2026, 10, 16)


def cat(geboortedatum: str, op: date = DAG) -> str | None:
    return landingspagina.leeftijdscategorie(Atleet("A", "B", geboortedatum=geboortedatum), op)


def test_masters_vanaf_35_op_de_peildatum():
    assert cat("1988-05-01") == "Masters 35"       # 38
    assert cat("1991-10-16") == "Masters 35"       # wordt vandaag 35
    assert cat("1991-10-17") == "Senior"           # morgen 35
    assert cat("1992-12-31") == "Senior"           # 33
    assert cat("1991") == "Masters 35"             # alleen het jaar: verschil in jaren, zoals elders
    assert cat("1996") == "Senior"
    assert cat("2011-03-14") == "U16"              # jeugd verandert niet


def test_klassen_van_vijf_jaar():
    assert cat("1986-10-16") == "Masters 40"       # 40 vandaag
    assert cat("1982-01-01") == "Masters 40"       # 44
    assert cat("1981-01-01") == "Masters 45"       # 45
    assert cat("1941-01-01") == "Masters 85"       # 85
    assert cat("1966-01-01") == "Masters 60"       # 60
    assert cat("1920-01-01") == "Masters 95"       # 106: de laatste klasse is 95+


def test_code_is_m35_v40_en_teksten():
    assert landingspagina.categorie_code("Masters 35", "M") == "M35"
    assert landingspagina.categorie_code("Masters 40", "V") == "V40"
    assert landingspagina.categorie_code("Masters 85", "M") == "M85"
    assert landingspagina.categorie_code("Masters 60", "V") == "V60"
    assert landingspagina.categorie_code("Masters 40", None) == "Masters 40"
    assert landingspagina.categorie_code("Senior", "M") == "SenM"
    assert landingspagina.geslacht_tekst("V", "Masters 40") == "Vrouw"
    assert landingspagina.categorie_groep("Masters 40", "M") == "mannen"


def test_categorieen_in_volgorde():
    c = landingspagina.CATEGORIEEN
    assert c[:8] == ("U8", "U10", "U12", "U14", "U16", "U18", "U20", "Senior")
    assert c[8] == "Masters 35" and c[-1] == "Masters 95" and len(c) == 8 + 13


@pytest.mark.parametrize("tekst, verwacht", [
    ("M35", ("Masters 35", "M")), ("V40", ("Masters 40", "V")), ("M85", ("Masters 85", "M")),
    ("V60", ("Masters 60", "V")), ("M 50", ("Masters 50", "M")), ("V35+", ("Masters 35+", "V")),
    ("Masters V45", ("Masters 45", "V")), ("Masters-M", ("Masters", "M")), ("Masters", ("Masters", None)),
    ("MU16", ("U16", "V")), ("VU20+V Masters", ("U20", "V")), ("SEN-M", ("Senior", "M")),
    ("M30", (None, None)), ("100m", (None, None)),
])
def test_lees_categorie_masters(tekst, verwacht):
    assert lees_categorie(tekst) == verwacht


def _regel(categorie: str | None) -> ProgrammaOnderdeel:
    return ProgrammaOnderdeel(1, DAG, "10:00", None, "Kogelstoten", categorie)


@pytest.mark.parametrize("tekst, verwacht", [
    ("M40", True), ("M35", False), ("M45", False), ("V40", False),          # eigen klasse en geslacht
    ("M35+", True), ("M40+", True), ("M45+", False),                        # vanaf een klasse
    ("Masters-M", True), ("SEN-M", True), ("Mannen", True), ("U16-M", False),
    ("Masters-V", False), ("Vrouwen", False),
])
def test_masters_40_man_en_de_regels(tekst, verwacht):
    assert chronoloog.past_bij(_regel(tekst), "Masters 40", "M") is verwacht, tekst


def test_senioren_horen_niet_bij_masters_regels():
    for tekst in ("Masters-M", "M35", "M35+"):
        assert chronoloog.past_bij(_regel(tekst), "Senior", "M") is False, tekst
    assert chronoloog.past_bij(_regel("SEN-M"), "Senior", "M") is True


def test_klasse_onbekend_zoals_de_ploeg_hem_geeft():
    # ploeg.tijdschema geeft 'Masters' zonder klasse door: dan telt elke masters-regel (zoals eerder)
    for tekst in ("M45", "V35+", "Masters-M", "SEN-M"):
        assert chronoloog.past_bij(_regel(tekst), "Masters", "M") is not False, tekst
