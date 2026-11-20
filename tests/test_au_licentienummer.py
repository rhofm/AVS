"""Tests voor het AU-licentienummer (licentienummer van de Atletiekunie) van een atleet:
model, opslag in personen.db (atleet.au_licentienummer), de formulieren 'Nieuwe atleet' en 'Aanpassen',
en de landingspagina.

Alleen nepgegevens en een vaste testsleutel.
"""


from test_app import client
from test_landingspagina import opslag, voorbeeld

from atleten import aanpassen, beheer, nieuw
from db.queries import Opslag
from models import Atleet
from hulp import TESTSLEUTEL, tekst, verwacht as _verwacht


def _form(db, mid, **wijzig) -> dict:
    form = aanpassen.ingevuld_uit(db, db.atleet(mid))
    form["actief"] = "1" if db.atleet(mid).actief else ""
    form.update(wijzig)
    return form


def test_model():
    assert Atleet("Anna", "Proef", au_licentienummer=" 12 34 567 ").au_licentienummer == "1234567"
    assert Atleet("Anna", "Proef", au_licentienummer="  ").au_licentienummer is None
    assert Atleet("Anna", "Proef").au_licentienummer is None
    _verwacht(ValueError, lambda: Atleet("Anna", "Proef", au_licentienummer="AU-123"))
    assert "1234567" not in repr(Atleet("Anna", "Proef", au_licentienummer="1234567"))   # niet in logs


def test_opslaan_en_zoeken():
    with opslag() as db:
        anna = beheer.nieuwe_atleet(db, "Anna", "Proef", au_licentienummer="1234567")
        assert db.atleet(anna.master_id).au_licentienummer == "1234567"
        assert db.atleet_op_au_licentienummer("1234567").master_id == anna.master_id
        assert db.atleet_op_au_licentienummer("123 4567").master_id == anna.master_id
        assert db.atleet_op_au_licentienummer("7654321") is None
        bas = beheer.nieuwe_atleet(db, "Bas", "Proef")                      # zonder nummer: mag vaker
        beheer.nieuwe_atleet(db, "Cas", "Proef")
        assert db.atleet(bas.master_id).au_licentienummer is None
        # Uniek in de database, ook als de controle in het formulier wordt overgeslagen.
        bas.au_licentienummer = "1234567"
        _verwacht(Exception, lambda: db.atleet_opslaan(bas))
        assert db.atleet(bas.master_id).au_licentienummer is None
        # Andere gegevens bijwerken laat het nummer staan; leegmaken kan.
        anna = db.atleet(anna.master_id)
        anna.specialisatie = "Horden"
        db.atleet_opslaan(anna)
        assert db.atleet(anna.master_id).au_licentienummer == "1234567"
        anna.au_licentienummer = None
        db.atleet_opslaan(anna)
        assert db.atleet_op_au_licentienummer("1234567") is None


def test_formulier_nieuw():
    with opslag() as db:
        beheer.nieuwe_atleet(db, "Bas", "Proef", au_licentienummer="7777777")
        invoer = nieuw.lees_formulier(db, {"voornaam": "Lieke", "achternaam": "Proef", "au_licentienummer": "12 34 567"})
        assert invoer.au_licentienummer == "1234567"
        assert db.atleet(nieuw.aanmaken(db, invoer).master_id).au_licentienummer == "1234567"
        assert nieuw.lees_formulier(db, {"voornaam": "Mo", "achternaam": "Proef"}).au_licentienummer is None
        e = _verwacht(nieuw.InvoerFout, lambda: nieuw.lees_formulier(
            db, {"voornaam": "Mo", "achternaam": "Proef", "au_licentienummer": "AU123"}))
        assert e.fouten == {"au_licentienummer": "Het AU-licentienummer bestaat alleen uit cijfers."}
        e = _verwacht(nieuw.InvoerFout, lambda: nieuw.lees_formulier(
            db, {"voornaam": "Mo", "achternaam": "Proef", "au_licentienummer": "7777777"}))
        assert "Bas Proef" in e.fouten["au_licentienummer"]
        assert "au_licentienummer" in nieuw.formulier(db).waarden


def test_formulier_aanpassen():
    with opslag() as db:
        mid = voorbeeld(db)
        beheer.nieuwe_atleet(db, "Bas", "Proef", au_licentienummer="7777777")
        assert aanpassen.ingevuld_uit(db, db.atleet(mid))["au_licentienummer"] == ""
        w = aanpassen.lees_en_opslaan(db, mid, _form(db, mid, au_licentienummer="1234567"))
        assert w.velden == ["AU-licentienummer"] and db.atleet(mid).au_licentienummer == "1234567"
        assert aanpassen.lees_en_opslaan(db, mid, _form(db, mid)).leeg              # eigen nummer is geen 'dubbel'
        e = _verwacht(nieuw.InvoerFout, lambda: aanpassen.lees_en_opslaan(db, mid, _form(db, mid, au_licentienummer="7777777")))
        assert "Bas Proef" in e.fouten["au_licentienummer"]
        assert db.atleet(mid).au_licentienummer == "1234567"
        aanpassen.lees_en_opslaan(db, mid, _form(db, mid, au_licentienummer=""))   # leegmaken
        assert db.atleet(mid).au_licentienummer is None


def test_paginas():
    with client() as (c, mid, tmp):
        r = c.get("/atleten/nieuw")
        assert 'name="au_licentienummer"' in tekst(r) and "AU-licentienummer" in tekst(r)
        r = c.get(f"/atleet/{mid}/aanpassen")
        assert 'name="au_licentienummer" value=""' in tekst(r)
        assert "licentie " not in tekst(c.get(f"/atleet/{mid}"))
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            form = _form(db, mid, au_licentienummer="1234567")
        r = c.post(f"/atleet/{mid}/aanpassen", data=form, follow_redirects=True)
        assert "Opgeslagen: gewijzigd: AU-licentienummer." in tekst(r) and "licentie 1234567" in tekst(r)
        r = c.post(f"/atleet/{mid}/aanpassen", data={**form, "au_licentienummer": "12a"})
        assert r.status_code == 400 and "Het AU-licentienummer bestaat alleen uit cijfers." in tekst(r)
