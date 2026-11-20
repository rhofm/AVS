"""Tests voor de importeerpagina (src/ui/importeren.py en de routes /importeren...).

Tijdelijke map met versleutelde databases, vaste testsleutel, alleen nepgegevens.

"""

import re

from test_startpagina import opslag

from ui import importeren
from hulp import app_client


def test_keuzes():
    assert [k.sleutel for k in importeren.KEUZES] == ["atleet", "groep", "wedstrijd"]
    assert set(importeren.PER_SLEUTEL) == {"atleet", "groep", "wedstrijd"}
    assert importeren.DOORSTUREN == {"atleet": "atleet_nieuw", "wedstrijd": "wedstrijd_nieuw"}
    assert [k.endpoint for k in importeren.KEUZES] == ["atleet_nieuw", "importeren_groep", "wedstrijd_nieuw"]
    for k in importeren.KEUZES:
        assert k.titel and k.uitleg and k.bron and k.nodig


def test_importeerpagina():
    with opslag() as (_, tmp):
        c = app_client(tmp)
        r = c.get("/importeren")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "<h1 class=\"startkop__titel\">Importeren</h1>" in html
        # Drie tegels: atleet en wedstrijd naar de bestaande formulieren, groep naar 'Groep importeren'.
        tegels = re.findall(r'<a class="tegel[^"]*" href="(/[a-z/]+)"', html)
        assert tegels == ["/atleten/nieuw", "/importeren/groep", "/wedstrijden/nieuw"]
        for pad in tegels:
            assert c.get(pad).status_code == 200, pad
        # 'Importeren' is actief in het hoofdmenu, en er is een weg terug naar Start.
        assert 'href="/importeren" aria-current="page"' in html
        assert "&larr; Start" in html
        # Geen namen van atleten.
        assert "Anna" not in html and "Voorbeeld" not in html


def test_importpaginas_werken_en_gaan_terug_naar_importeren():
    with opslag() as (_, tmp):
        c = app_client(tmp)
        r = c.get("/importeren/groep")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "Groep importeren" in html
        assert 'href="/importeren">&larr; Importeren' in html
        assert 'href="/importeren" aria-current="page"' in html
        assert c.get("/importeren/iets-anders").status_code == 404


def test_atleet_en_wedstrijd_sturen_door_naar_formulieren():
    with opslag() as (_, tmp):
        c = app_client(tmp)
        for soort, doel, kop in (("atleet", "/atleten/nieuw", "Nieuwe atleet"),
                                 ("wedstrijd", "/wedstrijden/nieuw", "Nieuwe wedstrijd")):
            r = c.get(f"/importeren/{soort}")
            assert r.status_code == 302 and r.headers["Location"].endswith(doel), soort
            assert kop in c.get(doel).get_data(as_text=True)


def test_startpagina_knop_gaat_naar_importeren():
    with opslag() as (_, tmp):
        c = app_client(tmp)
        assert 'href="/importeren"' in c.get("/").get_data(as_text=True)
        assert "Deze pagina komt nog" not in c.get("/importeren").get_data(as_text=True)
