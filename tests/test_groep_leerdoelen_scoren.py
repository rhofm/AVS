"""Tests voor src/groepen/leerdoelen_scoren.py en de pagina 'Leerdoelen scoren' van een groep.

Gebruikt de nepgroep uit test_groep_landingspagina (alleen nepgegevens, testsleutel).
Werkt met pytest en los: `python tests/test_groep_leerdoelen_scoren.py`.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_groep_landingspagina import TESTSLEUTEL, VANDAAG, opslag, voorbeeldgroep  # noqa: E402

from atleten import beheer  # noqa: E402
from db.queries import OpslagFout  # noqa: E402
from groepen import leerdoelen_scoren  # noqa: E402


def _verwacht(fout, fn):
    try:
        fn()
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


def _doel(db, categorie="U14", leerlijn="SPR"):
    return db.leerdoelen(categorie, leerlijn)[0]


def test_keuzes_en_rijen():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)                      # Anna en Bram U16, Cas U14 (peildatum VANDAAG)
        g = db.groep(ids["groep"])
        sp = leerdoelen_scoren.scorepagina(db, g, peildatum=VANDAAG)
        assert sp.leerdoel is None and sp.rijen == []
        gebruikt = {d.categorie for k in sp.keuzes for d in k.doelen}
        assert gebruikt <= {"U14", "U16"} and len(gebruikt) == 2     # alleen categorieën van de groep
        assert all(k.doelen for k in sp.keuzes)

        doel = _doel(db, "U14")
        sp = leerdoelen_scoren.scorepagina(db, g, doel.id, peildatum=VANDAAG)
        assert sp.leerdoel.id == doel.id and sp.leerlijn_naam
        assert {r.atleet.master_id for r in sp.rijen} == set(g.leden)
        assert [r.atleet.voornaam for r in sp.rijen if r.eigen_categorie] == ["Cas"]    # alleen Cas is U14
        _verwacht(OpslagFout, lambda: leerdoelen_scoren.scorepagina(db, g, "XXX-U10-99"))


def test_opslaan():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        g = db.groep(ids["groep"])
        doel = _doel(db, "U14")
        form = {"datum": "2026-10-01", f"score-{ids['anna']}": "4", f"score-{ids['bram']}": "2",
                f"score-{ids['cas']}": "", "iets-anders": "x"}
        assert leerdoelen_scoren.scores_opslaan(db, g, doel.id, form, date(2026, 10, 1)) == 2
        # Zelfde scores nog eens: niets nieuws in de geschiedenis. Een lege keuze wist niets.
        assert leerdoelen_scoren.scores_opslaan(db, g, doel.id, form, date(2026, 10, 8)) == 0
        form[f"score-{ids['bram']}"] = "3"
        assert leerdoelen_scoren.scores_opslaan(db, g, doel.id, form, date(2026, 10, 8)) == 1
        assert [s.score for s in db.leerdoelscores(ids["bram"], doel.id)] == [2, 3]
        assert db.leerdoelscores(ids["cas"], doel.id) == []

        sp = leerdoelen_scoren.scorepagina(db, g, doel.id, peildatum=VANDAAG)
        waarden = {r.atleet.voornaam: r.waarde for r in sp.rijen}
        assert waarden == {"Anna": 4, "Bram": 3, "Cas": None} and sp.beoordeeld == 2


def test_fouten_slaan_niets_op():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        g = db.groep(ids["groep"])
        doel = _doel(db, "U14")
        vreemd = beheer.nieuwe_atleet(db, "Vera", "Buiten", geslacht="V", geboortedatum="2011").master_id
        vandaag = date(2026, 10, 1)
        eerder = db.leerdoelscores(ids["anna"]), db.leerdoelscores(ids["bram"])                 # de nepgroep heeft er al
        _verwacht(OpslagFout, lambda: leerdoelen_scoren.scores_opslaan(
            db, g, doel.id, {f"score-{ids['anna']}": "4", f"score-{vreemd}": "3"}, vandaag))      # geen lid
        _verwacht(OpslagFout, lambda: leerdoelen_scoren.scores_opslaan(
            db, g, doel.id, {f"score-{ids['anna']}": "veel"}, vandaag))
        _verwacht(ValueError, lambda: leerdoelen_scoren.scores_opslaan(
            db, g, doel.id, {f"score-{ids['anna']}": "4", f"score-{ids['bram']}": "7"}, vandaag))
        _verwacht(OpslagFout, lambda: leerdoelen_scoren.scores_opslaan(
            db, g, "XXX-U10-99", {f"score-{ids['anna']}": "4"}, vandaag))
        assert (db.leerdoelscores(ids["anna"]), db.leerdoelscores(ids["bram"])) == eerder
        assert db.leerdoelscores(vreemd) == []


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        gid = ids["groep"]
        doel = _doel(db, "U14")
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        pad = f"/groep/{gid}/leerdoelen/scoren"

        r = c.get(pad)
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "Kies hierboven een leerdoel" in html and doel.id in html
        for p in (f"/groep/{gid}", f"/groep/{gid}/leerdoelen"):                   # links naar de nieuwe pagina
            assert pad in c.get(p).get_data(as_text=True), p
        r = c.get(f"{pad}?leerdoel={doel.id}")
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and f'name="score-{ids["anna"]}"' in html and f'name="score-{ids["cas"]}"' in html
        assert c.get(f"{pad}?leerdoel=XXX-U10-99").status_code == 404
        assert c.get(f"/groep/9999/leerdoelen/scoren").status_code == 404

        r = c.post(pad, data={"leerdoel": doel.id, "datum": "2026-10-01", f"score-{ids['anna']}": "4",
                              f"score-{ids['bram']}": "2"})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"{pad}?leerdoel={doel.id}")
        tekst = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "2 scores opgeslagen." in tekst and f'name="score-{ids["anna"]}" value="4" checked' in tekst
        r = c.post(pad, data={"leerdoel": doel.id, "datum": "2026-10-01", f"score-{ids['anna']}": "4"})
        assert "Geen scores gewijzigd." in c.get(r.headers["Location"]).get_data(as_text=True)

        for data, melding in (({"leerdoel": doel.id, "datum": "geen"}, "geldige datum"),
                              ({"leerdoel": doel.id, "datum": "2999-01-01"}, "toekomst"),
                              ({"leerdoel": doel.id, "datum": "2026-10-01", f"score-{ids['cas']}": "9"}, "Niet opgeslagen"),
                              ({"leerdoel": doel.id, "datum": "2026-10-01", "score-" + "0" * 32: "3"}, "Niet opgeslagen")):
            r = c.post(pad, data=data)
            assert r.status_code == 400 and melding in r.get_data(as_text=True), data
        assert c.post(pad, data={"datum": "2026-10-01"}).status_code == 400
        assert c.post("/groep/9999/leerdoelen/scoren", data={"leerdoel": doel.id}).status_code == 404
        assert db.leerdoelscores(ids["cas"]) == []


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
