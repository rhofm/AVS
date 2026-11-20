"""Tests voor een nieuwe wedstrijd (van een link of met de hand), gegevens wijzigen en
het tijdschema bijwerken: wedstrijden.tijdschema_import.wedstrijd_uit_link,
wedstrijden.detail.gegevens_opslaan en de routes /wedstrijden/nieuw,
/wedstrijd/<id>/bewerken en /wedstrijd/<id>/tijdschema.

Er wordt niets van internet gehaald: de importer leest een opgeslagen, geanonimiseerde
pagina (fixtures/atletieknu_tijdschema/meerkamp.html: 'Testmeerkamp 2026', Proefdorp,
29 en 30 augustus 2026, 15 regels).
"""

import contextlib
from datetime import date
from pathlib import Path

from test_tijdschema_import import MEERKAMP, NepImporter

from atleten import beheer
from db.queries import OpslagFout
from models import Onderdeel
from wedstrijden import detail, planning, tijdschema_import
from wedstrijden.detail import Gegevens
from hulp import app_client, lege_opslag, verwacht as _verwacht

LINK = "https://www.atletiek.nu/wedstrijd/main/45678/"
GENORMALISEERD = "https://www.atletiek.nu/wedstrijd/uitslagen/45678/"
BROWSERCONTROLE = "<html><body>Checking your browser</body></html>"


@contextlib.contextmanager
def opslag():
    with lege_opslag() as (db, tmp):
        db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
        yield db, Path(tmp)


@contextlib.contextmanager
def nep_site(inhoud: str | None = None):
    """Laat tijdschema_import de opgeslagen pagina lezen in plaats van atletiek.nu."""
    echt = tijdschema_import._ophalen

    def nep(bron, wedstrijd=None, importer=None):
        return echt(bron, wedstrijd, importer or NepImporter(MEERKAMP, inhoud))
    tijdschema_import._ophalen = nep
    try:
        yield
    finally:
        tijdschema_import._ophalen = echt


# ---------------------------------------------------------------- van een link

def test_wedstrijd_uit_link():
    with opslag() as (db, _):
        n = tijdschema_import.wedstrijd_uit_link(db, LINK, importer=NepImporter(MEERKAMP))
        w = n.wedstrijd
        assert not n.bestond and w.id is not None
        assert (w.naam, w.datum, w.locatie) == ("Testmeerkamp 2026", date(2026, 8, 29), "Proefdorp")
        assert w.bron_url == GENORMALISEERD and w.bron == "atletieknu" and not w.indoor
        assert n.verslag.aantal == 15 and len(db.programma(w.id)) == 15

        # Zelfde wedstrijd (andere pagina van dezelfde wedstrijd): geen dubbele, gegevens blijven.
        detail.gegevens_opslaan(db, w.id, Gegevens("Mijn naam", "2026-08-29", "Proefdorp", GENORMALISEERD))
        n2 = tijdschema_import.wedstrijd_uit_link(db, "https://www.atletiek.nu/wedstrijd/chronoloog/45678/",
                                                  importer=NepImporter(MEERKAMP))
        assert n2.bestond and n2.wedstrijd.id == w.id and n2.wedstrijd.naam == "Mijn naam"
        assert len(db.wedstrijden()) == 1


def test_wedstrijd_uit_link_fouten():
    with opslag() as (db, _):
        _verwacht(OpslagFout, lambda: tijdschema_import.wedstrijd_uit_link(db, "  "))
        _verwacht(OpslagFout, lambda: tijdschema_import.wedstrijd_uit_link(db, "https://example.com/wedstrijd"))
        _verwacht(OpslagFout, lambda: tijdschema_import.wedstrijd_uit_link(
            db, LINK, importer=NepImporter(MEERKAMP, BROWSERCONTROLE)))
        assert db.wedstrijden() == []                                   # niets half aangemaakt


# ---------------------------------------------------------------- gegevens

