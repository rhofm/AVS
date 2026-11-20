"""Tests voor src/groepen/landingspagina.py, de templates groep.html/groepen.html en de routes.

Echte (versleutelde) databases in een tijdelijke map, vaste testsleutel,
alleen nepgegevens.
"""

import contextlib
import re
from datetime import date, timedelta
from pathlib import Path

from atleten import beheer
from db.queries import Opslag
from groepen import landingspagina
from models import Absentie, Fase, Groep, LeerdoelScore, Mesocyclus, Onderdeel, Training, Trainingsschema
from wedstrijden import planning
from hulp import app_client, lege_opslag

VANDAAG = date(2026, 10, 16)                       # een vrijdag
MAANDAG = VANDAAG - timedelta(days=VANDAAG.weekday())
TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "ui" / "templates"


@contextlib.contextmanager
def opslag():
    with lege_opslag() as (db, tmp):
        db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
        db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
        yield db, Path(tmp)


def voorbeeldgroep(db: Opslag) -> dict:
    """Een nepgroep (di + do) met drie atleten en van alles erbij. Geeft ids."""
    anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2011-03-14",
                                specialisatie="Sprint").master_id
    bram = beheer.nieuwe_atleet(db, "Bram", "Test", geslacht="M", geboortedatum="2012").master_id
    cas = beheer.nieuwe_atleet(db, "Cas", "Proef", geslacht="M", geboortedatum="2013",
                               specialisatie="Werpen").master_id
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna, ["dinsdag", "donderdag", "zaterdag"]))
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(bram, ["dinsdag", "donderdag"]))
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(cas, ["maandag", "dinsdag", "donderdag"]))

    g = db.groep_opslaan(Groep("U16 sprint", "2026-2027", [anna, bram, cas]))
    werp = db.groep_opslaan(Groep("Werpgroep", "2026-2027", [cas]))
    db.training_opslaan(Training(werp.id, MAANDAG, "Kogel"))

    # Periodisering: V1 sinds twee weken (tot over zes weken), mesocyclus van 4 weken -> vandaag week 3 'Piek'.
    db.groep_fasen_opslaan(g.id, [Fase(MAANDAG - timedelta(weeks=2), "V1"), Fase(MAANDAG + timedelta(weeks=6), "V2")])
    db.mesocycli_opslaan(g.id, [Mesocyclus(MAANDAG - timedelta(weeks=2), 4, ["Opbouw", "Opbouw", "Piek", "Herstel"])])
    di_oud = db.training_opslaan(Training(g.id, MAANDAG - timedelta(days=6), "Starts"))     # vorige week di
    do_oud = db.training_opslaan(Training(g.id, MAANDAG - timedelta(days=4), "Horden"))     # vorige week do
    db.training_opslaan(Training(g.id, MAANDAG + timedelta(days=1), "Niet ingevuld"))       # deze week di
    db.training_opslaan(Training(g.id, MAANDAG + timedelta(days=8), "Startblok"))
    db.training_opslaan(Training(g.id, MAANDAG + timedelta(days=10), None))
    db.training_opslaan(Training(g.id, MAANDAG - timedelta(weeks=20), "Te oud"))
    db.absenties_opslaan([Absentie(di_oud.id, anna, "aanwezig"), Absentie(di_oud.id, bram, "afwezig"),
                          Absentie(do_oud.id, anna, "aanwezig"), Absentie(do_oud.id, bram, "aanwezig"),
                          Absentie(do_oud.id, cas, "afgemeld")])

    spr = [d.id for d in db.leerdoelen("U16", leerlijn="SPR")]
    db.leerdoelscores_opslaan([LeerdoelScore(anna, spr[0], 4, VANDAAG), LeerdoelScore(anna, spr[1], 2, VANDAAG),
                               LeerdoelScore(bram, spr[0], 5, VANDAAG)])

    w = planning.plan_wedstrijd(db, "Clubkampioenschappen", VANDAAG + timedelta(days=8), "Sportpark")
    planning.inschrijven(db, w.id, anna, ["100m"])
    planning.inschrijven(db, w.id, bram)
    oud = planning.plan_wedstrijd(db, "Vorige maand", VANDAAG - timedelta(days=30))
    planning.inschrijven(db, oud.id, anna, ["100m"])
    ander = beheer.nieuwe_atleet(db, "Dirk", "Buiten").master_id
    w3 = planning.plan_wedstrijd(db, "Zonder groep", VANDAAG + timedelta(days=3))
    planning.inschrijven(db, w3.id, ander)
    return {"groep": g.id, "werp": werp.id, "anna": anna, "bram": bram, "cas": cas, "spr": spr}


