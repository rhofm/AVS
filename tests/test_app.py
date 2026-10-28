"""Tests voor src/ui/app.py (Flask): alle pagina's, opslaan van leerdoelen en foutpagina's.

Tijdelijke map met versleutelde databases, vaste testsleutel, alleen nepgegevens.

"""

import contextlib
import io
import re
import tempfile
from pathlib import Path

from test_landingspagina import voorbeeld

from db.init_db import init_db
from db.queries import Opslag
from ui.app import maak_app
from hulp import TESTSLEUTEL


@contextlib.contextmanager
def client():
    """(Flask-testclient, master_id van Anna) met een tijdelijke database."""
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            from models import Onderdeel
            db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
            db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
            mid = voorbeeld(db)
        app = maak_app(map=Path(tmp), hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        yield app.test_client(), mid, Path(tmp)


def tekst(r) -> str:
    return r.get_data(as_text=True)


def test_paginas():
    with client() as (c, mid, _):
        assert c.get("/").status_code == 200                           # startpagina (zie test_startpagina.py)
        r = c.get("/atleten")
        assert r.status_code == 200 and "Anna Voorbeeld" in tekst(r) and "U16 sprint" in tekst(r)
        assert ">U16V</td>" in tekst(r)
        assert "Anna" not in tekst(c.get("/atleten?q=zzz"))
        assert c.get("/static/avs.css").status_code == 200

        r = c.get(f"/atleet/{mid}")
        assert r.status_code == 200 and "Trainingsschema" in tekst(r)
        # Elke link naar een eigen pagina van de atleet moet werken (geen 404).
        for pad in sorted(set(re.findall(rf'href="(/atleet/{mid}/[^"]*)"', tekst(r)))):
            assert c.get(pad).status_code == 200, pad
        for pad in ("wedstrijden", "wedstrijden?weergave=kalender", "aanwezigheid", "leerdoelen",
                    "leerdoelen?doorlopend=1", "leerdoelen?modus=bewerken"):
            assert c.get(f"/atleet/{mid}/{pad}").status_code == 200, pad
        assert 'value="kalender" checked' in tekst(c.get(f"/atleet/{mid}/aanwezigheid?weergave=kalender"))
        for pad in ("groepen", "wedstrijden", "ploegen", "leerlijnen", "importeren", "instellingen"):
            assert c.get(f"/{pad}").status_code == 200, pad


def test_niet_gevonden():
    with client() as (c, mid, _):
        assert c.get("/atleet/" + "0" * 32).status_code == 404
        assert c.get("/atleet/" + "0" * 32 + "/leerdoelen").status_code == 404
        assert c.get(f"/atleet/{mid}/bestaat-niet").status_code == 404
        assert "bestaat niet" in tekst(c.get("/onzin"))


def test_leerdoelen_opslaan():
    with client() as (c, mid, tmp):
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            doelen = [d.id for d in db.leerdoelen("U16")][:2]
        form = {"datum": "2026-10-01", f"score-{doelen[0]}": "4", f"score-{doelen[1]}": "2"}
        r = c.post(f"/atleet/{mid}/leerdoelen", data=form)
        assert r.status_code == 302                                    # Post/Redirect/Get
        r = c.get(r.headers["Location"])
        assert "2 scores opgeslagen." in tekst(r)
        assert f'name="score-{doelen[0]}" value="4" checked' in tekst(r)
        # Nog eens hetzelfde: niets gewijzigd.
        assert "Geen scores gewijzigd." in tekst(c.post(f"/atleet/{mid}/leerdoelen", data=form, follow_redirects=True))
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            assert [s.score for s in db.leerdoelscores(mid, doelen[0])] == [4]

        # Fouten: pagina blijft in bewerkstand met een melding, niets opgeslagen.
        r = c.post(f"/atleet/{mid}/leerdoelen", data={**form, "datum": "gisteren"})
        assert r.status_code == 400 and "geldige datum" in tekst(r) and 'value="bewerken" checked' in tekst(r)
        r = c.post(f"/atleet/{mid}/leerdoelen", data={**form, "datum": "2999-01-01"})
        assert r.status_code == 400 and "toekomst" in tekst(r)
        r = c.post(f"/atleet/{mid}/leerdoelen", data={"datum": "2026-10-02", f"score-{doelen[0]}": "9"})
        assert r.status_code == 400 and "Niet opgeslagen" in tekst(r)
        r = c.post(f"/atleet/{mid}/leerdoelen?doorlopend=1", data={"datum": "2026-10-02", f"score-{doelen[1]}": "3"})
        assert r.headers["Location"].endswith("doorlopend=1")
