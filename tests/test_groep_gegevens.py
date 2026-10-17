"""Tests voor het wijzigen van naam en seizoen van een groep
(groepen.groep.gegevens_opslaan, pagina /groep/<id>/gegevens).

Alleen nepgegevens en een vaste testsleutel. Werkt met pytest en los:
`python tests/test_groep_gegevens.py`.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_groep_landingspagina import TESTSLEUTEL, opslag  # noqa: E402

from db.queries import OpslagFout  # noqa: E402
from groepen import groep as groepsbeheer  # noqa: E402
from models import Atleet, Groep  # noqa: E402


def _verwacht_fout(fn, tekst):
    try:
        fn()
    except OpslagFout as e:
        assert tekst in str(e), str(e)
        return
    raise AssertionError("OpslagFout verwacht")


def _groepen(db):
    leden = [db.atleet_opslaan(Atleet(f"Atleet{i}", "Test")).master_id for i in range(3)]
    g = db.groep_opslaan(Groep("Sprint", "2025-2026", leden))
    db.groep_trainingsdagen_opslaan(g.id, {"dinsdag": "18:30"})
    andere = db.groep_opslaan(Groep("Werpgroep", "2026-2027", []))
    return g, andere


def test_gegevens_opslaan():
    with opslag() as (db, _):
        g, andere = _groepen(db)
        leden = sorted(db.groep(g.id).leden)
        nieuw, veranderd = groepsbeheer.gegevens_opslaan(db, g.id, "  Sprint   U16 ", " 2026-2027 ")
        assert veranderd == ["naam 'Sprint U16'", "seizoen 2026-2027"]
        opnieuw = db.groep(g.id)
        assert (opnieuw.naam, opnieuw.seizoen) == ("Sprint U16", "2026-2027")
        assert sorted(opnieuw.leden) == leden and opnieuw.trainingsdagen == {"dinsdag": "18:30"}   # ongemoeid

        assert groepsbeheer.gegevens_opslaan(db, g.id, "Sprint U16", "2026-2027")[1] == []
        assert groepsbeheer.gegevens_opslaan(db, g.id, "Sprint U16", "")[1] == ["geen seizoen"]
        assert db.groep(g.id).seizoen is None
        # Alleen hoofdletters veranderen mag (geen botsing met zichzelf).
        assert groepsbeheer.gegevens_opslaan(db, g.id, "sprint u16", None)[1] == ["naam 'sprint u16'"]

        _verwacht_fout(lambda: groepsbeheer.gegevens_opslaan(db, g.id, " ", "2026-2027"), "naam")
        _verwacht_fout(lambda: groepsbeheer.gegevens_opslaan(db, g.id, "x" * 81, None), "te lang")
        _verwacht_fout(lambda: groepsbeheer.gegevens_opslaan(db, g.id, "Sprint", "2" * 21), "seizoen is te lang")
        _verwacht_fout(lambda: groepsbeheer.gegevens_opslaan(db, g.id, "WERPGROEP", "2026-2027"), "al een groep")
        _verwacht_fout(lambda: groepsbeheer.gegevens_opslaan(db, 9999, "X", None), "bestaat niet")
        # Zelfde naam in een ander seizoen mag wel.
        assert groepsbeheer.gegevens_opslaan(db, g.id, "Werpgroep", "2025-2026")[0].naam == "Werpgroep"


def test_seizoenkeuzes():
    with opslag() as (db, _):
        _groepen(db)
        db.groep_opslaan(Groep("Oud", "2019-2020", []))
        assert groepsbeheer.seizoenkeuzes(db, date(2026, 10, 17)) == ["2027-2028", "2026-2027", "2025-2026", "2019-2020"]
        assert groepsbeheer.seizoenkeuzes(db, date(2027, 3, 1))[0] == "2027-2028"


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        g, _ = _groepen(db)
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        assert f'href="/groep/{g.id}/gegevens"' in c.get(f"/groep/{g.id}").get_data(as_text=True)

        html = c.get(f"/groep/{g.id}/gegevens").get_data(as_text=True)
        assert 'value="Sprint"' in html and 'value="2025-2026"' in html and '<option value="2026-2027">' in html

        r = c.post(f"/groep/{g.id}/gegevens", data={"naam": "Werpgroep", "seizoen": "2026-2027"})
        assert r.status_code == 400 and "al een groep" in r.get_data(as_text=True)
        assert 'value="Werpgroep"' in r.get_data(as_text=True)                   # ingevulde waarde blijft staan
        assert db.groep(g.id).naam == "Sprint"

        r = c.post(f"/groep/{g.id}/gegevens", data={"naam": "Sprint", "seizoen": "2026-2027"})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/groep/{g.id}")
        html = c.get(f"/groep/{g.id}").get_data(as_text=True)
        assert "Gewijzigd: seizoen 2026-2027." in html and "seizoen 2026-2027" in html
        assert c.get("/groepen?seizoen=2026-2027").get_data(as_text=True).count('href="/groep/') == 2

        assert c.get("/groep/9999/gegevens").status_code == 404
        assert c.post("/groep/9999/gegevens", data={"naam": "X"}).status_code == 404


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("ok ", naam)