def test_landingspagina():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        lp = landingspagina.landingspagina(db, ids["groep"], peildatum=VANDAAG)
        assert lp.dagen_bron == landingspagina.BRON_TRAININGEN
        assert [d.dag for d in lp.trainingsdagen] == ["dinsdag", "donderdag"]
        assert [d.aantal_atleten for d in lp.trainingsdagen] == [3, 3]
        assert [d.dag for d in lp.dagen if d.vandaag] == ["vrijdag"]
        assert lp.categorieen == ["U14", "U16"]
        assert lp.periode.fase.fase == "V1" and lp.periode.week.nummer == 3 and lp.periode.week.naam == "Piek"
        assert lp.periode.kort == "V1 · wk 3 Piek"
        assert [b.code for b in lp.jaar.fasen] == ["V1", "V2"] and lp.jaar.vandaag_pct is not None

        leden = {l.atleet.voornaam: l for l in lp.leden}
        assert [l.atleet.voornaam for l in lp.leden] == ["Cas", "Bram", "Anna"]   # op achternaam
        assert leden["Anna"].categorie_code == "U16V"
        assert [d.soort for d in leden["Anna"].dagen] == [None, "groep", None, "groep", None, "elders", None]
        assert leden["Anna"].dagen[5].andere_groepen == []                         # zelf / elders
        assert leden["Cas"].dagen[0].soort == "elders" and leden["Cas"].dagen[0].andere_groepen == ["Werpgroep"]
        assert "Werpgroep" in leden["Cas"].dagen[0].uitleg
        assert (leden["Bram"].met_groep, leden["Bram"].elders) == (2, 0)

        assert [r.wedstrijd.naam for r in lp.wedstrijden] == ["Clubkampioenschappen"]
        assert [d.naam for d in lp.wedstrijden[0].deelnames] == ["Bram Test", "Anna Voorbeeld"]

        # Eerst de training van afgelopen dinsdag (nog niets ingevuld), dan de komende.
        # 'Horden'/'Starts' van vorige week vallen buiten de 7 dagen (en zijn ingevuld).
        assert [(k.training.onderwerp, k.dagen_tot, k.verwacht, k.periode, k.geweest) for k in lp.trainingen] == [
            ("Niet ingevuld", -3, 3, "V1 · wk 3 Piek", True),
            ("Startblok", 4, 3, "V1 · wk 4 Herstel", False), (None, 6, 3, "V1 · wk 4 Herstel", False)]

        assert [(b.code, b.gemiddelde_score, b.beoordeeld) for b in lp.leerdoelen] == [("SPR", 4.0, 2)]
        aantal = len(ids["spr"])
        assert lp.leerdoelen[0].zelfstandig_pct == round((100 / aantal + 100 / aantal) / 2, 1)

        aw = {d.dag: d for d in lp.aanwezigheid}
        assert list(aw) == ["dinsdag", "donderdag"]
        assert (aw["dinsdag"].trainingen, aw["dinsdag"].ingevulde_trainingen, aw["dinsdag"].percentage) == (2, 1, 50.0)
        assert aw["donderdag"].percentage == 66.7 and aw["donderdag"].gemiddeld_aanwezig == 2
        assert lp.aanwezig_pct == 60.0

        assert landingspagina.landingspagina(db, 9999) is None

        # Zodra er aanwezigheid is opgeslagen, verdwijnt de training van vorige week uit de lijst.
        dinsdag = lp.trainingen[0].training
        db.absenties_opslaan([Absentie(dinsdag.id, ids["anna"], "aanwezig")])
        lp = landingspagina.landingspagina(db, ids["groep"], peildatum=VANDAAG)
        assert [k.training.onderwerp for k in lp.trainingen] == ["Startblok", None]


