"""Tests voor het wedstrijdenoverzicht (wedstrijden.overzicht, pagina /wedstrijden):
komende en afgelopen wedstrijden, aantallen, het vinkje 'Afgelopen wedstrijden'
en de knop '+ Nieuwe wedstrijd'.

Alleen nepgegevens en een vaste testsleutel. Werkt met pytest en los:
`python tests/test_wedstrijdenoverzicht.py`.
"""

import contextlib
import io
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_landingspagina import TESTSLEUTEL, VANDAAG, opslag, voorbeeld  # noqa: E402

from atleten import beheer  # noqa: E402
from db.init_db import init_db  # noqa: E402
from db.queries import Opslag  # noqa: E402
from models import Onderdeel  # noqa: E402
from wedstrijden import planning  # noqa: E402
from wedstrijden.overzicht import wedstrijdenoverzicht  # noqa: E402


def test_komend_en_afgelopen():
    with opslag() as db:
        voorbeeld(db)       # Clubkampioenschappen (+8 d), Indoor Cup (+40 d), Vorig seizoen (-30 d)
        bram = beheer.nieuwe_atleet(db, "Bram", "Test").master_id
        w = db.wedstrijden()
        club = next(x for x in w if x.naam == "Clubkampioenschappen")
        planning.inschrijven(db, club.id, bram, ["100m"])
        planning.plan_wedstrijd(db, "Avondwedstrijd", VANDAAG)
        planning.plan_wedstrijd(db, "Heel oud", VANDAAG - timedelta(days=400))

        o = wedstrijdenoverzicht(db, peildatum=VANDAAG)
        # Komend: vandaag telt mee, vroegste eerst.
        assert [r.wedstrijd.naam for r in o.komend] == ["Avondwedstrijd", "Clubkampioenschappen", "Indoor Cup"]
        assert [r.dagen_tot for r in o.komend] == [0, 8, 40] and not any(r.geweest for r in o.komend)
        # Aantal atleten, niet het aantal onderdelen (Anna doet er twee).
        assert [r.deelnemers for r in o.komend] == [0, 2, 1]
        # Afgelopen: nieuwste eerst; ook wedstrijden zonder inschrijvingen (bijv. uit een import).
        namen_afgelopen = [r.wedstrijd.naam for r in o.afgelopen]
        assert namen_afgelopen[0] == "Vorig seizoen" and "Heel oud" in namen_afgelopen
        assert all(r.geweest for r in o.afgelopen)
        datums = [r.wedstrijd.datum for r in o.afgelopen]
        assert datums == sorted(datums, reverse=True)


def test_prestaties_per_wedstrijd():
    with opslag() as db:
        mid = voorbeeld(db)
        oud = next(x for x in db.wedstrijden() if x.naam == "Vorig seizoen")
        from models import Prestatie
        db.prestatie_opslaan(Prestatie("100m", oud.datum, 13.1, atleet_id=mid,
                                       onderdeel_id=db.onderdeel("100m").id, wedstrijd_id=oud.id))
        o = wedstrijdenoverzicht(db, peildatum=VANDAAG)
        rij = next(r for r in o.afgelopen if r.wedstrijd.id == oud.id)
        assert rij.prestaties == 1 and rij.deelnemers == 1
        assert all(r.prestaties == 0 for r in o.komend)       # komende wedstrijden: niet geteld


def test_leeg():
    with opslag() as db:
        o = wedstrijdenoverzicht(db, peildatum=VANDAAG)
        assert o.komend == [] and o.afgelopen == []


@contextlib.contextmanager
def _client(vul=True):
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
            db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
            if vul:
                vandaag = date.today()
                mid = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld").master_id
                w = planning.plan_wedstrijd(db, "Clubkampioenschappen", vandaag + timedelta(days=8), "Sportpark",
                                            link="https://www.atletiek.nu/wedstrijd/main/45678/")
                planning.inschrijven(db, w.id, mid, ["100m", "Verspringen"])
                planning.plan_wedstrijd(db, "Indoor Cup", vandaag + timedelta(days=40), indoor=True)
                planning.plan_wedstrijd(db, "Vorig seizoen", vandaag - timedelta(days=30))
        from ui.app import maak_app
        app = maak_app(map=Path(tmp), hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        yield app.test_client()


def test_pagina():
    with _client() as c:
        r = c.get("/wedstrijden")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "Deze pagina komt nog" not in html
        assert 'aria-current="page">Wedstrijden' in html
        assert "2 komende wedstrijden" in html
        # Komende wedstrijden in de bovenste tabel, op datum.
        komend = html.split('id="tabel-komend"')[1].split("</table>")[0]
        assert komend.index("Clubkampioenschappen") < komend.index("Indoor Cup")
        assert "Vorig seizoen" not in komend
        assert 'href="https://www.atletiek.nu/wedstrijd/uitslagen/45678/"' in komend
        assert '<span class="kenmerk">indoor</span>' in komend and "Sportpark" in komend
        # Geen namen van atleten op deze pagina, alleen aantallen.
        assert "Anna" not in html and "Voorbeeld" not in html
        # Afgelopen: achter een vinkje, standaard uit.
        assert re.search(r'<input class="afgelopen__vink" type="checkbox" id="toon-afgelopen"[^>]*>', html)
        assert 'id="toon-afgelopen" name="afgelopen" value="1">' in html            # niet checked
        assert 'for="toon-afgelopen">Afgelopen wedstrijden <span class="zacht">(1)</span>' in html
        afgelopen = html.split('id="tabel-afgelopen"')[1].split("</table>")[0]
        assert "Vorig seizoen" in afgelopen and "nog niet geïmporteerd" in afgelopen
        # Met ?afgelopen=1 staat het vinkje meteen aan.
        assert 'value="1" checked>' in c.get("/wedstrijden?afgelopen=1").get_data(as_text=True)
        # Knop naar een nieuwe wedstrijd; die pagina komt later.
        assert 'href="/wedstrijden/nieuw">+ Nieuwe wedstrijd</a>' in html
        r = c.get("/wedstrijden/nieuw")
        assert r.status_code == 200
        nieuw = r.get_data(as_text=True)
        assert "Nieuwe wedstrijd" in nieuw and "Deze pagina komt nog" in nieuw and "&larr; Wedstrijden" in nieuw
        # CSS voor het vinkje is er.
        css = c.get("/static/avs.css").get_data(as_text=True)
        assert ".afgelopen__vink:checked ~ .afgelopen__inhoud" in css


def test_pagina_leeg():
    with _client(vul=False) as c:
        html = c.get("/wedstrijden").get_data(as_text=True)
        assert "0 komende wedstrijden" in html and "Geen komende wedstrijden gepland" in html
        assert "Nog geen afgelopen wedstrijden" in html and "(0)" in html


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("ok ", naam)
