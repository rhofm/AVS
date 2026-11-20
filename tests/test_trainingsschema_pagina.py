"""Tests voor src/atleten/trainingsschema.py en de pagina /atleet/<id>/trainingsschema.

Alleen nepgegevens en een vaste testsleutel.
"""


from test_app import client
from test_landingspagina import VANDAAG, opslag, voorbeeld

from atleten import trainingsschema
from db.queries import Opslag, OpslagFout
from hulp import TESTSLEUTEL, tekst, verwacht as _verwacht


def test_formulier_en_opslaan():
    with opslag() as db:
        mid = voorbeeld(db)                                  # Anna: di/do/za, groep 'U16 sprint' traint op di
        f = trainingsschema.schemaformulier(db, mid, peildatum=VANDAAG)
        assert [d.kort for d in f.dagen] == ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
        assert [d.dag for d in f.dagen if d.traint] == ["dinsdag", "donderdag", "zaterdag"] and f.aantal == 3
        groepen = {d.dag: d.groepen for d in f.dagen}
        assert groepen["dinsdag"] == ["U16 sprint"] and f.heeft_groepsdagen

        w = trainingsschema.schema_opslaan(db, mid, ["maandag", "Donderdag ", "zaterdag", ""])
        assert w.erbij == ["maandag"] and w.eraf == ["dinsdag"]
        assert w.tekst == "Trainingsschema opgeslagen: maandag, donderdag, zaterdag."
        assert db.trainingsschema(mid).dagen == ["maandag", "donderdag", "zaterdag"]
        assert trainingsschema.schema_opslaan(db, mid, ["zaterdag", "maandag", "donderdag"]).leeg
        w = trainingsschema.schema_opslaan(db, mid, [])
        assert w.tekst == "Trainingsschema opgeslagen: geen trainingsdagen." and db.trainingsschema(mid).dagen == []

        _verwacht(OpslagFout, lambda: trainingsschema.schema_opslaan(db, mid, ["feestdag"]))
        _verwacht(OpslagFout, lambda: trainingsschema.schema_opslaan(db, "0" * 32, ["maandag"]))
        assert trainingsschema.schemaformulier(db, "0" * 32) is None


def test_pagina():
    with client() as (c, mid, tmp):
        r = c.get(f"/atleet/{mid}/trainingsschema")
        assert r.status_code == 200 and "Trainingsschema" in tekst(r)
        assert 'value="dinsdag" checked' in tekst(r) and 'value="maandag">' in tekst(r)

        r = c.post(f"/atleet/{mid}/trainingsschema", data={"dag": ["woensdag", "vrijdag"]})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/atleet/{mid}#kop-schema")
        r = c.get(f"/atleet/{mid}")
        assert "Trainingsschema opgeslagen: woensdag, vrijdag." in tekst(r) and "2× per week" in tekst(r)
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            assert db.trainingsschema(mid).dagen == ["woensdag", "vrijdag"]

        r = c.post(f"/atleet/{mid}/trainingsschema", data={"dag": ["woensdag", "vrijdag"]}, follow_redirects=True)
        assert "Trainingsschema niet gewijzigd." in tekst(r)
        r = c.post(f"/atleet/{mid}/trainingsschema", data={"dag": ["blauwdag"]})
        assert r.status_code == 400 and "Niet opgeslagen" in tekst(r)
        assert c.get("/atleet/" + "0" * 32 + "/trainingsschema").status_code == 404
