"""Gedeeld voor pytest: tests mogen niet afhangen van de instellingen van de testcomputer.

'Zoals de computer' (instellingen.systeem) leest op Windows het register; in de
tests geldt altijd de Nederlandse standaard (week op maandag, 24-uursklok).
Daarom leest 'het register' hier niets; een test die een computer wil nadoen,
zet zelf `systeem._register` (of eerste_weekdag/tijd_24) met monkeypatch.

Vaste datums: een testmodule met vaste datums (VANDAAG, een geboortejaar, een wedstrijddag)
zet `VASTE_VANDAAG = date(...)`; dan geeft date.today() in de AVS-code die dag
(hulp.vaste_vandaag). Anders gaat zo'n test stuk zodra de echte datum verder is, bijv. op
1 januari als een atleet een leeftijdscategorie opschuift. Zulke tests vind je door de tests
een jaar verder te draaien (tests/tijdreis/sitecustomize.py).

Fixtures voor 'Sleutel herstellen': kluis (nep-sleutelkluis) en data (bestaande databases).
"""

import contextlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from instellingen import systeem  # noqa: E402
from hulp import SLEUTEL, vaste_vandaag  # noqa: E402


@pytest.fixture(autouse=True)
def nederlandse_computer(monkeypatch):
    monkeypatch.setattr(systeem, "_register", lambda naam: None)


@pytest.fixture(autouse=True)
def vaste_datum_van_de_module(request, monkeypatch):
    """VASTE_VANDAAG in de testmodule: date.today() in de AVS-code geeft die dag (zie boven)."""
    dag = getattr(request.module, "VASTE_VANDAAG", None)
    if dag is not None:
        vaste_vandaag(monkeypatch, dag)


@pytest.fixture
def kluis(monkeypatch):
    """Nep-sleutelkluis: {'sleutel': bytes} of leeg. De echte sleutelkluis wordt nooit gebruikt."""
    from db import init_db as db_init
    inhoud: dict[str, bytes] = {}
    monkeypatch.setattr(db_init, "_lees_hoofdsleutel", lambda: inhoud.get("sleutel"))
    monkeypatch.setattr(db_init, "_bewaar_hoofdsleutel", lambda s: inhoud.__setitem__("sleutel", s))
    return inhoud


@pytest.fixture
def data(tmp_path):
    """Map met bestaande databases (versleuteld met hulp.SLEUTEL) en één nep-atleet."""
    from atleten import beheer
    from db.init_db import init_db
    from db.queries import Opslag
    with contextlib.redirect_stdout(io.StringIO()):
        init_db(tmp_path, hoofd=SLEUTEL)
    with Opslag(map=tmp_path, hoofd=SLEUTEL) as db:
        beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2011-03-14")
    return tmp_path
