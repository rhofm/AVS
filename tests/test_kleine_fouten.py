"""Kleine fouten uit de codereview (1.8): rare cijfers in formulieren, jokers in de zoekfunctie,
een wedstrijd op link opzoeken en sjablonen zonder `| safe`. Alleen nepgegevens."""

from datetime import date

from atleten import beheer, nieuw
from groepen.atleten_uit_csv import lees_atletieknu_id
from importers.atletieknu_prs import atleet_id_uit
from models import Atleet, Wedstrijd
from voorbeeld_atleet import client
from hulp import opslag, tekst


# ---------------- cijfers die geen gewone cijfers zijn ----------------
def test_superscript_in_de_link_geeft_geen_crash():
    """'²'.isdigit() is True, maar int('²') faalt: dat gaf een fout 500."""
    with client() as (c, _mid, _tmp):
        assert c.get("/atleten?groep=²").status_code == 200
        assert c.get("/atleten?groep=①").status_code == 200


def test_opgeslagen_nummers_alleen_gewone_cijfers():
    assert atleet_id_uit("123456") == "123456"
    assert atleet_id_uit("١٢٣٤٥٦") == ""                       # Arabisch-Indische cijfers: geen id
    assert atleet_id_uit("https://www.atletiek.nu/atleet/profiel/١٢٣/") == ""
    assert lees_atletieknu_id("123456.0") == "123456" and lees_atletieknu_id("١٢٣") == ""
    with opslag() as db:
        form = {"voornaam": "Test", "achternaam": "Proef", "geslacht": "V",
                "atletieknu_id": "١٢٣", "au_licentienummer": "١٢٣٤٥٦٧"}
        try:
            nieuw.lees_formulier(db, form)
            raise AssertionError("had geweigerd moeten worden")
        except nieuw.InvoerFout as e:
            assert set(e.fouten) >= {"atletieknu_id", "au_licentienummer"}
    try:
        Atleet("Test", "Proef", au_licentienummer="١٢٣")
        raise AssertionError("had geweigerd moeten worden")
    except ValueError:
        pass


# ---------------- zoeken: % en _ zijn gewone tekens ----------------
def test_zoeken_zonder_jokers():
    with opslag() as db:
        beheer.nieuwe_atleet(db, "Anna", "Voorbeeld")
        beheer.nieuwe_atleet(db, "Bas", "Proef_Mans")
        assert db.atleten_zoeken("%") == []                     # was: iedereen
        assert [a.achternaam for a in db.atleten_zoeken("_")] == ["Proef_Mans"]
        assert [a.voornaam for a in db.atleten_zoeken("nna voor")] == ["Anna"]
        assert db.atleten_zoeken("!") == []


# ---------------- wedstrijd op link ----------------
def test_wedstrijd_op_link():
    with opslag() as db:
        w = db.wedstrijd_opslaan(Wedstrijd("Testmeeting", date(2026, 6, 1),
                                           bron_url="https://www.atletiek.nu/wedstrijd/main/1/"))
        assert db.wedstrijd_op_link("https://www.atletiek.nu/wedstrijd/main/1/").id == w.id
        assert db.wedstrijd_op_link("https://www.atletiek.nu/wedstrijd/main/2/") is None
        again = db.wedstrijd_opslaan(Wedstrijd("Zelfde link", date(2026, 6, 1),
                                               bron_url="https://www.atletiek.nu/wedstrijd/main/1/"))
        assert again.id == w.id                                  # hergebruikt, geen dubbele


# ---------------- sjablonen zonder | safe ----------------
def test_atleetformulier_attributen():
    with client() as (c, _mid, _tmp):
        html = tekst(c.get("/atleten/nieuw"))
        assert 'name="voornaam" value="" required autocomplete="off" autofocus>' in html
        assert 'placeholder="bijv. van der"' in html and 'list="specialisaties"' in html
        assert html.count('inputmode="numeric"') >= 3          # id, licentie en geboortejaar
        assert html.count('autocomplete="off"') >= 7
