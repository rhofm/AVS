"""Tests voor 'Sleutel herstellen' (Instellingen) en herstel() in db/init_db.py.

De echte sleutelkluis wordt nooit gebruikt: `nepkluis` vervangt het lezen en
bewaren van de hoofdsleutel door een dict. Alleen nepgegevens in een tijdelijke map.
Werkt met pytest.
"""

import contextlib
import io
from pathlib import Path

import pytest

from db.init_db import SleutelFout, herstel
from ui.app import maak_app, start
from hulp import SLEUTEL, app_zonder_sleutel, tekst

ANDERE = "a5" * 32                # een sleutel die er niet bij past


# ---------------- herstel() ----------------
def test_herstel_controleert_databases(kluis, data):
    with pytest.raises(SleutelFout, match="past niet"):
        herstel(ANDERE, data)
    assert kluis == {}                                   # niet-passende sleutel komt nooit in de kluis

    with pytest.raises(SleutelFout, match="hexadecimale"):
        herstel("dit is geen sleutel", data)
    with pytest.raises(SleutelFout, match="64 hex"):
        herstel("ab" * 10, data)
    assert kluis == {}

    # in groepjes overgenomen, met regeleinde: mag
    herstel(" ".join(SLEUTEL[i:i + 8] for i in range(0, 64, 8)).replace(" ", "\n", 1), data)
    assert kluis["sleutel"] == bytes.fromhex(SLEUTEL)


def test_herstel_overschrijft_nooit(kluis, data):
    kluis["sleutel"] = bytes.fromhex(SLEUTEL)
    herstel(SLEUTEL.upper(), data)                       # dezelfde sleutel: geen probleem
    with pytest.raises(SleutelFout, match="andere hoofdsleutel"):
        herstel(ANDERE, data)
    assert kluis["sleutel"] == bytes.fromhex(SLEUTEL)


def test_herstel_zonder_databases(kluis, tmp_path):
    herstel(SLEUTEL, tmp_path)                           # nog geen databases: niets om tegen te controleren
    assert kluis["sleutel"] == bytes.fromhex(SLEUTEL)


# ---------------- de app ----------------
def test_startfout_laat_instellingen_door(kluis, data):
    c = app_zonder_sleutel(data)

    r = c.get("/atleten")
    assert r.status_code == 500 and "AVS kan niet starten" in tekst(r)
    assert "Instellingen &gt; Sleutel herstellen" in tekst(r) and "python src" not in tekst(r)
    assert 'href="/instellingen#sleutel"' in tekst(r)

    r = c.get("/instellingen")
    html = tekst(r)
    assert r.status_code == 200 and 'id="sleutel"' in html
    assert "AVS kan je gegevens nu niet openen." in html
    assert '<details class="sleutel__herstellen" open>' in html     # meteen open
    assert 'type="password"' in html


def test_sleutel_herstellen(kluis, data):
    c = app_zonder_sleutel(data)

    # verkeerde sleutel: foutmelding, niets bewaard, sleutel niet terug in de pagina
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": ANDERE})
    assert r.status_code == 400 and "Niet hersteld" in tekst(r) and "past niet" in tekst(r)
    assert ANDERE not in tekst(r) and r.headers["Cache-Control"] == "no-store"
    assert kluis == {}
    assert c.get("/atleten").status_code == 500

    # goede sleutel: bewaard, AVS werkt weer zonder herstart
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": SLEUTEL})
    assert r.status_code == 302 and r.headers["Location"].endswith("/instellingen")
    assert r.headers["Cache-Control"] == "no-store"
    assert kluis["sleutel"] == bytes.fromhex(SLEUTEL)
    html = tekst(c.get("/instellingen"))
    assert "Herstelsleutel teruggezet." in html and SLEUTEL not in html
    assert "AVS kan je gegevens nu niet openen." not in html
    r = c.get("/atleten")
    assert r.status_code == 200 and "Anna Voorbeeld" in tekst(r)


def test_sleutel_herstellen_andere_website(kluis, data):
    c = app_zonder_sleutel(data)
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": SLEUTEL},
               headers={"Origin": "https://kwaadaardig.example"})
    assert r.status_code == 403 and kluis == {}
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": SLEUTEL},
               headers={"Origin": "http://localhost"})              # de test-client draait op 'localhost'
    assert r.status_code == 302 and kluis["sleutel"] == bytes.fromhex(SLEUTEL)


