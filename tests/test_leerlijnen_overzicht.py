"""Tests voor src/leerlijnen/overzicht.py en de pagina /leerlijnen (templates/leerlijnen.html).

Alleen de catalogus uit schema_leerlijnen.sql; geen persoonsgegevens nodig.

"""

import contextlib
import io
import tempfile
from pathlib import Path

from db.init_db import init_db
from db.queries import Opslag
from leerlijnen.overzicht import leerlijnoverzicht
from models import CATEGORIEEN
from ui.app import maak_app
from hulp import TESTSLEUTEL


@contextlib.contextmanager
def map_met_db():
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        yield Path(tmp)


@contextlib.contextmanager
def opslag():
    with map_met_db() as tmp, Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
        yield db


@contextlib.contextmanager
def client():
    with map_met_db() as tmp:
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        yield app.test_client()


def ids(o) -> list[str]:
    return [d.id for g in o.groepen for d in g.doelen]


# ---------- logica ----------
def test_zonder_keuze_alleen_telling():
    with opslag() as db:
        o = leerlijnoverzicht(db)
        assert not o.gekozen and o.groepen == [] and o.groeperen_op is None
        assert o.totaal == len(db.leerdoelen()) == 215
        assert sum(o.per_categorie(c) for c in CATEGORIEEN) == o.totaal
        assert sum(o.per_onderdeel(c) for c, _ in o.leerlijnen) == o.totaal
        assert o.telling[("SPR", "U10")] == len(db.leerdoelen("U10", leerlijn="SPR"))


def test_onderdeel_per_categorie():
    with opslag() as db:
        o = leerlijnoverzicht(db, onderdeel="spr")                         # hoofdletters maken niet uit
        assert o.onderdeel == "SPR" and o.onderdeel_naam == "Sprint" and o.groeperen_op == "categorie"
        assert [g.sleutel for g in o.groepen] == [c for c in CATEGORIEEN if o.telling.get(("SPR", c))]
        assert ids(o) == [d.id for d in db.leerdoelen(leerlijn="SPR")]
        assert ids(o)[0] == "SPR-U10-01"
        assert not o.toon_categorie


def test_categorie_per_onderdeel_en_doorlopend():
    with opslag() as db:
        o = leerlijnoverzicht(db, categorie="U14")
        assert o.groeperen_op == "onderdeel" and not o.doorlopend
        assert all(d.categorie == "U14" for g in o.groepen for d in g.doelen)
        assert sorted(ids(o)) == sorted(d.id for d in db.leerdoelen("U14"))
        volgorde = [c for c, _ in o.leerlijnen]
        assert [g.sleutel for g in o.groepen] == sorted((g.sleutel for g in o.groepen), key=volgorde.index)

        door = leerlijnoverzicht(db, categorie="U14", doorlopend=True)
        assert door.doorlopend and door.toon_categorie
        assert door.aantal == len(db.leerdoelen("U14", doorlopend=True))
        for g in door.groepen:                                             # oudste categorie eerst
            cats = [CATEGORIEEN.index(d.categorie) for d in g.doelen]
            assert cats == sorted(cats)


def test_onderdeel_en_categorie():
    with opslag() as db:
        o = leerlijnoverzicht(db, onderdeel="VER", categorie="U12")
        assert len(o.groepen) == 1 and o.groepen[0].titel == "Verspringen"
        assert ids(o) == [d.id for d in db.leerdoelen("U12", leerlijn="VER")]
        door = leerlijnoverzicht(db, onderdeel="VER", categorie="U12", doorlopend=True)
        assert door.groeperen_op == "categorie" and [g.sleutel for g in door.groepen] == ["U10", "U12"]


def test_onbekende_keuzes_vallen_weg():
    with opslag() as db:
        o = leerlijnoverzicht(db, onderdeel="XYZ", categorie="U11", doorlopend=True)
        assert o.onderdeel is None and o.categorie is None and not o.doorlopend and not o.gekozen
        assert not leerlijnoverzicht(db, onderdeel="SPR", doorlopend=True).doorlopend   # zonder categorie


def test_link():
    with opslag() as db:
        o = leerlijnoverzicht(db, onderdeel="SPR", categorie="U12", doorlopend=True)
        assert o.link() == "?onderdeel=SPR&categorie=U12&doorlopend=1"
        assert o.link(categorie=None) == "?onderdeel=SPR"                 # doorlopend valt weg
        assert o.link(onderdeel=None, doorlopend=None) == "?categorie=U12"
        assert leerlijnoverzicht(db).link() == "?"


# ---------- pagina ----------
def test_pagina_zonder_keuze():
    with client() as c:
        r = c.get("/leerlijnen")
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "Deze pagina komt nog" not in html
        assert "Aantal leerdoelen per onderdeel en categorie" in html
        assert 'href="?onderdeel=SPR&amp;categorie=U10"' in html
        assert 'href="/leerlijnen" aria-current="page"' in html             # actief in het menu


def test_pagina_per_onderdeel():
    with client() as c:
        html = c.get("/leerlijnen?onderdeel=HOO").get_data(as_text=True)
        assert "Leerlijn hoogspringen" in html
        assert "De atleet weet aan welke kant hij moet beginnen met de aanloop." in html
        assert 'id="ll-U10"' in html and 'class="fases leerlijnen__opbouw"' in html
        assert 'aria-current="true">Hoogspringen' in html


def test_pagina_per_categorie():
    with client() as c:
        html = c.get("/leerlijnen?categorie=U16").get_data(as_text=True)
        assert "Leerdoelen U16" in html and "nieuw in U16" in html
        assert 'id="ll-HOR"' in html and "specialisten" in html          # HOR-U16-02 is voor specialisten
        assert "SPR-U10-01" not in html
        door = c.get("/leerlijnen?categorie=U16&doorlopend=1").get_data(as_text=True)
        assert 'title="SPR-U10-01"' in door and 'class="eerder"' in door and "U10 t/m U16" in door


def test_pagina_lege_keuze_en_rommel():
    with client() as c:
        assert c.get("/leerlijnen?onderdeel=bestaat-niet&categorie=U99").status_code == 200
        # Kogelslingeren begint pas in U12: in U10 geen doelen.
        html = c.get("/leerlijnen?onderdeel=SLI&categorie=U10").get_data(as_text=True)
        assert "Geen leerdoelen voor deze keuze" in html
