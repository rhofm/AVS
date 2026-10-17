"""Tests voor src/atleten/overzicht.py en de pagina /atleten (zoeken, filteren, sorteren).

Alleen nepgegevens en een vaste testsleutel. Werkt met pytest en los:
`python tests/test_atletenoverzicht.py`.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_app import TESTSLEUTEL, client, tekst  # noqa: E402
from test_landingspagina import VANDAAG, opslag, voorbeeld  # noqa: E402

from atleten import beheer, overzicht  # noqa: E402
from db.queries import Opslag  # noqa: E402
from models import Groep  # noqa: E402


def _vul(db):
    """Anna (U16V, sprint & verspringen, groep U16 sprint) plus drie anderen."""
    anna = voorbeeld(db)
    zoe = beheer.nieuwe_atleet(db, "Zoë", "Werpstra", geboortedatum="2013", geslacht="V", specialisatie="Werpen")
    bas = beheer.nieuwe_atleet(db, "Bas", "Akkerman", geboortedatum="2012", geslacht="M", specialisatie="Sprint")
    oud = beheer.nieuwe_atleet(db, "Oud", "Lid", geboortedatum="2000")
    beheer.zet_actief(db, oud.master_id, False)
    werp = db.groep_opslaan(Groep("Werpgroep", "2026-2027", [zoe.master_id]))
    return anna, zoe, bas, oud, werp


def _namen(o):
    return [r.atleet.voornaam for r in o.rijen]


def test_plat():
    assert overzicht.plat("  Zoë   VAN Dijk ") == "zoe van dijk"
    assert overzicht.plat(None) == ""


def test_zoeken_en_filteren():
    with opslag() as db:
        anna, zoe, bas, oud, werp = _vul(db)
        o = overzicht.atletenoverzicht(db, peildatum=VANDAAG)
        assert _namen(o) == ["Bas", "Anna", "Zoë"] and o.totaal == 3 and not o.gefilterd   # op achternaam
        assert o.categorieen == ["U14", "U16"]

        zoek = lambda q, **kw: _namen(overzicht.atletenoverzicht(db, zoek=q, peildatum=VANDAAG, **kw))  # noqa: E731
        assert zoek("zoe") == ["Zoë"]                       # zonder accent
        assert zoek("u16v") == ["Anna"]                     # categorie met geslacht
        assert zoek("U16") == ["Bas", "Anna"]               # beide U16 (Bas wordt dit jaar 14)
        assert zoek("sprint") == ["Bas", "Anna"]            # specialisatie of groep 'U16 sprint'
        assert zoek("werpgroep") == ["Zoë"]                 # groep
        assert zoek("u16 sprint verspringen") == ["Anna"]   # alle woorden moeten passen
        assert zoek("xyz") == []
        assert zoek("", categorie="U14") == ["Zoë"]
        assert zoek("", groep_id=werp.id) == ["Zoë"]
        assert zoek("", categorie="onzin") == ["Bas", "Anna", "Zoë"]      # onbekend filter = genegeerd
        assert zoek("lid") == [] and zoek("lid", ook_inactief=True) == ["Oud"]
        assert overzicht.atletenoverzicht(db, zoek="sprint", peildatum=VANDAAG).gefilterd


def test_sorteersleutels():
    with opslag() as db:
        anna, zoe, bas, oud, werp = _vul(db)
        rijen = {r.atleet.voornaam: r for r in overzicht.atletenoverzicht(db, ook_inactief=True, peildatum=VANDAAG).rijen}
        assert rijen["Anna"].sort_naam == "voorbeeld anna"
        # U14 vóór U16, binnen U16 M vóór V; Senior helemaal achteraan; onbekend leeg.
        assert int(rijen["Zoë"].sort_categorie) < int(rijen["Bas"].sort_categorie) < int(rijen["Anna"].sort_categorie)
        assert int(rijen["Oud"].sort_categorie) > int(rijen["Anna"].sort_categorie)
        geen = beheer.nieuwe_atleet(db, "Geen", "Jaar")
        r = [r for r in overzicht.atletenoverzicht(db, peildatum=VANDAAG).rijen if r.atleet.voornaam == "Geen"][0]
        assert r.sort_categorie == "" and r.sort_groepen == ""


def test_pagina():
    with client() as (c, mid, tmp):
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            zoe = beheer.nieuwe_atleet(db, "Zoë", "Werpstra", geboortedatum="2013", geslacht="V")
            werp = db.groep_opslaan(Groep("Werpgroep", "2026-2027", [zoe.master_id]))
        r = tekst(c.get("/atleten"))
        assert 'class="tabel sorteerbaar atletentabel"' in r and "/static/sorteer.js" in r and "/static/filter.js" in r
        assert r.count('<button type="button" class="sorteer">') == 4
        assert 'data-zoek="anna voorbeeld u16v sprint &amp; verspringen u16 sprint"' in r
        assert f'data-groepen="{werp.id}"' in r and 'data-categorie="U14"' in r

        r = tekst(c.get("/atleten?q=werpgroep"))
        assert "Zoë Werpstra" in r and "Anna Voorbeeld" not in r and "1 atleet</span> van 2" in r
        r = tekst(c.get(f"/atleten?groep={werp.id}"))
        assert "Zoë Werpstra" in r and "Anna Voorbeeld" not in r and f'<option value="{werp.id}" selected>' in r
        r = tekst(c.get("/atleten?cat=U16"))
        assert "Anna Voorbeeld" in r and "Zoë Werpstra" not in r and '<option value="U16" selected>' in r
        r = tekst(c.get("/atleten?q=niemand"))
        assert re.search(r'<p class="leeg" data-filter-leeg>Geen atleten gevonden', r)
        assert c.get("/atleten?groep=abc").status_code == 200


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
