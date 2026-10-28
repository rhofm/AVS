"""Tests voor src/atleten/landingspagina.py en het template ui/templates/atleet.html.

Echte (versleutelde) databases in een tijdelijke map, vaste testsleutel,
alleen nepgegevens.
"""

import contextlib
from datetime import date, timedelta
from pathlib import Path

from atleten import beheer, landingspagina, prestaties
from db.queries import Opslag
from models import Absentie, Groep, Notitie, Onderdeel, Test, Testresultaat, Training, Trainingsschema
from wedstrijden import planning
from hulp import lege_opslag

VANDAAG = date(2026, 10, 16)   # een vrijdag
TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "ui" / "templates"


@contextlib.contextmanager
def opslag():
    with lege_opslag() as (db, tmp):
        db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
        db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
        yield db


def voorbeeld(db: Opslag) -> str:
    """Een nep-atleet met van alles erbij. Geeft de master_id."""
    a = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2011-03-14",
                             specialisatie="Sprint & verspringen")
    mid = a.master_id
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(mid, ["dinsdag", "donderdag", "zaterdag"]))
    g = db.groep_opslaan(Groep("U16 sprint", "2026-2027", [mid]))
    maandag = VANDAAG - timedelta(days=VANDAAG.weekday())
    db.training_opslaan(Training(g.id, maandag + timedelta(days=1), "Startblok"))
    db.training_opslaan(Training(g.id, maandag + timedelta(days=8), "Volgende week"))   # valt buiten deze week
    oud = db.training_opslaan(Training(g.id, VANDAAG - timedelta(days=10), "Horden"))
    heel_oud = db.training_opslaan(Training(g.id, VANDAAG - timedelta(weeks=20), "Kracht"))
    db.absenties_opslaan([Absentie(oud.id, mid, "blessure", "enkel"),
                          Absentie(heel_oud.id, mid, "blessure", "knie")])
    for i in range(7):
        db.notitie_opslaan(Notitie(mid, VANDAAG - timedelta(days=i), f"Notitie {i}\ntweede regel"))
    w = planning.plan_wedstrijd(db, "Clubkampioenschappen", VANDAAG + timedelta(days=8), "Sportpark")
    planning.inschrijven(db, w.id, mid, ["100m", "Verspringen"])
    w2 = planning.plan_wedstrijd(db, "Indoor Cup", VANDAAG + timedelta(days=40))
    planning.inschrijven(db, w2.id, mid)
    oud_w = planning.plan_wedstrijd(db, "Vorig seizoen", VANDAAG - timedelta(days=30))
    planning.inschrijven(db, oud_w.id, mid, ["100m"])
    prestaties.handmatig_toevoegen(db, mid, "100m", date(2026, 6, 1), "13,20", wind=1.0)
    prestaties.handmatig_toevoegen(db, mid, "Verspringen", date(2026, 6, 1), "4,80", wind=0.5)
    t = db.test_opslaan(Test("30m vliegend", "s", True))
    db.testresultaat_opslaan(Testresultaat(mid, t.id, date(2026, 9, 1), 4.25))
    return mid


