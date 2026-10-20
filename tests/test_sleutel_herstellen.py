"""Tests voor 'Sleutel herstellen' (Instellingen) en herstel() in db/init_db.py.

De echte sleutelkluis wordt nooit gebruikt: `nepkluis` vervangt het lezen en
bewaren van de hoofdsleutel door een dict. Alleen nepgegevens in een tijdelijke map.
Werkt met pytest.
"""

import contextlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import init_db as db_init  # noqa: E402
from db.init_db import SleutelFout, herstel, init_db  # noqa: E402
from db.queries import Opslag  # noqa: E402
from ui.app import maak_app, start  # noqa: E402

SLEUTEL = "5a" * 32               # de 'opgeschreven' herstelsleutel van de databases
ANDERE = "a5" * 32                # een sleutel die er niet bij past


@pytest.fixture
def kluis(monkeypatch):
    """Nep-sleutelkluis: {'sleutel': bytes} of leeg."""
    inhoud: dict[str, bytes] = {}
    monkeypatch.setattr(db_init, "_lees_hoofdsleutel", lambda: inhoud.get("sleutel"))
    monkeypatch.setattr(db_init, "_bewaar_hoofdsleutel", lambda s: inhoud.__setitem__("sleutel", s))
    return inhoud


@pytest.fixture
def data(tmp_path):
    """Map met bestaande databases (versleuteld met SLEUTEL) en één nep-atleet."""
    with contextlib.redirect_stdout(io.StringIO()):
        init_db(tmp_path, hoofd=SLEUTEL)
    from atleten import beheer
    with Opslag(map=tmp_path, hoofd=SLEUTEL) as db:
        beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2011-03-14")
    return tmp_path


def _app_zonder_sleutel(map: Path):
    """Zoals start() het doet als de sleutel ontbreekt: databases bestaan, kluis is leeg."""
    with pytest.raises(SleutelFout) as e:
        init_db(map)
    app = maak_app(map=map, startfout=str(e.value))
    app.config["TESTING"] = True
    return app.test_client()


def _tekst(r) -> str:
    return r.get_data(as_text=True)


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
    c = _app_zonder_sleutel(data)

    r = c.get("/atleten")
    assert r.status_code == 500 and "AVS kan niet starten" in _tekst(r)
    assert "Instellingen &gt; Sleutel herstellen" in _tekst(r) and "python src" not in _tekst(r)
    assert 'href="/instellingen#sleutel"' in _tekst(r)

    r = c.get("/instellingen")
    html = _tekst(r)
    assert r.status_code == 200 and 'id="sleutel"' in html
    assert "AVS kan je gegevens nu niet openen." in html
    assert '<details class="sleutel__herstellen" open>' in html     # meteen open
    assert 'type="password"' in html


def test_sleutel_herstellen(kluis, data):
    c = _app_zonder_sleutel(data)

    # verkeerde sleutel: foutmelding, niets bewaard, sleutel niet terug in de pagina
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": ANDERE})
    assert r.status_code == 400 and "Niet hersteld" in _tekst(r) and "past niet" in _tekst(r)
    assert ANDERE not in _tekst(r) and r.headers["Cache-Control"] == "no-store"
    assert kluis == {}
    assert c.get("/atleten").status_code == 500

    # goede sleutel: bewaard, AVS werkt weer zonder herstart
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": SLEUTEL})
    assert r.status_code == 302 and r.headers["Location"].endswith("/instellingen")
    assert r.headers["Cache-Control"] == "no-store"
    assert kluis["sleutel"] == bytes.fromhex(SLEUTEL)
    html = _tekst(c.get("/instellingen"))
    assert "Herstelsleutel teruggezet." in html and SLEUTEL not in html
    assert "AVS kan je gegevens nu niet openen." not in html
    r = c.get("/atleten")
    assert r.status_code == 200 and "Anna Voorbeeld" in _tekst(r)


def test_sleutel_herstellen_andere_website(kluis, data):
    c = _app_zonder_sleutel(data)
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
    html = _tekst(c.get("/instellingen"))
    assert '<details class="sleutel__herstellen">' in html and "niet openen" not in html
    r = c.post("/instellingen/sleutel", data={"herstelsleutel": ANDERE})
    assert r.status_code == 400 and "andere hoofdsleutel" in _tekst(r)
    assert kluis["sleutel"] == bytes.fromhex(SLEUTEL)


def test_start_melding(kluis, data, monkeypatch):
    """start() wijst naar Instellingen, niet naar de terminal."""
    gezien = {}

    def nep_maak_app(map=None, hoofd=None, startfout=None):
        gezien["startfout"] = startfout
        raise SystemExit                                # niet echt een server starten

    monkeypatch.setattr("ui.app.maak_app", nep_maak_app)
    with pytest.raises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
        start(map=data, browser=False)
    assert "Instellingen > Sleutel herstellen" in gezien["startfout"]
    assert gezien["startfout"].count("Sleutel herstellen") == 1 and "python" not in gezien["startfout"]
