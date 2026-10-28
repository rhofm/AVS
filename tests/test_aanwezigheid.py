"""Tests voor src/atleten/aanwezigheid.py en het template ui/templates/aanwezigheid.html.

Alleen nepgegevens en een vaste testsleutel.
"""

from datetime import date, timedelta

from test_landingspagina import TEMPLATES, VANDAAG, opslag, voorbeeld

from atleten import aanwezigheid, landingspagina
from models import Absentie, Training


def _met_trainingen(db):
    """Anna (traint di/do/za) met een paar trainingen in de U16-sprintgroep."""
    mid = voorbeeld(db)
    g = [g for g in db.groepen_van_atleet(mid) if g.naam == "U16 sprint"][0]
    dinsdag = date(2026, 10, 13)
    t = {
        "aanwezig": db.training_opslaan(Training(g.id, dinsdag, "Starts")),
        "afgemeld": db.training_opslaan(Training(g.id, dinsdag - timedelta(days=5), "Horden")),   # do 8 okt
        "afwezig": db.training_opslaan(Training(g.id, dinsdag - timedelta(days=7), None)),        # di 6 okt
        "leeg": db.training_opslaan(Training(g.id, dinsdag + timedelta(days=2), "Kracht")),       # do 15 okt
        "maandag": db.training_opslaan(Training(g.id, dinsdag - timedelta(days=1), "Extra")),    # ma: niet ingeroosterd
    }
    db.absenties_opslaan([Absentie(t["aanwezig"].id, mid, "aanwezig"),
                          Absentie(t["afgemeld"].id, mid, "afgemeld", "school"),
                          Absentie(t["afwezig"].id, mid, "afwezig")])
    return mid, t


def test_aanwezigheid():
    with opslag() as db:
        mid, t = _met_trainingen(db)
        aw = aanwezigheid.aanwezigheid(db, mid, peildatum=VANDAAG)
        status = {r.training.id: r.status for r in aw.regels}
        assert status[t["aanwezig"].id] == "aanwezig"
        assert status[t["afgemeld"].id] == "afgemeld"
        assert status[t["leeg"].id] == aanwezigheid.NIET_INGEVULD
        assert t["maandag"].id not in status                            # niet ingeroosterd, geen status
        assert [r.training.datum for r in aw.regels] == sorted((r.training.datum for r in aw.regels), reverse=True)
        # uit voorbeeld(): de training "Startblok" (niet ingevuld), een blessure 10 dagen geleden
        # en één 20 weken geleden (buiten de 12 weken)
        assert aw.telling == {"aanwezig": 1, "afwezig": 1, "afgemeld": 1, "blessure": 1, "niet_ingevuld": 2}
        assert aw.ingevuld == 4 and aw.percentage == 25.0
        # Toekomstige training (volgende week in voorbeeld()) telt niet mee.
        assert all(r.training.datum <= VANDAAG for r in aw.regels)

        assert aw.maanden[0].naam == "oktober 2026" and aw.maanden[-1].naam == "juli 2026"
        okt = {d.datum: d for w in aw.maanden[0].weken for d in w}
        assert okt[date(2026, 10, 8)].status == "afgemeld"
        assert okt[date(2026, 10, 13)].status == aanwezigheid.NIET_INGEVULD   # twee trainingen: de "ergste" telt
        assert okt[date(2026, 9, 29)].regels == []                       # opvuldag uit september
        assert okt[VANDAAG].vandaag
        assert max(okt) == date(2026, 10, 18)                           # week na vandaag valt weg
        assert landingspagina.landingspagina(db, mid, peildatum=VANDAAG).aanwezig_pct == 25.0


def test_dagstatus_ergste_eerst():
    t = Training(1, VANDAAG)
    dag = aanwezigheid.AanwezigheidDag(VANDAAG, True, False, [
        aanwezigheid.AanwezigheidRegel(t, "A", "aanwezig"), aanwezigheid.AanwezigheidRegel(t, "B", "afgemeld")])
    assert dag.status == "afgemeld"


def render(aw, **kw) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from ui.opmaak import registreer_filters
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    registreer_filters(env)
    return env.get_template("aanwezigheid.html").render(
        aw=aw, kop_naam="Anna Voorbeeld", terug_url="/atleet/x", actief_menu="atleten", **kw)


def test_template():
    with opslag() as db:
        mid, _ = _met_trainingen(db)
        html = render(aanwezigheid.aanwezigheid(db, mid, peildatum=VANDAAG))
        for s in ("aanwezig", "afwezig", "afgemeld", "blessure", "niet_ingevuld"):
            assert f'<tr class="status-{s}">' in html
        assert "25%" in html and "school" in html and "oktober 2026" in html
        assert 'id="weergave-lijst" value="lijst" checked' in html
        html = render(aanwezigheid.aanwezigheid(db, mid, peildatum=VANDAAG), weergave="kalender")
        assert 'id="weergave-kalender" value="kalender" checked' in html
