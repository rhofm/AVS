"""Tests voor src/instellingen (eerste weekdag, thema, tijdnotatie) en de pagina Instellingen.

Alleen nepgegevens in een tijdelijke map. Werkt met pytest (conftest.py zet 'de computer'
op maandag + 24-uurs); los draaien kan ook: `python tests/test_instellingen.py`.
"""

import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import instellingen  # noqa: E402
from instellingen import Instellingen, systeem  # noqa: E402


# ---------------- tijden ----------------
def test_tijd_24_en_12():
    h24, h12 = Instellingen(tijdnotatie="24"), Instellingen(tijdnotatie="12")
    assert h24.tijd("18:00") == "18:00u" and h24.tijd("9:05") == "09:05u" and h24.tijd("18:30:00") == "18:30u"
    assert h12.tijd("14:00") == "2:00PM" and h12.tijd("18:30") == "6:30PM"
    assert h12.tijd("00:15") == "12:15AM" and h12.tijd("12:00") == "12:00PM" and h12.tijd("09:30") == "9:30AM"
    # leeg of onleesbaar blijft zoals het is
    assert h24.tijd(None) == "" and h24.tijd("") == "" and h12.tijd("ochtend") == "ochtend" and h12.tijd("25:00") == "25:00"


def test_tijdvak():
    h24, h12 = Instellingen(tijdnotatie="24"), Instellingen(tijdnotatie="12")
    assert h24.tijdvak("10:00", "10:30") == "10:00–10:30u"
    assert h12.tijdvak("18:00", "18:45") == "6:00–6:45PM"
    assert h12.tijdvak("11:30", "12:15") == "11:30AM–12:15PM"
    assert h24.tijdvak("10:00", None) == "10:00u"


# ---------------- weekvolgorde ----------------
def test_dagvolgorde_en_weekbegin():
    zo = Instellingen(eerste_dag="zondag")
    assert zo.dagen()[:2] == ("zondag", "maandag") and len(zo.dagen()) == 7 and zo.eerste_weekdag == 6
    assert Instellingen(eerste_dag="maandag").dagen()[0] == "maandag"
    woensdag = date(2026, 10, 21)
    assert zo.weekbegin(woensdag) == date(2026, 10, 18)                        # zondag ervoor
    assert Instellingen(eerste_dag="maandag").weekbegin(woensdag) == date(2026, 10, 19)
    assert zo.weekbegin(date(2026, 10, 18)) == date(2026, 10, 18)              # zondag zelf


def test_zoals_de_computer(monkeypatch):
    monkeypatch.setattr(systeem, "eerste_weekdag", lambda: 6)
    monkeypatch.setattr(systeem, "tijd_24", lambda: False)
    inst = Instellingen()                                                      # alles 'systeem'
    assert inst.dagen()[0] == "zondag" and inst.tijd("18:00") == "6:00PM" and inst.thema_attribuut is None
    assert Instellingen(thema="donker").thema_attribuut == "dark"
    assert Instellingen(thema="licht").thema_attribuut == "light"


def test_systeem_register(monkeypatch):
    waarden = {"iFirstDayOfWeek": "6", "sShortTime": "h:mm tt"}
    monkeypatch.setattr(systeem, "_register", lambda naam: waarden.get(naam))
    assert systeem.eerste_weekdag() == 6 and systeem.tijd_24() is False
    waarden.update({"iFirstDayOfWeek": "x", "sShortTime": "HH:mm"})
    assert systeem.eerste_weekdag() == 0 and systeem.tijd_24() is True
    waarden.clear()
    assert systeem.eerste_weekdag() == 0 and systeem.tijd_24() is True       # niets te lezen: standaard
    waarden["iTime"] = "0"                                                     # alleen het oude veld
    assert systeem.tijd_24() is False


def test_onbekende_keuze():
    for fout in ({"eerste_dag": "maandagavond"}, {"thema": "paars"}, {"tijdnotatie": "13"}):
        try:
            Instellingen(**fout)
        except ValueError:
            continue
        raise AssertionError(fout)