def test_gegevens_opslaan():
    with opslag() as (db, _):
        w = detail.gegevens_opslaan(db, None, Gegevens("  Club  kampioenschappen ", "2027-05-15", "Nijmegen"))
        assert (w.naam, w.datum, w.locatie, w.bron_url, w.bron) == (
            "Club kampioenschappen", date(2027, 5, 15), "Nijmegen", None, "handmatig")
        w = detail.gegevens_opslaan(db, w.id, Gegevens("Clubkampioenschappen", "2027-05-16", "", LINK, True))
        w = db.wedstrijd(w.id)
        assert (w.naam, w.datum, w.locatie, w.bron_url, w.bron, w.indoor) == (
            "Clubkampioenschappen", date(2027, 5, 16), None, GENORMALISEERD, "atletieknu", True)
        ander = planning.plan_wedstrijd(db, "Andere", date(2027, 6, 1))
        _verwacht(OpslagFout, lambda: detail.gegevens_opslaan(db, ander.id, Gegevens("Andere", "2027-06-01", link=LINK)))
        _verwacht(OpslagFout, lambda: detail.gegevens_opslaan(db, None, Gegevens("", "2027-06-01")))
        _verwacht(OpslagFout, lambda: detail.gegevens_opslaan(db, None, Gegevens("X", "15-05-2027")))
        _verwacht(OpslagFout, lambda: detail.gegevens_opslaan(db, None, Gegevens("X", "2027-06-01", link="C:/pad")))
        _verwacht(OpslagFout, lambda: detail.gegevens_opslaan(db, 999, Gegevens("X", "2027-06-01")))


# ---------------------------------------------------------------- pagina's

def test_nieuw_pagina():
    with opslag() as (db, tmp):
        c = app_client(tmp)
        html = c.get("/wedstrijden/nieuw").get_data(as_text=True)
        assert "Deze pagina komt nog" not in html
        assert 'name="soort" value="link"' in html and 'name="soort" value="hand"' in html
        assert "Ophalen en verder" in html and "Of met de hand invullen" in html


def test_nieuw_van_link_route():
    with opslag() as (db, tmp):
        c = app_client(tmp)
        with nep_site():
            r = c.post("/wedstrijden/nieuw", data={"soort": "link", "link": LINK, "indoor": "1"})
        assert r.status_code == 302
        w = db.wedstrijden()[0]
        assert r.headers["Location"].endswith(f"/wedstrijd/{w.id}/inschrijven") and w.indoor
        html = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Wedstrijd Testmeerkamp 2026 (2026-08-29) aangemaakt" in html and "Schrijf nu de atleten in" in html
        # Nog een keer dezelfde link: geen tweede wedstrijd.
        with nep_site():
            r = c.post("/wedstrijden/nieuw", data={"soort": "link", "link": LINK})
        assert "stond er al" in c.get(r.headers["Location"]).get_data(as_text=True) and len(db.wedstrijden()) == 1
        # Site geeft een browsercontrole: foutmelding, link blijft staan, niets aangemaakt.
        with nep_site(BROWSERCONTROLE):
            r = c.post("/wedstrijden/nieuw", data={"soort": "link", "link": "https://www.atletiek.nu/wedstrijd/main/1/"})
        html = r.get_data(as_text=True)
        assert r.status_code == 400 and "Niet gelukt" in html and 'value="https://www.atletiek.nu/wedstrijd/main/1/"' in html
        assert len(db.wedstrijden()) == 1


def test_nieuw_met_de_hand_route():
    with opslag() as (db, tmp):
        c = app_client(tmp)
        r = c.post("/wedstrijden/nieuw", data={"soort": "hand", "naam": "Clubkampioenschappen",
                                               "datum": "2027-05-15", "locatie": "Nijmegen", "link": ""})
        assert r.status_code == 302 and "/inschrijven" in r.headers["Location"]
        assert "Wedstrijd Clubkampioenschappen aangemaakt" in c.get(r.headers["Location"]).get_data(as_text=True)
        # Fout: alles blijft ingevuld en het formulier staat open.
        r = c.post("/wedstrijden/nieuw", data={"soort": "hand", "naam": "Tweede", "datum": "", "locatie": "Ergens"})
        html = r.get_data(as_text=True)
        assert r.status_code == 400 and "geldige datum" in html
        assert 'value="Tweede"' in html and 'value="Ergens"' in html and '<details class="blok handmatig" open>' in html


