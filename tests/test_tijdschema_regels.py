"""Tests voor regels met de hand toevoegen/verwijderen en een opgeslagen tijdschemapagina uploaden:
wedstrijden.detail.regel_toevoegen/regel_verwijderen, tijdschema_import.tijdschema_uit_bestanden en
de routes /wedstrijd/<id>/tijdschema/regels en /tijdschema/uploaden.

Alleen opgeslagen, geanonimiseerde pagina's uit tests/fixtures/ (niets van internet).
"""

import io
from datetime import date
from pathlib import Path

import pytest

from test_tijdschema_import import MEERKAMP
from hulp import app_client
from test_wedstrijd_nieuw import BROWSERCONTROLE, opslag

from db.queries import OpslagFout
from wedstrijden import detail, planning, tijdschema_import
from wedstrijden.detail import NieuweRegel

SELTEC = Path(__file__).resolve().parent / "fixtures" / "seltec_tijdschema"


def _wedstrijd(db, d=date(2026, 8, 29)):
    return planning.plan_wedstrijd(db, "Handmatig", d)


# ---------------------------------------------------------------- met de hand

def test_regel_toevoegen_en_verwijderen():
    with opslag() as (db, _):
        w = _wedstrijd(db)
        o = db.onderdelen()[0]
        r = detail.regel_toevoegen(db, w.id, NieuweRegel(tijd="10:30", onderdeel_id=str(o.id), duur="15",
                                                         categorie="Meisjes U16", ronde="serie", groep="2"))
        assert r.id and (r.datum, r.starttijd, r.onderdeel_id, r.duur, r.groep) == (w.datum, "10:30", o.id, 15, 2)
        assert r.onderdeel_tekst == o.naam
        r2 = detail.regel_toevoegen(db, w.id, NieuweRegel(dag="2026-08-30", tijd="9:05", onderdeel_tekst=" Hink  stap sprong "))
        assert (r2.datum, r2.starttijd, r2.onderdeel_id, r2.onderdeel_tekst, r2.duur) == (
            date(2026, 8, 30), "09:05", None, "Hink stap sprong", None)
        assert [x.id for x in db.programma(w.id)] == [r.id, r2.id]
        detail.regel_verwijderen(db, w.id, r.id)
        assert [x.id for x in db.programma(w.id)] == [r2.id]


@pytest.mark.parametrize("invoer", [
    NieuweRegel(onderdeel_tekst="Kogel"),                                   # geen tijd
    NieuweRegel(tijd="10:00"),                                              # geen onderdeel
    NieuweRegel(tijd="25:99", onderdeel_tekst="Kogel"),                     # ongeldige tijd
    NieuweRegel(tijd="10:00", onderdeel_tekst="Kogel", dag="morgen"),
    NieuweRegel(tijd="10:00", onderdeel_tekst="Kogel", duur="x"),
    NieuweRegel(tijd="10:00", onderdeel_tekst="Kogel", duur="9999"),
    NieuweRegel(tijd="10:00", onderdeel_tekst="Kogel", groep="0"),
    NieuweRegel(tijd="10:00", onderdeel_id="9999"),
])
def test_regel_toevoegen_fouten(invoer):
    with opslag() as (db, _):
        w = _wedstrijd(db)
        with pytest.raises(OpslagFout):
            detail.regel_toevoegen(db, w.id, invoer)
        assert db.programma(w.id) == []


def test_regel_verwijderen_van_een_andere_wedstrijd():
    with opslag() as (db, _):
        a, b = _wedstrijd(db), planning.plan_wedstrijd(db, "Andere", date(2026, 9, 1))
        r = detail.regel_toevoegen(db, a.id, NieuweRegel(tijd="10:00", onderdeel_tekst="Kogel"))
        with pytest.raises(OpslagFout):
            detail.regel_verwijderen(db, b.id, r.id)
        assert len(db.programma(a.id)) == 1


# ---------------------------------------------------------------- uploaden

def test_upload_atletieknu_pagina():
    with opslag() as (db, _):
        w = _wedstrijd(db)
        detail.regel_toevoegen(db, w.id, NieuweRegel(tijd="08:00", onderdeel_tekst="Oud"))
        v = tijdschema_import.tijdschema_uit_bestanden(db, w.id, [("meerkamp.html", MEERKAMP.read_bytes())])
        assert v.aantal == 15 and len(db.programma(w.id)) == 15          # oude regel vervangen
        assert not any(x.onderdeel_tekst == "Oud" for x in db.programma(w.id))


