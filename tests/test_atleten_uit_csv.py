"""Tests voor src/groepen/atleten_uit_csv.py.

Gebruikt de geanonimiseerde profielpagina uit tests/fixtures/ en een tijdelijke map met
een vaste testsleutel: raakt atletiek.nu, de sleutelkluis en data/ nooit aan.
"""

import tempfile
from pathlib import Path

from atleten import beheer
from groepen.atleten_uit_csv import (
    BevestigingNodig, lees_csv, lees_datum, lees_licentienummer, importeer_regels, maak_bevestig, schrijf_mislukt,
    splits_naam, veld_van_kop,
)
from importers.base import ImportFout
from hulp import opslag

PROFIEL = (Path(__file__).parent / "fixtures" / "atletieknu_profiel.html").read_text(encoding="utf-8")


def stil(_):
    pass


# ----------------------------------------------------------------- lezen

def test_splits_naam():
    assert splits_naam("Test de Vries") == ("Test", "de", "Vries")
    assert splits_naam("Test van der Berg") == ("Test", "van der", "Berg")
    assert splits_naam("Anne Marie Jansen") == ("Anne Marie", None, "Jansen")
    assert splits_naam("Vries, Test de") == ("Test", "de", "Vries")
    assert splits_naam("de Vries, Test") == ("Test", "de", "Vries")
    assert splits_naam("Test Smit-Jansen") == ("Test", None, "Smit-Jansen")
    try:
        splits_naam("Alleen")
        raise AssertionError("ValueError verwacht")
    except ValueError:
        pass


def test_lees_datum():
    assert lees_datum("25-03-2011") == "2011-03-25"
    assert lees_datum("5/3/2011") == "2011-03-05"
    assert lees_datum("2011-03-25") == "2011-03-25"
    assert lees_datum("2011-03-25 00:00:00") == "2011-03-25"
    assert lees_datum("2011") == "2011"
    assert lees_datum("31-02-2011") is None
    assert lees_datum("123456") is None


def test_csv_met_kopregel_aparte_kolommen():
    tekst = ("Voornaam;Tussenvoegsel;Achternaam;Geboortedatum;Atletiek.nu nummer\n"
             "Test;de;Vries;25-03-2011;999999\n"
             "Proef;;Jansen;2012;https://www.atletiek.nu/atleet/profiel/888888/\n"
             "\n"
             "Fout;;Persoon;;\n")
    lees = lees_csv("x.csv", tekst=tekst)
    assert [r.atletieknu_id for r in lees.regels] == ["999999", "888888"]
    r = lees.regels[0]
    assert (r.voornaam, r.tussenvoegsel, r.achternaam, r.geboortedatum) == ("Test", "de", "Vries", "2011-03-25")
    assert lees.regels[1].tussenvoegsel is None and lees.regels[1].geboortedatum == "2012"
    assert len(lees.fouten) == 1 and lees.fouten[0][0] == 5     # regelnummer in het bestand


def test_csv_met_naam_in_een_kolom_en_geslacht():
    lees = lees_csv("x.csv", tekst="naam;geb.datum;geslacht;atletieknu\nTest van Dijk;01-01-2010;meisje;999999\n")
    r = lees.regels[0]
    assert (r.voornaam, r.tussenvoegsel, r.achternaam, r.geslacht) == ("Test", "van", "Dijk", "V")


def test_csv_zonder_kopregel():
    lees = lees_csv("x.csv", tekst="Test;de;Vries;25-03-2011;999999\nProef;;Jansen;2012-01-01;888888\n")
    assert lees.kopregel is None and not lees.fouten
    assert [(r.achternaam, r.atletieknu_id) for r in lees.regels] == [("Vries", "999999"), ("Jansen", "888888")]

    lees = lees_csv("x.csv", tekst="999999;Test de Vries;2011\n")
    r = lees.regels[0]
    assert (r.voornaam, r.tussenvoegsel, r.achternaam, r.geboortedatum) == ("Test", "de", "Vries", "2011")


