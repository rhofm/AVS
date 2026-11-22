"""Tests voor src/atleten/landingspagina.py en het template ui/templates/atleet.html.

Echte (versleutelde) databases in een tijdelijke map, vaste testsleutel,
alleen nepgegevens.
"""

from datetime import timedelta

from atleten import beheer, landingspagina
from models import Training, Trainingsschema
from voorbeeld_atleet import TEMPLATES, VANDAAG, opslag, voorbeeld


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
    assert landingspagina.geslacht_tekst("V") == "Vrouw"
    assert landingspagina.geslacht_tekst("M") == "Man"
    assert landingspagina.geslacht_tekst(None) is None
    assert landingspagina.categorie_groep("U16", "V") == "vrouwen"
    assert landingspagina.categorie_groep("Senior", "M") == "mannen"
    assert landingspagina.categorie_groep("U16", "M") == "mannen"
    assert landingspagina.geslacht_tekst("X") == "X"
    assert landingspagina.categorie_groep("U8", "V") == "vrouwen"
    assert landingspagina.categorie_groep("U18", "V") == "vrouwen"
    assert landingspagina.categorie_groep("U20", "M") == "mannen"
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


def test_deze_week_toont_de_variant_van_de_atleet():
    """Doet de atleet een afwijkende training (variant), dan staat die op zijn pagina, niet de gewone."""
    with opslag() as db:
        mid = voorbeeld(db)
        bram = beheer.nieuwe_atleet(db, "Bram", "Proef", geslacht="M", geboortedatum="2011")
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(bram.master_id, ["dinsdag"]))
        g = db.groepen_van_atleet(mid)[0]
        g.voeg_toe(bram.master_id)
        db.groep_opslaan(g)
        dinsdag = VANDAAG - timedelta(days=VANDAAG.weekday()) + timedelta(days=1)
        hoofd = next(t for t in db.trainingen(g.id) if t.datum == dinsdag)
        db.training_opslaan(Training(g.id, dinsdag, "Revalidatie", hoofdtraining_id=hoofd.id, atleten=[mid]))

        anna = landingspagina.landingspagina(db, mid, peildatum=VANDAAG)
        assert anna.schema[1].gekoppeld == ["U16 sprint – Revalidatie"]
        bram_lp = landingspagina.landingspagina(db, bram.master_id, peildatum=VANDAAG)
        assert bram_lp.schema[1].gekoppeld == ["U16 sprint – Startblok"]   # wie de variant niet doet


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
        assert "U16V<small>vrouwen</small>" in html and "<span>Vrouw</span>" in html
        assert "meisje" not in html.lower() and "jongen" not in html.lower()
        assert html.count("&#9632;") == 3                       # drie trainingsdagen
        assert 'aria-current="step">Wedstrijdgericht' in html
        assert "za 24 okt" in html and "over 8 dagen" in html and "volgt nog" in html
        assert "Alle 7 notities" in html and "enkel" in html
        assert "4,25" in html
        leeg = beheer.nieuwe_atleet(db, "Bas", "Leeg")
        html = render(landingspagina.landingspagina(db, leeg.master_id, peildatum=VANDAAG))
        assert "Nog geen notities" in html and "Niet ingeschreven" in html
