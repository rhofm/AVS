"""Gedeeld voor pytest: tests mogen niet afhangen van de instellingen van de testcomputer.

'Zoals de computer' (instellingen.systeem) leest op Windows het register; in de
tests geldt altijd de Nederlandse standaard (week op maandag, 24-uursklok).
Daarom leest 'het register' hier niets; een test die een computer wil nadoen,
zet zelf `systeem._register` (of eerste_weekdag/tijd_24) met monkeypatch.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from instellingen import systeem  # noqa: E402


@pytest.fixture(autouse=True)
def nederlandse_computer(monkeypatch):
    monkeypatch.setattr(systeem, "_register", lambda naam: None)