def test_csv_fouten():
    lees = lees_csv("x.csv", tekst="naam,geboortedatum,id\nTest de Vries,2011,999999\n")
    assert not lees.regels and "scheidingsteken" in lees.fouten[0][1]

    lees = lees_csv("x.csv", tekst="naam;geboortedatum\nTest de Vries;2011\n")
    assert not lees.regels and "atletiek.nu-nummer" in lees.fouten[0][1]

    lees = lees_csv("x.csv", tekst="naam;geboortedatum;atletieknu\nA de B;2011;999999\nC de D;gisteren;888888\n"
                                   "E de F;2011;999999\n")
    assert len(lees.regels) == 1
    assert "geboortedatum" in lees.fouten[0][1] and "regel 2" in lees.fouten[1][1]


def test_csv_met_licentienummer():
    for kop in ("Licentienummer", "AU-licentie", "Licentie nr", "Atletiekunie licentienummer", "AU nummer"):
        assert veld_van_kop(kop) == "au_licentienummer", kop
    assert veld_van_kop("Atletiek.nu nummer") == "atletieknu_id"
    assert lees_licentienummer(" 12 34 567 ") == "1234567" and lees_licentienummer("1234567.0") == "1234567"
    assert lees_licentienummer("") is None
    tekst = ("naam;atletieknu;licentienummer\n"
             "Test de Vries;999999;1234567\n"
             "Proef Jansen;888888;\n"
             "Fout Een;777777;AU-12\n"
             "Fout Twee;666666;1234567\n")
    lees = lees_csv("x.csv", tekst=tekst)
    assert [(r.atletieknu_id, r.au_licentienummer) for r in lees.regels] == [("999999", "1234567"), ("888888", None)]
    assert [n for n, _ in lees.fouten] == [4, 5]
    assert "alleen cijfers" in lees.fouten[0][1] and "regel 2" in lees.fouten[1][1]
    # Zonder kopregel wordt geen licentienummer gelezen (niet te onderscheiden van het atletiek.nu-nummer).
    assert lees_csv("x.csv", tekst="Test de Vries;999999\n").regels[0].au_licentienummer is None


# ----------------------------------------------------------------- importeren

def test_importeer_en_opnieuw():
    lees = lees_csv("x.csv", tekst="voornaam;tussenvoegsel;achternaam;geboortedatum;atletieknu\n"
                                   "Test;de;Vries;25-03-2011;999999\n")
    with opslag() as db:
        v = importeer_regels(db, lees.regels, haal_html=lambda _: PROFIEL, log=stil)
        assert len(v.gelukt) == 1 and not v.mislukt
        regel, u = v.gelukt[0]
        assert u.status == "nieuw" and u.nieuw == 2
        opgeslagen = db.atleet(u.atleet.master_id)
        assert opgeslagen.geboortedatum == "2011-03-25" and opgeslagen.atletieknu_id == "999999"

        v2 = importeer_regels(db, lees.regels, haal_html=lambda _: PROFIEL, log=stil)
        assert v2.gelukt[0][1].status == "bestond" and v2.gelukt[0][1].nieuw == 0
        assert len(db.atleten(alleen_actief=False)) == 1


def test_fout_bij_een_atleet_stopt_de_rest_niet():
    lees = lees_csv("x.csv", tekst="naam;atletieknu\nTest de Vries;111111\nProef Jansen;999999\n")

    def haal(nummer):
        if nummer == "111111":
            raise ImportFout("atletiek.nu gaf een browsercontrole-pagina terug.\nmeer uitleg")
        return PROFIEL

    with opslag() as db:
        v = importeer_regels(db, lees.regels, haal_html=haal, log=stil)
        assert [r.atletieknu_id for r, _ in v.gelukt] == ["999999"]
        assert [r.atletieknu_id for r, _ in v.mislukt] == ["111111"]
        assert len(db.atleten(alleen_actief=False)) == 1       # mislukte atleet niet half aangemaakt

    with tempfile.TemporaryDirectory() as tmp:
        pad = schrijf_mislukt(Path(tmp) / "x_mislukt.csv", lees, v)
        inhoud = pad.read_text(encoding="utf-8-sig").splitlines()
        assert inhoud[0] == "naam;atletieknu;reden"
        assert inhoud[1].startswith("Test de Vries;111111;atletiek.nu gaf")
        assert lees_csv(pad).regels[0].atletieknu_id == "111111"   # opnieuw te gebruiken


