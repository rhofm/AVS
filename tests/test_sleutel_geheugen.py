"""De app leest de hoofdsleutel één keer uit de sleutelkluis en onthoudt hem (ui.app: hoofd_uit_geheugen()).

Zo hangt niet elke pagina af van de sleutelkluis van Windows. De echte kluis wordt nooit
gebruikt: een nepkluis telt hoe vaak er gelezen wordt en kan 'kapot' gaan.
Alleen nepgegevens in een tijdelijke map.
"""

import pytest

from db import init_db as db_init
from db.init_db import SleutelkluisFout
from ui.app import maak_app
from test_sleutel_herstellen import SLEUTEL, _app_zonder_sleutel, _tekst, data  # noqa: F401 (fixture)


class Nepkluis:
    def __init__(self, sleutel: bytes | None):
        self.sleutel = sleutel
        self.gelezen = 0
        self.kapot = False

    def lees(self):
        self.gelezen += 1
        if self.kapot:
            raise SleutelkluisFout("De sleutelkluis is even niet bereikbaar (test).")
        return self.sleutel

    def bewaar(self, s):
        self.sleutel = s


@pytest.fixture
def nepkluis(monkeypatch):
    k = Nepkluis(bytes.fromhex(SLEUTEL))
    monkeypatch.setattr(db_init, "_lees_hoofdsleutel", k.lees)
    monkeypatch.setattr(db_init, "_bewaar_hoofdsleutel", k.bewaar)
    return k


def _client(map):
    app = maak_app(map=map)                     # geen vaste sleutel: zoals start() het doet
    app.config["TESTING"] = True
    return app.test_client()


def test_sleutel_maar_een_keer_gelezen(nepkluis, data):
    c = _client(data)
    for pad in ("/atleten", "/groepen", "/atleten", "/wedstrijden"):
        assert c.get(pad).status_code == 200, pad
    assert nepkluis.gelezen == 1


def test_kluis_onderweg_kapot_pagina_werkt_nog(nepkluis, data):
    c = _client(data)
    assert c.get("/atleten").status_code == 200
    nepkluis.kapot = True
    r = c.get("/atleten")
    assert r.status_code == 200 and "Anna" in _tekst(r)


def test_kluis_eerst_kapot_dan_weer_goed(nepkluis, data):
    """Een mislukte keer wordt niet onthouden: het volgende verzoek probeert het opnieuw."""
    c = _client(data)
    nepkluis.kapot = True
    r = c.get("/atleten")
    assert r.status_code == 500 and "sleutelkluis" in _tekst(r).lower()
    nepkluis.kapot = False
    r = c.get("/atleten")
    assert r.status_code == 200 and "Anna" in _tekst(r)


def test_na_sleutel_herstellen_meteen_bruikbaar(nepkluis, data):
    """Kluis leeg bij de start (startfout), dan de herstelsleutel invullen: de pagina's werken
    meteen, met de sleutel die net is teruggezet."""
    nepkluis.sleutel = None
    c = _app_zonder_sleutel(data)
    assert c.get("/atleten").status_code == 500
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": SLEUTEL})
    assert r.status_code == 302 and nepkluis.sleutel == bytes.fromhex(SLEUTEL)
    gelezen = nepkluis.gelezen
    for _ in range(3):
        assert c.get("/atleten").status_code == 200
    assert nepkluis.gelezen == gelezen                   # al onthouden bij het herstellen


def test_herstelsleutel_tonen_gebruikt_de_onthouden_sleutel(nepkluis, data):
    c = _client(data)
    assert c.get("/atleten").status_code == 200
    nepkluis.kapot = True
    r = c.post("/instellingen/sleutel/tonen")
    assert r.status_code == 200 and SLEUTEL[:8] in _tekst(r)