def test_upload_seltec_dagpaginas_samen():
    with opslag() as (db, _):
        w = _wedstrijd(db, date(2026, 10, 10))
        v = tijdschema_import.tijdschema_uit_bestanden(
            db, w.id, [(n, (SELTEC / n).read_bytes()) for n in ("nk_dag1.html", "nk_dag2.html")])
        assert v.aantal == 14 and len({x.datum for x in db.programma(w.id)}) == 2


def test_upload_fouten_laten_het_oude_schema_staan():
    with opslag() as (db, _):
        w = _wedstrijd(db)
        detail.regel_toevoegen(db, w.id, NieuweRegel(tijd="08:00", onderdeel_tekst="Blijft"))
        for bestanden in ([], [("a.html", b"")], [("a.html", BROWSERCONTROLE.encode())],
                          [("a.html", b"<html><body>niets</body></html>")],
                          [("a.html", b"x" * (tijdschema_import.MAX_BESTAND + 1))]):
            with pytest.raises(OpslagFout):
                tijdschema_import.tijdschema_uit_bestanden(db, w.id, bestanden)
        assert [x.onderdeel_tekst for x in db.programma(w.id)] == ["Blijft"]


def test_upload_laat_niets_achter_op_schijf(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with opslag() as (db, _):
        w = _wedstrijd(db)
        tijdschema_import.tijdschema_uit_bestanden(db, w.id, [("m.html", MEERKAMP.read_bytes())])
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- routes

def test_routes():
    with opslag() as (db, tmp):
        w = _wedstrijd(db)
        c = app_client(tmp)
        pagina = c.get(f"/wedstrijd/{w.id}/tijdschema/regels").get_data(as_text=True)
        assert "Regel toevoegen" in pagina and 'type="file"' in pagina and "Nog geen regels" in pagina
        assert f"/wedstrijd/{w.id}/tijdschema/regels" in c.get(f"/wedstrijd/{w.id}").get_data(as_text=True)

        r = c.post(f"/wedstrijd/{w.id}/tijdschema/regels",
                   data={"nieuw-tijd": "10:00", "nieuw-onderdeel_tekst": "Kogelstoten", "nieuw-categorie": "U16"})
        assert r.status_code == 302
        pagina = c.get(f"/wedstrijd/{w.id}/tijdschema/regels").get_data(as_text=True)
        assert "Regel toegevoegd" in pagina and "Kogelstoten" in pagina
        regel = db.programma(w.id)[0]

        r = c.post(f"/wedstrijd/{w.id}/tijdschema/regels", data={"nieuw-tijd": "", "nieuw-onderdeel_tekst": "Speer"})
        assert r.status_code == 400 and "Niet toegevoegd" in r.get_data(as_text=True)
        assert "Speer" in r.get_data(as_text=True)                       # invoer blijft staan

        r = c.post(f"/wedstrijd/{w.id}/tijdschema/regels/{regel.id}/verwijderen")
        assert r.status_code == 302 and db.programma(w.id) == []
        assert c.post(f"/wedstrijd/{w.id}/tijdschema/regels/{regel.id}/verwijderen").status_code == 404
        assert c.get("/wedstrijd/9999/tijdschema/regels").status_code == 404

        r = c.post(f"/wedstrijd/{w.id}/tijdschema/uploaden",
                   data={"bestanden": [(io.BytesIO(MEERKAMP.read_bytes()), "meerkamp.html")]},
                   content_type="multipart/form-data")
        assert r.status_code == 302 and len(db.programma(w.id)) == 15
        r = c.post(f"/wedstrijd/{w.id}/tijdschema/uploaden",
                   data={"bestanden": [(io.BytesIO(BROWSERCONTROLE.encode()), "x.html")]},
                   content_type="multipart/form-data")
        assert r.status_code == 400 and "niet geïmporteerd" in r.get_data(as_text=True)
        r = c.post(f"/wedstrijd/{w.id}/tijdschema/uploaden", data={}, content_type="multipart/form-data")
        assert r.status_code == 400 and len(db.programma(w.id)) == 15