def test_bestaande_atleet_krijgt_nummer_en_geboortedatum():
    lees = lees_csv("x.csv", tekst="naam;geboortedatum;atletieknu\nTest Jansen;2011-05-01;999999\n")
    with opslag() as db:
        oud = beheer.nieuwe_atleet(db, "Test", "Jansen")
        v = importeer_regels(db, lees.regels, haal_html=lambda _: PROFIEL, bevestig=maak_bevestig("ja"), log=stil)
        assert v.gelukt[0][1].status == "id_toegevoegd"
        opgeslagen = db.atleet(oud.master_id)
        assert (opgeslagen.atletieknu_id, opgeslagen.geboortedatum) == ("999999", "2011-05-01")


def test_zonder_toetsenbord_wordt_dubbele_naam_overgeslagen():
    lees = lees_csv("x.csv", tekst="naam;atletieknu\nTest Jansen;999999\n")

    def bevestig(_):
        raise BevestigingNodig("er bestaat al een atleet met deze naam")

    with opslag() as db:
        beheer.nieuwe_atleet(db, "Test", "Jansen")
        v = importeer_regels(db, lees.regels, haal_html=lambda _: PROFIEL, bevestig=bevestig, log=stil)
        assert not v.gelukt and len(v.mislukt) == 1
        assert len(db.atleten(alleen_actief=False)) == 1


def test_importeer_licentienummer():
    with opslag() as db:
        lees = lees_csv("x.csv", tekst="naam;atletieknu;licentie\nTest de Vries;999999;1234567\n")
        v = importeer_regels(db, lees.regels, haal_html=lambda _: PROFIEL, log=stil)
        assert len(v.gelukt) == 1
        a = db.atleet_op_au_licentienummer("1234567")
        assert a.atletieknu_id == "999999" and a.naam == "Test de Vries"
        # Opnieuw met hetzelfde nummer: dezelfde atleet, niets aan de hand.
        assert len(importeer_regels(db, lees.regels, haal_html=lambda _: PROFIEL, log=stil).gelukt) == 1
        # Een bestaande licentie wordt niet overschreven.
        lees2 = lees_csv("x.csv", tekst="naam;atletieknu;licentie\nTest de Vries;999999;7654321\n")
        importeer_regels(db, lees2.regels, haal_html=lambda _: PROFIEL, log=stil)
        assert db.atleet(a.master_id).au_licentienummer == "1234567"


def test_licentie_van_een_ander_wordt_niet_geimporteerd():
    with opslag() as db:
        bas = beheer.nieuwe_atleet(db, "Bas", "Proef", au_licentienummer="1234567")
        opgehaald = []
        lees = lees_csv("x.csv", tekst="naam;atletieknu;licentie\nTest de Vries;999999;1234567\n")
        v = importeer_regels(db, lees.regels, haal_html=lambda n: opgehaald.append(n) or PROFIEL, log=stil)
        assert not v.gelukt and "Bas Proef" in v.mislukt[0][1] and "atletiek.nu-nummer in" in v.mislukt[0][1]
        assert opgehaald == [] and db.atleet_op_atletieknu_id("999999") is None   # niets half opgeslagen
        bas.atletieknu_id = "555555"
        db.atleet_opslaan(bas)
        v = importeer_regels(db, lees.regels, haal_html=lambda _: PROFIEL, log=stil)
        assert "555555" in v.mislukt[0][1]
