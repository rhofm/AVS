"""Tests voor src/groepen/groep.py (atleten van een groep wijzigen) en de route /groep/<id>/leden.

Gebruikt de nepgroep uit test_groep_landingspagina (alleen nepgegevens, testsleutel).
Werkt met pytest en los: `python tests/test_groep_leden.py`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_groep_landingspagina import TESTSLEUTEL, VANDAAG, opslag, voorbeeldgroep  # noqa: E402

from atleten import beheer  # noqa: E402
from db.queries import OpslagFout  # noqa: E402
from groepen import groep as groepsbeheer  # noqa: E402


def test_formulier():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)                       # U16 sprint: Anna, Bram, Cas; Dirk Buiten zit nergens in
        oud = beheer.nieuwe_atleet(db, "Oud", "Lid", actief=False).master_id
        f = groepsbeheer.ledenformulier(db, ids["groep"], peildatum=VANDAAG)
        assert [k.atleet.voornaam for k in f.leden] == ["Cas", "Bram", "Anna"]             # op achternaam
        assert {k.atleet.voornaam: k.andere_groepen for k in f.leden}["Cas"] == ["Werpgroep"]
        assert [k.atleet.voornaam for k in f.overigen] == ["Dirk"]                          # niet-actieve niet
        assert oud not in [k.atleet.master_id for k in f.overigen]
        assert groepsbeheer.ledenformulier(db, 9999) is None


def test_opslaan():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        dirk = [a for a in db.atleten() if a.voornaam == "Dirk"][0].master_id
        w = groepsbeheer.leden_opslaan(db, ids["groep"], [ids["anna"], ids["cas"], dirk, dirk, ""])
        assert [a.voornaam for a in w.toegevoegd] == ["Dirk"] and [a.voornaam for a in w.verwijderd] == ["Bram"]
        assert w.tekst == "Atleten gewijzigd: 1 toegevoegd (Dirk Buiten); 1 verwijderd (Bram Test)."
        assert set(db.groep(ids["groep"]).leden) == {ids["anna"], ids["cas"], dirk}
        # De geschiedenis van Bram blijft bewaard.
        assert [a.status for a in db.absenties_van_atleet(ids["bram"])] == ["afwezig", "aanwezig"]
        assert db.groep(ids["werp"]).leden == [ids["cas"]]                                  # andere groep ongemoeid

        w = groepsbeheer.leden_opslaan(db, ids["groep"], [ids["anna"], ids["cas"], dirk])
        assert w.leeg and w.tekst == "Niets gewijzigd."
        w = groepsbeheer.leden_opslaan(db, ids["groep"], [])
        assert len(w.verwijderd) == 3 and db.groep(ids["groep"]).leden == []

        for fout in (["0" * 32], ["kort"]):
            try:
                groepsbeheer.leden_opslaan(db, ids["groep"], fout)
                assert False, "onbekende atleet moet een fout geven"
            except OpslagFout:
                pass
        assert db.groep(ids["groep"]).leden == []                                           # niets half opgeslagen
        try:
            groepsbeheer.leden_opslaan(db, 9999, [])
            assert False
        except OpslagFout:
            pass


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        gid = ids["groep"]
        dirk = [a for a in db.atleten() if a.voornaam == "Dirk"][0].master_id
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        assert f'href="/groep/{gid}/leden"' in c.get(f"/groep/{gid}").get_data(as_text=True)
        html = c.get(f"/groep/{gid}/leden").get_data(as_text=True)
        assert f'value="{ids["anna"]}" id="lid-{ids["anna"]}" checked' in html
        assert f'value="{dirk}" id="lid-{dirk}">' in html
        r = c.post(f"/groep/{gid}/leden", data={"lid": [ids["anna"], dirk]})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/groep/{gid}#kop-atleten")
        tekst = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "1 toegevoegd (Dirk Buiten); 2 verwijderd (Cas Proef, Bram Test)" in tekst
        assert "Dirk Buiten" in tekst
        r = c.post(f"/groep/{gid}/leden", data={"lid": ["0" * 32]})
        assert r.status_code == 400 and "Niet opgeslagen" in r.get_data(as_text=True)
        assert c.get("/groep/9999/leden").status_code == 404
        assert c.post("/groep/9999/leden", data={}).status_code == 404


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
