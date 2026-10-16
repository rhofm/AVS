"""Tests voor het bewerken van een training (warming-up, kern A, kern B, cooling-down, notities)
en het toevoegen, bewerken en verwijderen van een afwijkende training voor enkele atleten.

Logica in groepen.trainingen, routes /training/<id>/bewerken, /variant/nieuw en /verwijderen.
Alleen nepgegevens en een vaste testsleutel. Werkt met pytest en los:
`python tests/test_training_bewerken.py`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_trainingen_inhoud import TESTSLEUTEL, _basis, _verwacht, opslag  # noqa: E402

from db.queries import OpslagFout  # noqa: E402
from groepen import trainingen as trainingsbeheer  # noqa: E402


def test_training_bewerken():
    with opslag() as (db, _):
        anna, bas, cor, buiten, g, t = _basis(db)
        t2 = trainingsbeheer.training_bewerken(db, t.id, {
            "onderwerp": "  Versnellingen ", "warming_up": "Inlopen\r\nABC", "kern_a": "",
            "kern_b": "4x 60 m", "cooling_down": "Uitlopen", "notities": ""})
        assert t2.onderwerp == "Versnellingen" and t2.warming_up == "Inlopen\nABC"
        assert t2.kern_a is None and t2.notities is None and t2.kern_b == "4x 60 m"
        _verwacht(OpslagFout, lambda: trainingsbeheer.training_bewerken(db, t.id, {"onderwerp": "x" * 121}))
        _verwacht(OpslagFout, lambda: trainingsbeheer.training_bewerken(db, 9999, {}))


def test_variant_toevoegen_bewerken_verwijderen():
    with opslag() as (db, _):
        anna, bas, cor, buiten, g, t = _basis(db)
        f = trainingsbeheer.variantformulier(db, t.id)
        assert f.nieuw and f.waarden["onderwerp"] == "" and f.waarden["kern_b"] == "3x 150 m"   # begint als kopie
        assert [k.atleet.voornaam for k in f.atleten] and not any(k.gekozen for k in f.atleten)

        v = trainingsbeheer.variant_toevoegen(db, t.id, {"onderwerp": "Revalidatie", "kern_a": "Fietsen"},
                                              [anna.master_id])
        assert v.is_afwijkend and v.hoofdtraining_id == t.id and v.atleten == [anna.master_id]
        assert [x.id for x in db.trainingen(g.id)] == [t.id]                 # lijst toont alleen de gewone

        # Anna staat al in een variant: in een tweede variant gemarkeerd, en dubbel kiezen mag niet.
        f2 = trainingsbeheer.variantformulier(db, t.id)
        assert {k.atleet.voornaam: k.elders for k in f2.atleten}["Anna"] == "Revalidatie"
        _verwacht(OpslagFout, lambda: trainingsbeheer.variant_toevoegen(db, t.id, {}, [anna.master_id]))
        _verwacht(OpslagFout, lambda: trainingsbeheer.variant_toevoegen(db, t.id, {}, []))           # niemand
        _verwacht(OpslagFout, lambda: trainingsbeheer.variant_toevoegen(db, t.id, {}, [buiten.master_id]))
        _verwacht(OpslagFout, lambda: trainingsbeheer.variant_toevoegen(db, v.id, {}, [bas.master_id]))  # variant van variant

        fb = trainingsbeheer.bewerkformulier(db, v.id)
        assert fb.is_variant and not fb.nieuw and fb.hoofd.id == t.id
        assert {k.atleet.voornaam: k.gekozen for k in fb.atleten}["Anna"] and fb.atleten[0].elders is None
        v = trainingsbeheer.training_bewerken(db, v.id, {"onderwerp": "Revalidatie", "kern_a": "Zwemmen"},
                                              [anna.master_id, bas.master_id])
        assert sorted(v.atleten) == sorted([anna.master_id, bas.master_id]) and v.kern_a == "Zwemmen"

        _verwacht(OpslagFout, lambda: trainingsbeheer.variant_verwijderen(db, t.id))   # gewone training niet
        assert trainingsbeheer.variant_verwijderen(db, v.id).id == t.id
        assert db.training(v.id) is None and db.training(t.id) is not None


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        anna, bas, cor, buiten, g, t = _basis(db)
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()

        html = c.get(f"/training/{t.id}").get_data(as_text=True)
        assert f'href="/training/{t.id}/bewerken"' in html and f'href="/training/{t.id}/variant/nieuw"' in html

        html = c.get(f"/training/{t.id}/bewerken").get_data(as_text=True)
        assert "Training bewerken" in html and html.count("<textarea") == 5 and 'name="atleet"' not in html
        for veld in ("warming_up", "kern_a", "kern_b", "cooling_down", "notities"):
            assert f'name="{veld}"' in html

        r = c.post(f"/training/{t.id}/bewerken", data={"onderwerp": "Starts", "warming_up": "<script>x</script>",
                                                       "kern_a": "**6x 30 m**"})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/training/{t.id}")
        html = c.get(f"/training/{t.id}").get_data(as_text=True)
        assert "Training opgeslagen." in html and "<strong>6x 30 m</strong>" in html
        assert "<script>x</script>" not in html                                     # markdown escapet html

        r = c.post(f"/training/{t.id}/bewerken", data={"onderwerp": "x" * 121, "kern_a": "bewaard"})
        assert r.status_code == 400 and "te lang" in r.get_data(as_text=True) and "bewaard" in r.get_data(as_text=True)

        # Afwijkende training
        html = c.get(f"/training/{t.id}/variant/nieuw").get_data(as_text=True)
        assert html.count('name="atleet"') == 3 and "Toevoegen" in html            # Dirk zit niet in de groep
        r = c.post(f"/training/{t.id}/variant/nieuw", data={"onderwerp": "Revalidatie", "kern_a": "Fietsen"})
        assert r.status_code == 400 and "Niet opgeslagen" in r.get_data(as_text=True)   # niemand gekozen
        r = c.post(f"/training/{t.id}/variant/nieuw",
                   data={"onderwerp": "Revalidatie", "kern_a": "Fietsen", "atleet": [anna.master_id]})
        v = db.varianten(t.id)[0]
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/training/{t.id}#kop-variant-{v.id}")
        html = c.get(f"/training/{t.id}").get_data(as_text=True)
        assert "Afwijkende training toegevoegd voor 1 atleet." in html and "Revalidatie" in html
        assert f'href="/training/{v.id}/bewerken"' in html

        html = c.get(f"/training/{v.id}/bewerken").get_data(as_text=True)
        assert "Afwijkende training bewerken" in html and f'action="/training/{v.id}/verwijderen"' in html
        assert c.post(f"/training/{t.id}/verwijderen").status_code == 404          # gewone training niet
        r = c.post(f"/training/{v.id}/verwijderen")
        assert r.status_code == 302 and db.varianten(t.id) == []

        for url in ("/training/9999/bewerken", "/training/9999/variant/nieuw", f"/training/{v.id}/bewerken"):
            assert c.get(url).status_code == 404, url
        assert c.post("/training/9999/verwijderen").status_code == 404


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("ok ", naam)
