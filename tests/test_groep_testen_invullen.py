"""Tests voor groepen/testen_invullen.py en de pagina 'Testresultaten invullen' van een groep.

Alleen nepgegevens en een vaste testsleutel (de nepgroep uit test_groep_landingspagina).

"""

from datetime import date

import pytest
from test_groep_landingspagina import opslag, voorbeeldgroep
from test_testen_paginas import form
from hulp import app_client

from groepen import testen_invullen as ti
from testen import resultaten as res
from testen import sjabloon as sj
from testen.sjabloon import Onderdeel, Sjabloon

DAG = date(2026, 10, 20)


def sprong() -> Sjabloon:
    return Sjabloon("Sprongkracht", [Onderdeel("Hoog", "lengte", "C1 * L", [100]), Onderdeel("Sprint", "tijd", "C1 / T", [150])])


def veld(mid, i):
    return ti.veldnaam(mid, i)


def test_pagina_en_opslaan():
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        g = db.groep(ids["groep"])
        s = res.sjabloon_opslaan(db, sprong(), tmp)
        bib = sj.laad_bibliotheek(tmp)
        assert ti.invulpagina(db, g, bib).sjabloon is None                        # niets gekozen
        with pytest.raises(ti.OpslagFout):
            ti.invulpagina(db, g, bib, "bestaat-niet")
        res.resultaat_vastleggen(db, ids["anna"], s, date(2026, 9, 1), ["0,4", "5"])
        ip = ti.invulpagina(db, g, bib, s.slug)
        assert sorted(r.atleet.voornaam for r in ip.rijen) == ["Anna", "Bram", "Cas"]
        rij = {r.atleet.voornaam: r for r in ip.rijen}
        assert rij["Anna"].laatste is not None and rij["Bram"].laatste is None and ip.met_laatste == 1
        assert all(r.invoer == ["", ""] for r in ip.rijen)
        # Bram en Cas ingevuld, Anna leeg: twee resultaten.
        f = {veld(ids["bram"], 0): "0,5", veld(ids["bram"], 1): "4", veld(ids["cas"], 0): "0,4", veld(ids["cas"], 1): "5", veld(ids["anna"], 0): ""}
        assert ti.resultaten_opslaan(db, g, s, f, DAG) == 2
        assert len(db.testresultaten(ids["anna"])) == 1
        (b,) = db.testresultaten(ids["bram"])
        assert (b.datum, b.score) == (DAG, pytest.approx(87.5)) and [d.deel for d in b.delen] == [0, 1]


def test_fouten_slaan_niets_op():
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        g = db.groep(ids["groep"])
        s = res.sjabloon_opslaan(db, sprong(), tmp)
        goed = {veld(ids["bram"], 0): "0,5", veld(ids["bram"], 1): "4"}
        with pytest.raises(ti.GroepInvoerFout) as e:
            ti.resultaten_opslaan(db, g, s, {**goed, veld(ids["cas"], 0): "abc", veld(ids["cas"], 1): "5",
                                              veld(ids["anna"], 0): "1"}, DAG)                  # Anna: totaal vraagt beide
        assert set(e.value.fouten) == {ids["cas"], ids["anna"]} and "geen geldig getal" in e.value.fouten[ids["cas"]]
        assert db.testresultaten(ids["bram"]) == []                                              # ook Bram niet
        with pytest.raises(ti.GroepInvoerFout, match="niets ingevuld"):
            ti.resultaten_opslaan(db, g, s, {}, DAG)
        with pytest.raises(ti.GroepInvoerFout, match="niet \\(meer\\) in deze groep"):
            ti.resultaten_opslaan(db, g, s, {**goed, veld("0" * 32, 0): "1"}, DAG)
        with pytest.raises(ti.GroepInvoerFout) as e:
            ti.resultaten_opslaan(db, g, s, goed, date(2999, 1, 1))
        assert "toekomst" in e.value.fouten[ids["bram"]]
        assert db.testresultaten(ids["bram"]) == []


def test_routes():
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        gid = ids["groep"]
        c = app_client(tmp)
        html = c.get(f"/groep/{gid}/testen").get_data(as_text=True)
        assert f"/groep/{gid}/testen/invullen" in html
        r = c.get(f"/groep/{gid}/testen/invullen")
        assert r.status_code == 200 and "Kies hierboven een test" in r.get_data(as_text=True)
        assert c.get("/groep/9999/testen/invullen").status_code == 404
        assert c.get(f"/groep/{gid}/testen/invullen?sjabloon=bestaat-niet").status_code == 404
        html = c.get(f"/groep/{gid}/testen/invullen?sjabloon=30m_vliegend").get_data(as_text=True)
        assert f'name="waarde-{ids["anna"]}-0"' in html and f'name="waarde-{ids["bram"]}-0"' in html
        # Nieuw sjabloon vanaf de groep -> meteen de groepspagina met dat sjabloon.
        d = form("Sprongkracht", [("Hoog", "lengte", "C1 * L", ["100"]), ("Sprint", "tijd", "C1 / T", ["150"])],
                 actie="opslaan", groep=str(gid))
        r = c.post("/testen/sjablonen/nieuw", data=d)
        assert r.status_code == 302 and r.headers["Location"] == f"/groep/{gid}/testen/invullen?sjabloon=sprongkracht"
        assert f'value="{gid}"' in c.get(f"/testen/sjablonen/nieuw?groep={gid}").get_data(as_text=True)
        assert f"/groep/{gid}/testen" in c.get(f"/testen/sjablonen?groep={gid}").get_data(as_text=True)
        pad = f"/groep/{gid}/testen/invullen"
        basis = {"sjabloon": "sprongkracht", "datum": "2026-10-20"}
        # Fout: het formulier komt terug met de invoer en de fout bij de atleet.
        r = c.post(pad, data={**basis, veld(ids["bram"], 0): "0,5", veld(ids["bram"], 1): "4", veld(ids["cas"], 0): "x", veld(ids["cas"], 1): "1"})
        html = r.get_data(as_text=True)
        assert r.status_code == 400 and "geen geldig getal" in html and 'value="0,5"' in html
        assert db.testresultaten(ids["bram"]) == []
        assert c.post(pad, data={**basis, "datum": "kapot"}).status_code == 400
        assert c.post(pad, data={**basis, "datum": "2999-01-01", veld(ids["bram"], 0): "1", veld(ids["bram"], 1): "1"}).status_code == 400
        assert c.post(pad, data={**basis, veld("0" * 32, 0): "1"}).status_code == 400
        assert c.post(pad, data={"sjabloon": "bestaat-niet", "datum": "2026-10-20"}).status_code == 404
        assert c.post("/groep/9999/testen/invullen", data=basis).status_code == 404
        # Goed.
        r = c.post(pad, data={**basis, veld(ids["bram"], 0): "0,5", veld(ids["bram"], 1): "4", veld(ids["cas"], 0): "0,4", veld(ids["cas"], 1): "5"},
                   follow_redirects=True)
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "2 resultaten" in html and "87,5" in html
        assert len(db.testresultaten(ids["bram"])) == 1 and len(db.testresultaten(ids["cas"])) == 1
        assert "Hoog" in c.get(f"/groep/{gid}/testen").get_data(as_text=True)
