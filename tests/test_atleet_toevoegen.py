"""Tests voor src/atleten/atleet_toevoegen_atletieknu.py.

Gebruikt een nagebouwde, geanonimiseerde profielpagina (tests/fixtures/atletieknu_profiel.html)
en een tijdelijke map met een vaste testsleutel: raakt atletiek.nu, de sleutelkluis en data/ nooit aan.
"""

from pathlib import Path

from atleten import beheer
from atleten.atleet_toevoegen_atletieknu import (
    atletieknu_id_uit, voeg_toe,
)
from hulp import opslag

PROFIEL = (Path(__file__).parent / "fixtures" / "atletieknu_profiel.html").read_text(encoding="utf-8")


def test_hulpjes():
    assert atletieknu_id_uit("999999") == "999999"
    assert atletieknu_id_uit("https://www.atletiek.nu/atleet/profiel/999999/#prs") == "999999"
    try:
        atletieknu_id_uit("https://www.atletiek.nu/")
        raise AssertionError("ValueError verwacht")
    except ValueError:
        pass


def test_nieuwe_atleet_en_opnieuw_importeren():
    with opslag() as db:
        u = voeg_toe(db, "Test", "Vries", "999999", tussenvoegsel="de", html=PROFIEL)
        assert u.status == "nieuw"
        assert u.atleet.naam == "Test de Vries" and u.atleet.atletieknu_id == "999999"
        opgeslagen = db.atleet(u.atleet.master_id)
        assert (opgeslagen.tussenvoegsel, opgeslagen.achternaam) == ("de", "Vries")
        assert (u.nieuw, u.bekend, u.overgeslagen) == (2, 0, 1)      # DNF overgeslagen
        assert len(db.prestaties(u.atleet.master_id)) == 2

        # Nog een keer: zelfde atleet, geen dubbele prestaties.
        u2 = voeg_toe(db, "Test", "Vries", "https://www.atletiek.nu/atleet/profiel/999999/",
                      tussenvoegsel="de", html=PROFIEL)
        assert u2.status == "bestond" and u2.atleet.master_id == u.atleet.master_id
        assert (u2.nieuw, u2.bekend) == (0, 2)
        assert len(db.atleten(alleen_actief=False)) == 1


def test_bestaande_atleet_zonder_id_koppelen():
    with opslag() as db:
        oud = beheer.nieuwe_atleet(db, "Test", "Jansen", club="AV Test")
        u = voeg_toe(db, "Test", "Jansen", "999999", html=PROFIEL, bevestig=lambda a: True)
        assert u.status == "id_toegevoegd" and u.atleet.master_id == oud.master_id
        assert db.atleet(oud.master_id).atletieknu_id == "999999"
        assert len(db.atleten(alleen_actief=False)) == 1


def test_tussenvoegsel_telt_mee_bij_dubbelen():
    with opslag() as db:
        oud = beheer.nieuwe_atleet(db, "Test", "Berg", tussenvoegsel="van den")
        # 'Test Berg' zonder tussenvoegsel is een andere naam: geen kandidaat.
        u = voeg_toe(db, "Test", "Berg", "999999", html=PROFIEL, bevestig=lambda a: True)
        assert u.status == "nieuw" and u.atleet.master_id != oud.master_id
        assert u.atleet.tussenvoegsel is None


def test_niet_bevestigd_of_ander_id_wordt_nieuwe_atleet():
    with opslag() as db:
        beheer.nieuwe_atleet(db, "Test", "Jansen")
        beheer.nieuwe_atleet(db, "Test", "Jansen", toch_aanmaken=True, atletieknu_id="888888")
        u = voeg_toe(db, "Test", "Jansen", "999999", html=PROFIEL, bevestig=lambda a: False)
        assert u.status == "nieuw"
        assert len(db.atleten(alleen_actief=False)) == 3
