"""Alleen AVS zelf: de Host-kop moet AVS zijn (tegen DNS rebinding) en alles wat iets
verandert moet van een AVS-pagina komen (tegen CSRF). Zie ui.app.controleer_herkomst.

De app draait hier met een startfout: dan zijn er geen databases of sleutel nodig, en werken
de Instellingen (lezen en opslaan) toch.
"""

import pytest

from ui.app import maak_app

EIGEN = "http://localhost"              # de test-client draait op 'localhost'
VREEMD = "https://kwaadaardig.example"


@pytest.fixture
def app(tmp_path):
    a = maak_app(map=tmp_path, startfout="x", sleutelfout=False)
    a.config["TESTING"] = True
    return a


@pytest.fixture
def c(app):
    return app.test_client()


def _opslaan(c, **headers):
    return c.post("/instellingen", data={"thema": "donker"}, headers=headers)


def _opgeslagen(tmp_path) -> bool:
    return (tmp_path / "instellingen.json").exists()


# ---------------- Host ----------------
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.1:5050", "localhost:61234"])
def test_eigen_host(c, host):
    assert c.get("/instellingen", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["kwaadaardig.example", "kwaadaardig.example:5050", "192.168.1.10:5050",
                                  "127.0.0.1.kwaadaardig.example", "localhost.kwaadaardig.example"])
def test_vreemde_host_krijgt_niets(c, host):
    r = c.get("/instellingen", headers={"Host": host})
    assert r.status_code == 400 and "<html" not in r.get_data(as_text=True).lower()


def test_vreemde_host_ook_niet_bij_statische_bestanden(c):
    assert c.get("/static/levend.js", headers={"Host": "kwaadaardig.example"}).status_code == 400


def test_vreemde_host_mag_niets_opslaan(c, tmp_path):
    r = c.post("/instellingen", data={"thema": "donker"}, headers={"Host": "kwaadaardig.example"})
    assert r.status_code == 400 and not _opgeslagen(tmp_path)


# ---------------- herkomst van een POST ----------------
def test_post_van_avs_zelf(c, tmp_path):
    assert _opslaan(c, Origin=EIGEN).status_code == 302 and _opgeslagen(tmp_path)


def test_post_zonder_herkomst_telt_als_avs(c, tmp_path):
    """Oude browser of test-client: geen Sec-Fetch-Site, Origin of Referer."""
    assert _opslaan(c).status_code == 302 and _opgeslagen(tmp_path)


@pytest.mark.parametrize("headers", [
    {"Origin": VREEMD},
    {"Referer": VREEMD + "/pagina"},
    {"Origin": "null"},                                   # bijv. vanaf een sandboxed iframe
    {"Origin": "http://localhost:9999"},                  # een ander programma op deze computer
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Site": "cross-site", "Origin": EIGEN},    # Sec-Fetch-Site gaat voor
])
def test_post_van_andere_website_geweigerd(c, tmp_path, headers):
    assert _opslaan(c, **headers).status_code == 403 and not _opgeslagen(tmp_path)


def test_sec_fetch_site_same_origin_ook_met_origin_null(c, tmp_path):
    """Op de pagina met de herstelsleutel (Referrer-Policy: no-referrer) stuurt de browser
    Origin 'null' mee, ook naar AVS zelf; Sec-Fetch-Site zegt dan wel 'same-origin'."""
    r = _opslaan(c, Origin="null", **{"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 302 and _opgeslagen(tmp_path)


def test_geweigerd_voor_de_startfout(c):
    """De herkomst wordt als eerste gecontroleerd: ook pagina's die een database nodig hebben
    (hier geblokkeerd door de startfout) weigeren een vreemd verzoek met 403."""
    r = c.post("/atleet/0123/verwijderen", headers={"Origin": VREEMD})
    assert r.status_code == 403


def test_get_van_andere_website_mag(c):
    """Een link volgen van een andere site is gewoon; lezen kan die site het antwoord niet."""
    assert c.get("/instellingen", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_geweigerd_verzoek_is_geen_teken_van_leven(app):
    class NepBewaker:
        verzoeken = 0

        def verzoek(self):
            self.verzoeken += 1

    app.config["AVS_BEWAKER"] = nep = NepBewaker()
    c = app.test_client()
    c.get("/instellingen", headers={"Host": "kwaadaardig.example"})
    c.post("/instellingen", data={"thema": "donker"}, headers={"Origin": VREEMD})
    assert nep.verzoeken == 0
    c.get("/instellingen")
    assert nep.verzoeken == 1