def test_leeftijdscategorie():
    from models import Atleet
    cat = landingspagina.leeftijdscategorie
    assert cat(Atleet("A", "B", geboortedatum="2011-12-31"), VANDAAG) == "U16"   # wordt 15
    assert cat(Atleet("A", "B", geboortedatum="2012"), VANDAAG) == "U16"         # wordt 14
    assert cat(Atleet("A", "B", geboortedatum="2013"), VANDAAG) == "U14"
    assert cat(Atleet("A", "B", geboortedatum="2017"), VANDAAG) == "U10"
    assert cat(Atleet("A", "B", geboortedatum="2021"), VANDAAG) == "U8"
    assert cat(Atleet("A", "B", geboortedatum="2006"), VANDAAG) == "Senior"
    assert cat(Atleet("A", "B"), VANDAAG) is None
    assert landingspagina.categorie_code("U16", "V") == "U16V"
    assert landingspagina.categorie_code("U10", "M") == "U10M"
    assert landingspagina.categorie_code("Senior", "V") == "SenV"
    assert landingspagina.categorie_code("U16", "X") == "U16"
    assert landingspagina.categorie_code("U16", None) == "U16"
    assert landingspagina.categorie_code(None, "V") is None
    assert landingspagina.geslacht_tekst("V", "U16") == "Meisje"
    assert landingspagina.geslacht_tekst("M", "Senior") == "Man"
    assert landingspagina.geslacht_tekst("V", None) == "Vrouw"
    assert landingspagina.geslacht_tekst(None, "U16") is None
    assert landingspagina.categorie_groep("U16", "V") == "meisjes"
    assert landingspagina.categorie_groep("Senior", "M") == "mannen"
    assert landingspagina.categorie_groep("U16", "M") == "jongens"
    assert landingspagina.categorie_groep("U18", "V") == "vrouwen"
    assert landingspagina.categorie_groep("U20", "M") == "mannen"
    assert landingspagina.geslacht_tekst("V", "U18") == "Vrouw"
    assert landingspagina.geslacht_tekst("M", "U20") == "Man"
    assert landingspagina.categorie_code("U18", "V") == "U18V"
    assert landingspagina.fase_van("U12") == "BMO"
    assert landingspagina.fase_van("U16") == "Wedstrijdgericht"
    assert landingspagina.fase_van("U18") == "Specialisatie"


def test_landingspagina():
    with opslag() as db:
        mid = voorbeeld(db)
        lp = landingspagina.landingspagina(db, mid, peildatum=VANDAAG)
        assert lp.categorie == "U16" and lp.fase == "Wedstrijdgericht"
        assert [d.kort for d in lp.schema] == ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
        assert [d.dag for d in lp.schema if d.traint] == ["dinsdag", "donderdag", "zaterdag"]
        assert lp.trainingen_per_week == 3
        assert [d.dag for d in lp.schema if d.vandaag] == ["vrijdag"]
        assert lp.schema[1].gekoppeld == ["U16 sprint – Startblok"]
        assert sum(len(d.gekoppeld) for d in lp.schema) == 1          # volgende week telt niet mee
        assert len(lp.notities) == 5 and lp.aantal_notities == 7
        assert [b.reden for b in lp.blessures] == ["enkel"]            # 'knie' is te lang geleden
        assert [(w.wedstrijd.naam, w.onderdelen, w.dagen_tot) for w in lp.wedstrijden] == [
            ("Clubkampioenschappen", ["100m", "Verspringen"], 8), ("Indoor Cup", [], 40)]
        assert sorted((r.onderdeel, r.waarde) for r in lp.prs) == [("100m", "13,20"), ("Verspringen", "4,80 m")]
        assert landingspagina.landingspagina(db, "0" * 32) is None


def test_lege_atleet():
    with opslag() as db:
        a = beheer.nieuwe_atleet(db, "Bas", "Leeg")
        lp = landingspagina.landingspagina(db, a.master_id, peildatum=VANDAAG)
        assert lp.categorie is None and lp.fase is None
        assert lp.trainingen_per_week == 0 and not lp.notities and not lp.wedstrijden and not lp.prs


def render(lp) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from ui.opmaak import registreer_filters
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    registreer_filters(env)
    return env.get_template("atleet.html").render(pagina=lp, fases=landingspagina.FASES, actief_menu="atleten")


def test_template():
    with opslag() as db:
        mid = voorbeeld(db)
        html = render(landingspagina.landingspagina(db, mid, peildatum=VANDAAG))
        assert "Anna Voorbeeld" in html and "Sprint &amp; verspringen" in html
        assert "U16V<small>meisjes</small>" in html and "<span>Meisje</span>" in html
        assert html.count("&#9632;") == 3                       # drie trainingsdagen
        assert 'aria-current="step">Wedstrijdgericht' in html
        assert "za 24 okt" in html and "over 8 dagen" in html and "volgt nog" in html
        assert "Alle 7 notities" in html and "enkel" in html
        assert "4,25" in html
        leeg = beheer.nieuwe_atleet(db, "Bas", "Leeg")
        html = render(landingspagina.landingspagina(db, leeg.master_id, peildatum=VANDAAG))
        assert "Nog geen notities" in html and "Niet ingeschreven" in html