# ---------------- bestand ----------------
def test_laden_en_opslaan():
    with tempfile.TemporaryDirectory() as tmp:
        map = Path(tmp)
        assert instellingen.laad(map) == Instellingen()                       # geen bestand: standaard
        inst = Instellingen(eerste_dag="zondag", thema="donker", tijdnotatie="12")
        instellingen.opslaan(inst, map)
        assert instellingen.laad(map) == inst
        assert json.loads((map / instellingen.BESTAND).read_text(encoding="utf-8"))["thema"] == "donker"
        assert not list(map.glob(".instellingen-*"))                          # geen tijdelijk bestand achtergebleven
        # één kapotte waarde: de rest blijft gelden
        (map / instellingen.BESTAND).write_text('{"eerste_dag": "zondag", "thema": "paars"}', encoding="utf-8")
        assert instellingen.laad(map) == Instellingen(eerste_dag="zondag")
        (map / instellingen.BESTAND).write_text("geen json", encoding="utf-8")
        assert instellingen.laad(map) == Instellingen()


# ---------------- pagina ----------------
def test_pagina_en_opslaan():
    from test_app import client, tekst
    with client() as (c, mid, map):
        r = c.get("/instellingen")
        html = tekst(r)
        assert r.status_code == 200 and "Deze pagina komt nog" not in html
        assert "Eerste dag van de week" in html and "Thema" in html and "Tijdnotatie" in html
        assert 'name="eerste_dag" id="eerste-dag-systeem" value="systeem"' in html and "data-theme" not in html.split("<head>")[0]
        assert "18:00u" in html and "6:00PM" in html                          # voorbeelden van beide notaties

        r = c.post("/instellingen", data={"eerste_dag": "zondag", "thema": "donker", "tijdnotatie": "12"})
        assert r.status_code == 302
        html = tekst(c.get("/instellingen"))
        assert "Instellingen opgeslagen." in html and '<html lang="nl" data-theme="dark">' in html
        assert re.search(r'value="zondag"[^>]*checked', html) and re.search(r'value="12"[^>]*checked', html)
        assert instellingen.laad(map) == Instellingen(eerste_dag="zondag", thema="donker", tijdnotatie="12")

        # het thema geldt op elke pagina; de kalender begint op zondag
        r = c.get(f"/atleet/{mid}/wedstrijden?weergave=kalender")
        assert 'data-theme="dark"' in tekst(r)
        koppen = tekst(r).split('<table class="kalender">', 1)[1].split("</thead>", 1)[0]
        assert koppen.index(">Zo<") < koppen.index(">Ma<")

        # onbekende keuze: niets opgeslagen
        r = c.post("/instellingen", data={"eerste_dag": "zondag", "thema": "paars", "tijdnotatie": "12"})
        assert r.status_code == 400 and "Niet opgeslagen" in tekst(r)
        assert instellingen.laad(map).thema == "donker"
    assert instellingen.actief() == instellingen.NEDERLANDS                  # niet doorgelekt na de requests


def test_tijden_op_groepspagina():
    from test_app import client, tekst
    from db.queries import Opslag
    from test_landingspagina import TESTSLEUTEL
    with client() as (c, mid, map):
        with Opslag(map=map, hoofd=TESTSLEUTEL) as db:
            g = db.groepen()[0]
            db.groep_trainingsdagen_opslaan(g.id, {"dinsdag": "18:30", "zondag": "09:00"})
        assert "18:30u" in tekst(c.get(f"/groep/{g.id}"))
        c.post("/instellingen", data={"eerste_dag": "zondag", "thema": "systeem", "tijdnotatie": "12"})
        html = tekst(c.get(f"/groep/{g.id}"))
        assert "6:30PM" in html and "18:30u" not in html
        # het groepenoverzicht: zondag nu vóór dinsdag
        overzicht = tekst(c.get("/groepen"))
        assert "Zo 9:00AM" in overzicht and overzicht.index("Zo 9:00AM") < overzicht.index("Di 6:30PM")


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f) and f.__code__.co_argcount == 0:
            f()
            print("ok", naam)
