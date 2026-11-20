"""Tests voor de startpagina (src/ui/startpagina.py en de route /).

Tijdelijke map met versleutelde databases, vaste testsleutel, alleen nepgegevens.

"""

import contextlib
import re
from datetime import timedelta
from pathlib import Path

from test_landingspagina import VANDAAG, voorbeeld

from models import Onderdeel
from ui import startpagina
from hulp import app_client, lege_opslag


@contextlib.contextmanager
def opslag(met_voorbeeld: bool = True):
    with lege_opslag() as (db, tmp):
        if met_voorbeeld:
            db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
            db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
            voorbeeld(db)
        yield db, Path(tmp)


def test_tegels_volgorde_en_cijfers():
    with opslag() as (db, _):
        t = startpagina.tegels(db, VANDAAG)
        assert [x.sleutel for x in t] == ["atleten", "groepen", "ploegen", "wedstrijden"]
        atleten, groepen, ploegen, wedstrijden = t
        assert (atleten.cijfer, atleten.cijfer_label) == ("1", "actieve atleet")
        assert (groepen.cijfer, groepen.cijfer_label) == ("1", "groep")
        assert (ploegen.cijfer, ploegen.cijfer_label) == ("0", "komende ploegen")
        # 'Vorig seizoen' ligt in het verleden en telt niet mee.
        assert (wedstrijden.cijfer, wedstrijden.cijfer_label) == ("2", "komende wedstrijden")
        assert wedstrijden.extra.startswith("Eerstvolgende: Clubkampioenschappen")
        # Na de laatste wedstrijd: niets meer gepland.
        later = startpagina.tegels(db, VANDAAG + timedelta(days=60))[3]
        assert later.cijfer == "0" and later.extra is None


def test_tegels_lege_database():
    with opslag(met_voorbeeld=False) as (db, _):
        t = startpagina.tegels(db, VANDAAG)
        assert [x.cijfer for x in t] == ["0", "0", "0", "0"]
        assert t[0].cijfer_label == "actieve atleten"


def test_startpagina_route():
    with opslag() as (_, tmp):
        c = app_client(tmp)
        r = c.get("/")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        # Vier grote tegels (dat die pagina's werken: test_app.test_paginas).
        tegels = re.findall(r'<a class="tegel[^"]*" href="(/[a-z]+)"', html)
        assert tegels == ["/atleten", "/groepen", "/ploegen", "/wedstrijden"]
        # Bovenin alleen Importeren en Instellingen, geen volledig hoofdmenu.
        assert 'href="/importeren"' in html and 'href="/instellingen"' in html
        assert 'aria-label="Hoofdmenu"' not in html
        # Geen namen van atleten op de startpagina.
        assert "Anna" not in html and "Voorbeeld" not in html
        # Andere pagina's houden het volledige menu.
        assert 'aria-label="Hoofdmenu"' in c.get("/atleten").get_data(as_text=True)
        assert 'aria-label="Hoofdmenu"' in c.get("/ploegen").get_data(as_text=True)
