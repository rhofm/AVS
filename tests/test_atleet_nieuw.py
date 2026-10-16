"""Tests voor src/atleten/nieuw.py en de pagina /atleten/nieuw.

Alleen nepgegevens en een vaste testsleutel. Werkt met pytest en los:
`python tests/test_atleet_nieuw.py`.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_app import TESTSLEUTEL, client, tekst  # noqa: E402
from test_landingspagina import VANDAAG, opslag, voorbeeld  # noqa: E402

from atleten import beheer, nieuw  # noqa: E402
from db.queries import Opslag  # noqa: E402


def _fout(fn) -> dict:
    try:
        fn()
    except nieuw.InvoerFout as e:
        return e.fouten
    raise AssertionError("InvoerFout verwacht")


def test_lees_formulier():
    with opslag() as db:
        mid = voorbeeld(db)
        groep = db.groepen_van_atleet(mid)[0]
        inv = nieuw.lees_formulier(db, {
            "voornaam": "  Lieke ", "tussenvoegsel": "van  der", "achternaam": "Proef", "geslacht": "V",
            "geboortedatum": "", "geboortejaar": "2012", "specialisatie": "Sprint", "atletieknu_id": "",
            "groep": [str(groep.id)], "dag": ["donderdag", "dinsdag"]}, peildatum=VANDAAG)
        assert (inv.voornaam, inv.tussenvoegsel, inv.geboortedatum) == ("Lieke", "van der", "2012")
        assert inv.groep_ids == [groep.id] and inv.dagen == ["dinsdag", "donderdag"] and inv.atletieknu_id is None

        assert set(_fout(lambda: nieuw.lees_formulier(db, {"voornaam": " ", "achternaam": ""}))) == {"voornaam", "achternaam"}
        basis = {"voornaam": "A", "achternaam": "B"}
        assert "geslacht" in _fout(lambda: nieuw.lees_formulier(db, {**basis, "geslacht": "Q"}))
        assert "geboortedatum" in _fout(lambda: nieuw.lees_formulier(db, {**basis, "geboortedatum": "2999-01-01"}))
        assert "geboortejaar" in _fout(lambda: nieuw.lees_formulier(db, {**basis, "geboortejaar": "12"}))
        assert "atletieknu_id" in _fout(lambda: nieuw.lees_formulier(db, {**basis, "atletieknu_id": "12a"}))
        assert "groep" in _fout(lambda: nieuw.lees_formulier(db, {**basis, "groep": ["999"]}))
        assert "dag" in _fout(lambda: nieuw.lees_formulier(db, {**basis, "dag": ["feestdag"]}))
        # Een atletiek.nu-id dat al bij iemand hoort, mag niet nog eens.
        beheer.nieuwe_atleet(db, "Iemand", "Anders", atletieknu_id="555")
        assert "Iemand Anders" in _fout(lambda: nieuw.lees_formulier(db, {**basis, "atletieknu_id": "555"}))["atletieknu_id"]
        # Volledige geboortedatum gaat voor het jaar.
        assert nieuw.lees_formulier(db, {**basis, "geboortedatum": "2011-03-14", "geboortejaar": "2010"}).geboortedatum == "2011-03-14"


def test_aanmaken():
    with opslag() as db:
        mid = voorbeeld(db)
        groep = db.groepen_van_atleet(mid)[0]
        inv = nieuw.NieuweAtleetInvoer("Lieke", "Proef", geslacht="V", geboortedatum="2012",
                                       groep_ids=[groep.id], dagen=["maandag", "woensdag"])
        a = nieuw.aanmaken(db, inv)
        assert db.atleet(a.master_id).naam == "Lieke Proef"
        assert a.master_id in db.groep(groep.id).leden and mid in db.groep(groep.id).leden
        assert db.trainingsschema(a.master_id).dagen == ["maandag", "woensdag"]
        # Zelfde naam en jaar: eerst een waarschuwing, met toch_aanmaken wel.
        try:
            nieuw.aanmaken(db, nieuw.NieuweAtleetInvoer("lieke", "PROEF", geboortedatum="2012"))
            raise AssertionError("DubbeleAtleet verwacht")
        except beheer.DubbeleAtleet as e:
            assert [x.master_id for x in e.bestaande] == [a.master_id]
        b = nieuw.aanmaken(db, nieuw.NieuweAtleetInvoer("Lieke", "Proef", geboortedatum="2012"), toch_aanmaken=True)
        assert b.master_id != a.master_id and db.trainingsschema(b.master_id).dagen == []


def test_paginas():
    with client() as (c, mid, tmp):
        r = c.get("/atleten")
        assert 'href="/atleten/nieuw"' in tekst(r) and "+ Nieuwe atleet" in tekst(r)
        r = c.get("/atleten/nieuw")
        assert r.status_code == 200 and "Persoonsgegevens" in tekst(r) and "U16 sprint" in tekst(r)

        # Fout: wat er al ingevuld was blijft staan.
        r = c.post("/atleten/nieuw", data={"voornaam": "Lieke", "achternaam": "", "dag": ["dinsdag"]})
        assert r.status_code == 400 and "Vul een achternaam in." in tekst(r)
        assert 'value="Lieke"' in tekst(r) and 'value="dinsdag" checked' in tekst(r)

        data = {"voornaam": "Lieke", "achternaam": "Proef", "geslacht": "V", "geboortejaar": "2012", "dag": ["dinsdag"]}
        r = c.post("/atleten/nieuw", data=data)
        assert r.status_code == 302
        r = c.get(r.headers["Location"])
        assert "Lieke Proef is toegevoegd." in tekst(r) and "U16V" in tekst(r)          # wordt dit jaar 14

        # Nog eens: waarschuwing voor dubbele atleet, pas met 'toch' wordt het een tweede atleet.
        r = c.post("/atleten/nieuw", data=data)
        assert r.status_code == 409 and "Er bestaat al een atleet met deze naam" in tekst(r)
        r = c.post("/atleten/nieuw", data={**data, "toch": "1"})
        assert r.status_code == 302
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            assert len([a for a in db.atleten() if a.naam == "Lieke Proef"]) == 2


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
