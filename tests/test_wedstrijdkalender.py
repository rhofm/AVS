"""Tests voor src/wedstrijden/kalender.py en het template ui/templates/wedstrijdplanning.html.

Alleen nepgegevens en een vaste testsleutel.
"""

from datetime import date, timedelta

from test_landingspagina import TEMPLATES, VANDAAG, opslag, voorbeeld

from atleten import beheer
from wedstrijden import kalender, planning


def test_een_atleet():
    with opslag() as db:
        mid = voorbeeld(db)
        p = kalender.wedstrijdplanning(db, mid, peildatum=VANDAAG)
        # 'Vorig seizoen' (30 dagen geleden) valt binnen de standaard 8 weken terug.
        assert [r.wedstrijd.naam for r in p.regels] == ["Vorig seizoen", "Clubkampioenschappen", "Indoor Cup"]
        assert [r.wedstrijd.naam for r in p.geweest] == ["Vorig seizoen"]
        assert p.komend[0].onderdelen == ["100m", "Verspringen"] and p.komend[1].onderdelen == []
        assert not p.groep
        # Kalender: september (geweest) t/m november (Indoor Cup), en minstens 3 maanden vanaf oktober.
        assert [m.anker for m in p.maanden] == ["2026-09", "2026-10", "2026-11", "2026-12"]
        okt = p.maanden[1]
        assert okt.naam == "oktober 2026" and all(len(w) == 7 for w in okt.weken)
        assert okt.weken[0][0].datum == date(2026, 9, 28)            # week begint op maandag
        dagen = {d.datum: d for w in okt.weken for d in w}
        assert dagen[VANDAAG].vandaag
        assert [r.wedstrijd.naam for r in dagen[VANDAAG + timedelta(days=8)].regels] == ["Clubkampioenschappen"]
        # Alleen recentere wedstrijden met een latere 'van'.
        p2 = kalender.wedstrijdplanning(db, mid, peildatum=VANDAAG, van=VANDAAG)
        assert not p2.geweest


def test_groep_en_leeg():
    with opslag() as db:
        mid = voorbeeld(db)
        bas = beheer.nieuwe_atleet(db, "Bas", "Proef").master_id
        w = [r for r in kalender.wedstrijdplanning(db, mid, peildatum=VANDAAG).komend][0].wedstrijd
        planning.inschrijven(db, w.id, bas, ["100m"])
        p = kalender.wedstrijdplanning(db, [mid, bas], peildatum=VANDAAG)
        assert p.groep
        club = [r for r in p.regels if r.wedstrijd.id == w.id][0]
        assert [(d.naam, d.onderdelen) for d in club.deelnames] == [
            ("Anna Voorbeeld", ["100m", "Verspringen"]), ("Bas Proef", ["100m"])]
        leeg = kalender.wedstrijdplanning(db, bas, peildatum=VANDAAG, van=VANDAAG + timedelta(days=9))
        assert leeg.regels == [] and len(leeg.maanden) == 3


def render(p, **kw) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from ui.opmaak import registreer_filters
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    registreer_filters(env)
    return env.get_template("wedstrijdplanning.html").render(
        planning=p, kop_naam="Anna Voorbeeld", terug_url="/atleet/x", actief_menu="atleten", **kw)


def test_template():
    with opslag() as db:
        mid = voorbeeld(db)
        html = render(kalender.wedstrijdplanning(db, mid, peildatum=VANDAAG))
        assert 'id="weergave-lijst" value="lijst" checked' in html
        assert "Clubkampioenschappen" in html and "oktober 2026" in html and "volgt nog" in html
        assert 'href="#k-' in html and "Geweest" in html
        html = render(kalender.wedstrijdplanning(db, mid, peildatum=VANDAAG), weergave="kalender")
        assert 'id="weergave-kalender" value="kalender" checked' in html
        bas = beheer.nieuwe_atleet(db, "Bas", "Proef").master_id
        html = render(kalender.wedstrijdplanning(db, [mid, bas], peildatum=VANDAAG))
        assert "Atleten &amp; onderdelen" in html and "<strong>Anna Voorbeeld</strong>" in html


def test_meerdaagse_wedstrijd_staat_op_elke_dag():
    with opslag() as db:
        mid = voorbeeld(db)
        start = VANDAAG + timedelta(days=50)               # na de Indoor Cup (dag 40)
        w = planning.plan_wedstrijd(db, "Meerkamp", start, einddatum=start + timedelta(days=2))
        planning.inschrijven(db, w.id, mid, ["100m"])
        assert db.wedstrijd(w.id).einddatum == start + timedelta(days=2)
        p = kalender.wedstrijdplanning(db, mid, peildatum=VANDAAG)
        dagen = {d.datum: d for m in p.maanden for wk in m.weken for d in wk if d.in_maand}
        for n in range(3):
            assert [r.wedstrijd.naam for r in dagen[start + timedelta(days=n)].regels] == ["Meerkamp"]
        assert "Meerkamp" not in [r.wedstrijd.naam for r in dagen[start + timedelta(days=3)].regels]
        html = render(p)
        assert html.count(f'href="#k-{w.id}"') >= 3          # in de kalender, één keer per dag


def test_einddatum_telt_niet_als_geweest_tijdens_de_wedstrijd():
    with opslag() as db:
        mid = voorbeeld(db)
        w = planning.plan_wedstrijd(db, "Loopt nog", VANDAAG - timedelta(days=1), einddatum=VANDAAG + timedelta(days=1))
        planning.inschrijven(db, w.id, mid)
        r = [r for r in kalender.wedstrijdplanning(db, mid, peildatum=VANDAAG).regels if r.wedstrijd.id == w.id][0]
        assert not r.geweest and r.dagen_tot == 0


def test_lopende_meerdaagse_wedstrijd_op_atleten_en_groepspagina_en_overzicht():
    from atleten import landingspagina as atleet_pagina
    from wedstrijden import overzicht
    with opslag() as db:
        mid = voorbeeld(db)
        w = planning.plan_wedstrijd(db, "Loopt nog", VANDAAG - timedelta(days=1), einddatum=VANDAAG + timedelta(days=1))
        planning.inschrijven(db, w.id, mid)
        pagina = atleet_pagina.landingspagina(db, mid, peildatum=VANDAAG)
        assert [p.dagen_tot for p in pagina.wedstrijden if p.wedstrijd.id == w.id] == [0]
        o = overzicht.wedstrijdenoverzicht(db, VANDAAG)
        assert w.id in [r.wedstrijd.id for r in o.komend] and w.id not in [r.wedstrijd.id for r in o.afgelopen]
        assert w.id in [x.id for x in db.wedstrijden(van=VANDAAG)]           # o.a. startpagina