def test_dagen_uit_schema_en_lege_groep():
    with opslag() as (db, _):
        a = beheer.nieuwe_atleet(db, "Eva", "Een").master_id
        b = beheer.nieuwe_atleet(db, "Fos", "Twee").master_id
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(a, ["maandag", "woensdag"]))
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(b, ["woensdag"]))
        g = db.groep_opslaan(Groep("Zonder trainingen", None, [a, b]))
        lp = landingspagina.landingspagina(db, g.id, peildatum=VANDAAG)
        assert lp.dagen_bron == landingspagina.BRON_SCHEMA
        assert [d.dag for d in lp.trainingsdagen] == ["maandag", "woensdag"]       # >= de helft van 2
        assert not lp.aanwezigheid and not lp.trainingen and not lp.wedstrijden and not lp.leerdoelen

        leeg = db.groep_opslaan(Groep("Leeg", None, []))
        lp = landingspagina.landingspagina(db, leeg.id, peildatum=VANDAAG)
        assert lp.dagen_bron is None and not lp.leden and lp.aanwezig_pct is None and not lp.periode and lp.jaar is None


def render(naam: str, **context) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from ui.opmaak import registreer_filters
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.globals["url_for"] = lambda endpoint, **kw: f"/{endpoint}/" + "/".join(str(v) for v in kw.values())
    registreer_filters(env)
    return env.get_template(naam).render(**context)


def test_template():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        html = render("groep.html", pagina=landingspagina.landingspagina(db, ids["groep"], peildatum=VANDAAG),
                      actief_menu="groepen")
        assert "U16 sprint" in html and "U14 · U16" in html and "V1 · wk 3 Piek" in html
        assert html.count("dagcel--groep") == 1 + 6 and html.count("dagcel--elders") == 1 + 2   # legenda + cellen
        assert "Maandag: traint elders (Werpgroep)" in html
        assert "U16V" in html and "Werpen" in html
        assert "Clubkampioenschappen" in html and "Zonder groep" not in html and "Vorige maand" not in html
        assert "Startblok" in html and "V1 · wk 4 Herstel" in html
        assert "Nu: Algemene voorbereiding (V1) · week 3 van 4: Piek" in html and 'class="jaar__blok fase--v1"' in html
        assert f'href="/groep/{ids["groep"]}/periodisering"' in html
        assert "3 dagen geleden" in html and "Nog invullen" in html and "1 van de afgelopen week nog in te vullen" in html
        assert "gem. 4 · 2/3 atl." in html
        assert "50%" in html and "67%" in html and "60%" in html
        assert f'href="/groep/{ids["groep"]}/prs"' in html and f'href="/groep/{ids["groep"]}/testen"' in html

        leeg = db.groep_opslaan(Groep("Leeg", None, []))
        html = render("groep.html", pagina=landingspagina.landingspagina(db, leeg.id, peildatum=VANDAAG))
        assert "Nog geen atleten" in html and "Nog niet bekend" in html
        assert "Nog niet ingesteld (optioneel)" in html and "jaar__balk" not in html

        from groepen.groepenoverzicht import GEEN_SEIZOEN, groepenoverzicht
        html = render("groepen.html", o=groepenoverzicht(db, peildatum=VANDAAG), geen_seizoen=GEEN_SEIZOEN)
        assert "U16 sprint" in html and "Di, Do" in html and "Werpgroep" in html


def test_routes():
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        c = app_client(tmp)
        r = c.get("/groepen")
        assert r.status_code == 200 and f'href="/groep/{ids["groep"]}"' in r.get_data(as_text=True)
        r = c.get(f"/groep/{ids['groep']}")
        tekst = r.get_data(as_text=True)
        assert r.status_code == 200 and "Trainingsdagen" in tekst
        # Elke link vanaf de groepspagina werkt (geen 404).
        for pad in sorted(set(re.findall(r'href="(/(?:groep|atleet|training)/[^"]*)"', tekst))):
            assert c.get(pad).status_code == 200, pad
        assert "Anna Voorbeeld" in c.get(f"/groep/{ids['groep']}/wedstrijden").get_data(as_text=True)
        assert c.get("/groep/9999").status_code == 404
        assert c.get(f"/groep/{ids['groep']}/bestaat-niet").status_code == 404
        # De groepsnamen op de atletenlijst en de atleetpagina linken naar de groep.
        assert f'href="/groep/{ids["groep"]}"' in c.get("/atleten").get_data(as_text=True)
        assert f'href="/groep/{ids["werp"]}"' in c.get(f"/atleet/{ids['cas']}").get_data(as_text=True)
