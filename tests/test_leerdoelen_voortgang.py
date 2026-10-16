"""Tests voor src/leerlijnen/voortgang.py en het template ui/templates/leerdoelen.html.

Alleen nepgegevens en een vaste testsleutel. Gebruikt de echte catalogus uit
schema_leerlijnen.sql. Werkt met pytest en los: `python tests/test_leerdoelen_voortgang.py`.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_landingspagina import TEMPLATES, VANDAAG, opslag, voorbeeld  # noqa: E402

from atleten import beheer, landingspagina  # noqa: E402
from db.queries import OpslagFout  # noqa: E402
from leerlijnen import voortgang  # noqa: E402
from models import LeerdoelScore  # noqa: E402


def _verwacht(fout, fn):
    try:
        fn()
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


def test_categorie():
    assert voortgang.leerdoelcategorie("U16") == "U16"
    assert voortgang.leerdoelcategorie("U8") == "U10"
    assert voortgang.leerdoelcategorie("Senior") == "U20"
    assert voortgang.leerdoelcategorie(None) is None


def test_pagina_en_opslaan():
    with opslag() as db:
        mid = voorbeeld(db)                                  # U16
        lp = voortgang.leerdoelenpagina(db, mid, "U16", peildatum=VANDAAG)
        assert lp.categorie == "U16" and lp.aantal == len(db.leerdoelen("U16"))
        assert all(r.eigen_categorie for b in lp.leerlijnen for r in b.regels)
        assert lp.zelfstandig == 0 and lp.beoordeeld == 0
        door = voortgang.leerdoelenpagina(db, mid, "U16", doorlopend=True)
        assert door.aantal == len(db.leerdoelen("U16", doorlopend=True)) > lp.aantal
        assert any(not r.eigen_categorie for b in door.leerlijnen for r in b.regels)

        blok0 = max(lp.leerlijnen, key=lambda b: b.aantal)                 # een leerlijn met minstens 3 doelen
        doelen = [r.leerdoel.id for r in blok0.regels][:3]
        form = {"datum": "2026-10-01", f"score-{doelen[0]}": "4", f"score-{doelen[1]}": "2",
                f"score-{doelen[2]}": "", "iets-anders": "x"}
        assert voortgang.scores_opslaan(db, mid, form, date(2026, 10, 1)) == 2
        # Zelfde scores nog eens: niets nieuws in de geschiedenis.
        assert voortgang.scores_opslaan(db, mid, form, date(2026, 10, 8)) == 0
        form[f"score-{doelen[1]}"] = "3"
        assert voortgang.scores_opslaan(db, mid, form, date(2026, 10, 8)) == 1
        assert [s.score for s in db.leerdoelscores(mid, doelen[1])] == [2, 3]

        lp = voortgang.leerdoelenpagina(db, mid, "U16")
        blok = [b for b in lp.leerlijnen if b.code == blok0.code][0]
        assert blok.beoordeeld == 2 and blok.zelfstandig == 1 and blok.gemiddelde == 3.5
        assert [b.code for b in voortgang.samenvatting(db, mid, "U16")] == [blok.code]
        assert landingspagina.landingspagina(db, mid, peildatum=VANDAAG).leerdoelen[0].zelfstandig == 1

        _verwacht(ValueError, lambda: voortgang.scores_opslaan(db, mid, {f"score-{doelen[0]}": "7"}, VANDAAG))
        _verwacht(OpslagFout, lambda: voortgang.scores_opslaan(db, mid, {f"score-{doelen[0]}": "veel"}, VANDAAG))
        _verwacht(OpslagFout, lambda: voortgang.scores_opslaan(db, mid, {"score-XXX-U10-99": "3"}, VANDAAG))
        assert voortgang.leerdoelenpagina(db, "0" * 32, "U16") is None


def test_zonder_leeftijd():
    with opslag() as db:
        bas = beheer.nieuwe_atleet(db, "Bas", "Proef").master_id
        lp = voortgang.leerdoelenpagina(db, bas, None)
        assert lp.categorie is None and lp.aantal == len(db.leerdoelen())


def render(lp, **kw) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from ui.opmaak import registreer_filters
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    registreer_filters(env)
    return env.get_template("leerdoelen.html").render(lp=lp, basis_url="/atleet/x", actief_menu="atleten", **kw)


def test_template():
    with opslag() as db:
        mid = voorbeeld(db)
        doel = db.leerdoelen("U16")[0]
        db.leerdoelscore_opslaan(LeerdoelScore(mid, doel.id, 4, date(2026, 9, 1)))
        lp = voortgang.leerdoelenpagina(db, mid, "U16", peildatum=VANDAAG)
        html = render(lp)
        assert 'id="modus-bekijken" value="bekijken" checked' in html
        assert f'name="score-{doel.id}" value="4" checked' in html
        assert "Zelfstandig" in html and "1 sep 2026" in html and "Nog niet beoordeeld" in html
        assert html.count('class="aan"') >= 4 + 15          # 4 blokjes + de schaal (1+2+3+4+5)
        html = render(lp, modus="bewerken", melding="1 score opgeslagen")
        assert 'id="modus-bewerken" value="bewerken" checked' in html and "1 score opgeslagen" in html


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
