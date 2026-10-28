"""Tests voor src/atleten/aanpassen.py en de pagina's /atleet/<id>/aanpassen en /verwijderen.

Alleen nepgegevens en een vaste testsleutel.
"""


from test_app import client
from test_landingspagina import opslag, voorbeeld

from atleten import aanpassen, beheer, nieuw
from db.queries import Opslag, OpslagFout
from models import Groep, Notitie
from hulp import TESTSLEUTEL, tekst


def _form(db, mid, **wijzig) -> dict:
    """Het formulier zoals het vooraf ingevuld wordt, met wijzigingen."""
    form = aanpassen.ingevuld_uit(db, db.atleet(mid))
    form["actief"] = "1" if db.atleet(mid).actief else ""
    form.update(wijzig)
    return form


def test_vooraf_ingevuld():
    with opslag() as db:
        mid = voorbeeld(db)
        a, f, actief = aanpassen.aanpasformulier(db, mid)
        assert f.waarden["voornaam"] == "Anna" and f.waarden["geboortedatum"] == "2011-03-14"
        assert f.waarden["geboortejaar"] == "" and f.waarden["geslacht"] == "V" and actief
        assert [k.groep.naam for k in f.groepen if k.gekozen] == ["U16 sprint"]
        assert aanpassen.aanpasformulier(db, "0" * 32) is None


def test_opslaan():
    with opslag() as db:
        mid = voorbeeld(db)
        extra = db.groep_opslaan(Groep("Werpgroep", "2026-2027"))
        sprint = db.groepen_van_atleet(mid)[0]
        assert aanpassen.lees_en_opslaan(db, mid, _form(db, mid)).leeg

        w = aanpassen.lees_en_opslaan(db, mid, _form(db, mid, achternaam="Voorbeeld-Test", specialisatie="Horden",
                                                   geboortedatum="", geboortejaar="2011", groep=[str(extra.id)]))
        assert w.velden == ["achternaam", "geboortedatum", "specialisatie"]
        assert w.groepen_erbij == ["Werpgroep"] and w.groepen_eraf == ["U16 sprint"]
        assert w.tekst.startswith("Opgeslagen: gewijzigd: achternaam, geboortedatum, specialisatie;")
        a = db.atleet(mid)
        assert (a.naam, a.geboortedatum, a.specialisatie) == ("Anna Voorbeeld-Test", "2011", "Horden")
        assert mid in db.groep(extra.id).leden and mid not in db.groep(sprint.id).leden
        assert db.trainingsschema(mid).dagen == ["dinsdag", "donderdag", "zaterdag"]   # blijft ongemoeid

        w = aanpassen.lees_en_opslaan(db, mid, _form(db, mid, actief=""))
        assert w.velden == ["actief"] and not db.atleet(mid).actief

        # Eigen atletiek.nu-id is geen 'dubbel'; dat van een ander wel.
        beheer.nieuwe_atleet(db, "Bas", "Proef", atletieknu_id="777")
        aanpassen.lees_en_opslaan(db, mid, _form(db, mid, atletieknu_id="123"))
        assert aanpassen.lees_en_opslaan(db, mid, _form(db, mid, atletieknu_id="123")).leeg
        try:
            aanpassen.lees_en_opslaan(db, mid, _form(db, mid, atletieknu_id="777"))
            raise AssertionError("InvoerFout verwacht")
        except nieuw.InvoerFout as e:
            assert "Bas Proef" in e.fouten["atletieknu_id"]


def test_verwijderen():
    with opslag() as db:
        mid = voorbeeld(db)
        db.notitie_opslaan(Notitie(mid, __import__("datetime").date(2026, 10, 1), "test"))
        for fout in ("", "Anna", "Anna Voorbeeldje"):
            try:
                aanpassen.verwijderen(db, mid, fout)
                raise AssertionError("OpslagFout verwacht")
            except OpslagFout:
                pass
        assert db.atleet(mid) is not None
        a = aanpassen.verwijderen(db, mid, "  anna   VOORBEELD ")
        assert a.naam == "Anna Voorbeeld" and db.atleet(mid) is None
        assert db.notities(mid) == [] and db.trainingsschema(mid).dagen == []


def test_paginas():
    with client() as (c, mid, tmp):
        r = c.get(f"/atleet/{mid}")
        assert f'href="/atleet/{mid}/aanpassen"' in tekst(r)
        r = c.get(f"/atleet/{mid}/aanpassen")
        assert r.status_code == 200 and 'value="Anna"' in tekst(r) and 'name="actief" value="1" checked' in tekst(r)

        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            form = _form(db, mid, specialisatie="Meerkamp")
        r = c.post(f"/atleet/{mid}/aanpassen", data=form, follow_redirects=True)
        assert "Opgeslagen: gewijzigd: specialisatie." in tekst(r) and "Meerkamp" in tekst(r)

        r = c.post(f"/atleet/{mid}/aanpassen", data={**form, "voornaam": ""})
        assert r.status_code == 400 and "Vul een voornaam in." in tekst(r) and 'value="Meerkamp"' in tekst(r)

        r = c.post(f"/atleet/{mid}/verwijderen", data={"bevestiging": "iemand anders"})
        assert r.status_code == 400 and "Typ de volledige naam" in tekst(r)
        r = c.post(f"/atleet/{mid}/verwijderen", data={"bevestiging": "Anna Voorbeeld"}, follow_redirects=True)
        assert "Anna Voorbeeld en alle gegevens zijn verwijderd." in tekst(r)
        assert c.get(f"/atleet/{mid}").status_code == 404
        assert c.get("/atleet/" + "0" * 32 + "/aanpassen").status_code == 404