def test_sleutel_herstellen_als_alles_werkt(kluis, data):
    """Zonder startfout staat het blok dicht; een andere sleutel wordt geweigerd."""
    kluis["sleutel"] = bytes.fromhex(SLEUTEL)
    app = maak_app(map=data)
    app.config["TESTING"] = True
    c = app.test_client()
    html = tekst(c.get("/instellingen"))
    assert '<details class="sleutel__herstellen">' in html and "niet openen" not in html
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": ANDERE})
    assert r.status_code == 400 and "andere hoofdsleutel" in tekst(r)
    assert kluis["sleutel"] == bytes.fromhex(SLEUTEL)


def test_start_melding(kluis, data, monkeypatch):
    """start() wijst naar Instellingen, niet naar de terminal."""
    gezien = {}

    def nep_maak_app(map=None, hoofd=None, startfout=None, sleutelfout=True, ontbrekend=None):
        gezien.update(startfout=startfout, sleutelfout=sleutelfout)
        raise SystemExit                                # niet echt een server starten

    monkeypatch.setattr("ui.app.maak_app", nep_maak_app)
    with pytest.raises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
        start(map=data, browser=False)
    assert "Instellingen > Sleutel herstellen" in gezien["startfout"] and gezien["sleutelfout"] is True
    assert gezien["startfout"].count("Sleutel herstellen") == 1 and "python" not in gezien["startfout"]


# ---------------- herstelsleutel tonen ----------------
def _app_met_sleutel(map: Path, hoofd=None):
    app = maak_app(map=map, hoofd=hoofd)
    app.config["TESTING"] = True
    return app.test_client()


def test_herstelsleutel_als_hij_past(kluis, data):
    from db.init_db import herstelsleutel_als_hij_past, in_groepjes
    assert herstelsleutel_als_hij_past(data, SLEUTEL) == SLEUTEL
    with pytest.raises(SleutelFout, match="past niet"):
        herstelsleutel_als_hij_past(data, ANDERE)
    with pytest.raises(SleutelFout, match="Geen hoofdsleutel"):
        herstelsleutel_als_hij_past(data)                      # lege kluis
    kluis["sleutel"] = bytes.fromhex(SLEUTEL)
    assert herstelsleutel_als_hij_past(data) == SLEUTEL
    assert in_groepjes(SLEUTEL) == ["5a5a5a5a"] * 8


def test_herstelsleutel_tonen(kluis, data):
    kluis["sleutel"] = bytes.fromhex(SLEUTEL)
    c = _app_met_sleutel(data)

    html = tekst(c.get("/instellingen"))
    assert "Herstelsleutel tonen" in html and "5a5a5a5a" not in html  # alleen de knop, nooit de sleutel

    r = c.post("/instellingen/sleutel/tonen")
    html = tekst(r)
    assert r.status_code == 200 and html.count("<span>5a5a5a5a</span>") == 8
    assert "Deel deze sleutel met niemand." in html and "Herstelsleutel tonen</button>" not in html
    assert r.headers["Cache-Control"] == "no-store" and r.headers["Referrer-Policy"] == "no-referrer"
    assert "5a5a5a5a" not in tekst(c.get("/instellingen"))      # daarna weer weg
    assert c.get("/instellingen/sleutel/tonen").status_code == 405    # geen GET: niet in de geschiedenis

    # de getoonde sleutel (met spaties) werkt bij herstellen
    kluis.clear()
    herstel(" ".join(["5a5a5a5a"] * 8), data)
    assert kluis["sleutel"] == bytes.fromhex(SLEUTEL)


def test_herstelsleutel_tonen_testsleutel(kluis, data):
    """Met een vaste sleutel (hoofd=) wordt die getoond, niet wat er in de kluis staat."""
    c = _app_met_sleutel(data, hoofd=SLEUTEL)
    assert tekst(c.post("/instellingen/sleutel/tonen")).count("<span>5a5a5a5a</span>") == 8


def test_herstelsleutel_tonen_niet_bij_startfout(kluis, data):
    c = app_zonder_sleutel(data)
    html = tekst(c.get("/instellingen"))
    assert "Herstelsleutel tonen" not in html and "Sleutel herstellen" in html
    r = c.post("/instellingen/sleutel/tonen")
    assert r.status_code == 500 and "5a5a" not in tekst(r)


def test_herstelsleutel_tonen_andere_website(kluis, data):
    kluis["sleutel"] = bytes.fromhex(SLEUTEL)
    c = _app_met_sleutel(data)
    r = c.post("/instellingen/sleutel/tonen", headers={"Origin": "https://kwaadaardig.example"})
    assert r.status_code == 403 and "5a5a" not in tekst(r)
