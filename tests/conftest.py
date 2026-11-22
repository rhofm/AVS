"""Gedeeld voor pytest: tests mogen niet afhangen van de instellingen van de testcomputer.

'Zoals de computer' (instellingen.systeem) leest op Windows het register; in de
tests geldt altijd de Nederlandse standaard (week op maandag, 24-uursklok).
Daarom leest 'het register' hier niets; een test die een computer wil nadoen,
zet zelf `systeem._register` (of eerste_weekdag/tijd_24) met monkeypatch.

Vaste datums: een testmodule met vaste datums (VANDAAG, een geboortejaar, een wedstrijddag)
zet `VASTE_VANDAAG = date(...)`; dan geeft date.today() in de AVS-code die dag
(hulp.vaste_vandaag). Anders gaat zo'n test stuk zodra de echte datum verder is, bijv. op
1 januari als een atleet een leeftijdscategorie opschuift. tests/test_vaste_datums.py
controleert dat geen module het vergeet.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from instellingen import systeem  # noqa: E402
from hulp import vaste_vandaag  # noqa: E402


@pytest.fixture(autouse=True)
def nederlandse_computer(monkeypatch):
    monkeypatch.setattr(systeem, "_register", lambda naam: None)


@pytest.fixture(autouse=True)
def vaste_datum_van_de_module(request, monkeypatch):
    """VASTE_VANDAAG in de testmodule: date.today() in de AVS-code geeft die dag (zie boven)."""
    dag = getattr(request.module, "VASTE_VANDAAG", None)
    if dag is not None:
        vaste_vandaag(monkeypatch, dag)