def test_bewerken_route():
    with opslag() as (db, tmp):
        w = planning.plan_wedstrijd(db, "Clubkampioenschappen", date(2027, 5, 15), "Nijmegen")
        c = app_client(tmp)
        html = c.get(f"/wedstrijd/{w.id}").get_data(as_text=True)
        assert f'href="/wedstrijd/{w.id}/bewerken">Gegevens wijzigen</a>' in html
        assert "Tijdschema bijwerken" not in html                       # geen link: veld om er een te plakken
        html = c.get(f"/wedstrijd/{w.id}/bewerken").get_data(as_text=True)
        assert 'value="Clubkampioenschappen"' in html and 'value="2027-05-15"' in html
        r = c.post(f"/wedstrijd/{w.id}/bewerken", data={"naam": "CK", "datum": "2027-05-16", "locatie": "Arnhem",
                                                       "link": LINK, "indoor": "1"})
        assert r.status_code == 302
        w2 = db.wedstrijd(w.id)
        assert (w2.naam, w2.datum, w2.locatie, w2.bron_url, w2.indoor) == ("CK", date(2027, 5, 16), "Arnhem",
                                                                           GENORMALISEERD, True)
        assert "Gegevens opgeslagen." in c.get(r.headers["Location"]).get_data(as_text=True)
        # Fout: blijft op het formulier met de ingevulde waarden.
        r = c.post(f"/wedstrijd/{w.id}/bewerken", data={"naam": "", "datum": "2027-05-16"})
        assert r.status_code == 400 and "Geef de wedstrijd een naam" in r.get_data(as_text=True)
        # Opslaan en meteen het tijdschema bijwerken.
        with nep_site():
            r = c.post(f"/wedstrijd/{w.id}/bewerken", data={"naam": "CK", "datum": "2026-08-29",
                                                           "link": LINK, "bijwerken": "1"})
        assert "Tijdschema geïmporteerd: 15 regels" in c.get(r.headers["Location"]).get_data(as_text=True)
        assert c.get("/wedstrijd/999/bewerken").status_code == 404


def test_tijdschema_knop():
    with opslag() as (db, tmp):
        w = planning.plan_wedstrijd(db, "Testmeerkamp", date(2026, 8, 29), link=LINK)
        c = app_client(tmp)
        html = c.get(f"/wedstrijd/{w.id}").get_data(as_text=True)
        assert ">Tijdschema importeren</button>" in html                 # bovenaan, met de bewaarde link
        with nep_site():
            r = c.post(f"/wedstrijd/{w.id}/tijdschema")
        html = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Tijdschema geïmporteerd: 15 regels" in html and ">Tijdschema bijwerken</button>" in html
        with nep_site(BROWSERCONTROLE):
            r = c.post(f"/wedstrijd/{w.id}/tijdschema")
        assert r.status_code == 400 and "Tijdschema niet geïmporteerd" in r.get_data(as_text=True)
        assert len(db.programma(w.id)) == 15                              # oude tijdschema blijft staan

        # Wedstrijd zonder link: link plakken, importeren en (aangevinkt) bewaren.
        los = planning.plan_wedstrijd(db, "Los", date(2026, 8, 29))
        assert 'name="bewaar"' in c.get(f"/wedstrijd/{los.id}").get_data(as_text=True)
        with nep_site():
            c.post(f"/wedstrijd/{los.id}/tijdschema",
                   data={"link": "https://www.atletiek.nu/wedstrijd/main/777/", "bewaar": "1"})
        assert db.wedstrijd(los.id).bron_url == "https://www.atletiek.nu/wedstrijd/uitslagen/777/"
        assert len(db.programma(los.id)) == 15


def test_inschrijven_na_nieuw():
    """Na het aanmaken kun je direct inschrijven; het tijdschema bepaalt de onderdelen."""
    with opslag() as (db, tmp):
        anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2008").master_id
        n = tijdschema_import.wedstrijd_uit_link(db, LINK, importer=NepImporter(MEERKAMP))
        c = app_client(tmp)
        r = c.post(f"/wedstrijd/{n.wedstrijd.id}/inschrijven", data={"atleet": [anna], "onderdeel": []})
        assert r.status_code == 302
        assert "Anna Voorbeeld" in c.get(f"/wedstrijd/{n.wedstrijd.id}").get_data(as_text=True)
