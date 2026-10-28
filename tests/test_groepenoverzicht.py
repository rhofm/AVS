"""Tests voor het groepenoverzicht (groepen.groepenoverzicht, pagina /groepen):
zoeken op naam, seizoen, trainingsdag en aantal atleten, filters en sorteersleutels.

Alleen nepgegevens en een vaste testsleutel.
"""


from test_groep_landingspagina import VANDAAG, opslag

from groepen.groepenoverzicht import GEEN_SEIZOEN, groepenoverzicht
from models import Atleet, Groep
from hulp import app_client


def _groepen(db):
    leden = [db.atleet_opslaan(Atleet(f"Atleet{i}", "Test")).master_id for i in range(5)]
    a = db.groep_opslaan(Groep("Sprint Zoë", "2026-2027", leden[:3]))
    b = db.groep_opslaan(Groep("Werpgroep", "2025-2026", leden[3:4]))
    c = db.groep_opslaan(Groep("Recreanten", None, leden))
    db.groep_trainingsdagen_opslaan(a.id, {"dinsdag": "18:30", "donderdag": "18:30"})
    db.groep_trainingsdagen_opslaan(b.id, {"maandag": "19:00"})
    return a, b, c


def _namen(o):
    return [r.groep.naam for r in o.rijen]


def test_zoeken_en_filteren():
    with opslag() as (db, _):
        a, b, c = _groepen(db)
        o = groepenoverzicht(db, peildatum=VANDAAG)
        assert _namen(o) == ["Recreanten", "Sprint Zoë", "Werpgroep"] and o.totaal == 3 and not o.gefilterd
        assert o.seizoenen == ["2026-2027", "2025-2026"] and o.zonder_seizoen
        assert o.dagkeuzes == [("maandag", "Maandag"), ("dinsdag", "Dinsdag"), ("donderdag", "Donderdag")]
        sprint = o.rijen[1]
        assert sprint.labels == ["Di 18:30u", "Do 18:30u"] and sprint.aantal == 3

        zoek = lambda q: _namen(groepenoverzicht(db, zoek=q, peildatum=VANDAAG))  # noqa: E731
        assert zoek("zoe") == ["Sprint Zoë"]                          # zonder accent, hoofdletters maken niet uit
        assert zoek("2025") == ["Werpgroep"]                          # seizoen
        assert zoek("dinsdag") == zoek("di 18:30") == ["Sprint Zoë"]  # trainingsdag (voluit of kort)
        assert zoek("1 atleet") == ["Werpgroep"] and zoek("5 atleten") == ["Recreanten"]
        assert zoek("sprint 2026") == ["Sprint Zoë"] and zoek("sprint 2025") == []

        o = groepenoverzicht(db, seizoen="2026-2027", peildatum=VANDAAG)
        assert _namen(o) == ["Sprint Zoë"] and o.gefilterd and o.totaal == 3
        assert _namen(groepenoverzicht(db, seizoen=GEEN_SEIZOEN, peildatum=VANDAAG)) == ["Recreanten"]
        assert _namen(groepenoverzicht(db, dag="maandag", peildatum=VANDAAG)) == ["Werpgroep"]
        # Onbekende keuzes worden genegeerd.
        o = groepenoverzicht(db, seizoen="1999", dag="feestdag", peildatum=VANDAAG)
        assert len(o.rijen) == 3 and o.seizoen == "" and o.dag == ""


def test_sorteersleutels():
    with opslag() as (db, _):
        _groepen(db)
        rij = {r.groep.naam: r for r in groepenoverzicht(db, peildatum=VANDAAG).rijen}
        assert rij["Sprint Zoë"].sort_dagen == "13" and rij["Werpgroep"].sort_dagen == "0"
        assert rij["Recreanten"].sort_dagen == "" and rij["Recreanten"].sort_seizoen == ""   # leeg = onderaan
        assert rij["Sprint Zoë"].sort_naam == "sprint zoe"


def test_pagina():
    with opslag() as (db, tmp):
        _groepen(db)
        c = app_client(tmp)
        html = c.get("/groepen").get_data(as_text=True)
        assert 'class="tabel sorteerbaar"' in html and "filter.js" in html and "sorteer.js" in html
        assert html.count('<button type="button" class="sorteer">') == 4
        assert 'data-filter-teller="groep groepen">3 groepen' in html
        assert '<option value="2026-2027">' in html and "Zonder seizoen" in html and '<option value="maandag">' in html

        html = c.get("/groepen?q=werp").get_data(as_text=True)
        assert "Werpgroep" in html and "Recreanten" not in html and "1 groep</span> van 3" in html
        assert "Wissen" in html
        html = c.get("/groepen?dag=dinsdag&seizoen=2026-2027").get_data(as_text=True)
        assert "Sprint Zoë" in html and "Werpgroep" not in html
        html = c.get("/groepen?q=bestaatniet").get_data(as_text=True)
        assert "0 groepen" in html and "Geen groepen gevonden" in html
