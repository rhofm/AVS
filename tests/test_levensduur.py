"""Tests voor ui/levensduur.py (AVS stopt vanzelf) en de knop 'AVS afsluiten'.

De Bewaker krijgt een nepklok, zodat minuten in een fractie van een seconde voorbijgaan.
Werkt met pytest.
"""

import contextlib
import io
import socket
import threading
import urllib.request
from pathlib import Path

import pytest

from ui import levensduur
from ui.levensduur import EERSTE_PAGINA, HARTSLAG, TIJDLIMIET, WEG_WACHTTIJD, Bewaker


class Klok:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def bw():
    klok, wand = Klok(), Klok()
    gestopt = []
    b = Bewaker(stop=lambda: gestopt.append(True), klok=klok, wandklok=wand)

    def verder(seconden: float, elke: float = 1.0, ping: dict | None = None) -> bool:
        """Laat de tijd lopen met een controle per seconde; `ping`: {pagina: om de hoeveel s}."""
        verstreken = 0.0
        while verstreken < seconden:
            klok.t += elke
            wand.t += elke
            verstreken += elke
            for pagina, om in (ping or {}).items():
                if round(verstreken / elke) % round(om / elke) == 0:
                    b.levend(pagina)
            if b.controleer():
                return True
        return False

    b.verder, b.gestopt, b.klok, b.wand = verder, gestopt, klok, wand
    return b


def test_naar_een_andere_pagina(bw):
    bw.levend("A")
    assert not bw.verder(20, ping={"A": HARTSLAG})
    bw.weg("A")                                   # pagina A verlaten ...
    assert not bw.verder(2)
    bw.levend("B")                                # ... en de volgende pagina is er
    assert not bw.verder(60, ping={"B": HARTSLAG})
    assert bw.gestopt == []


def test_laatste_tabblad_dicht(bw):
    bw.levend("A")
    bw.weg("A")
    assert not bw.verder(WEG_WACHTTIJD - 1)
    assert bw.verder(1)
    assert bw.gestopt == [True] and bw.reden == "geen pagina meer open"
    assert bw.controleer() and bw.gestopt == [True]          # maar één keer stoppen


def test_ander_verzoek_rekt_de_wachttijd(bw):
    bw.levend("A")
    bw.weg("A")
    bw.verder(WEG_WACHTTIJD - 2)
    bw.verzoek()                                  # bijv. een formulier dat net wordt verstuurd
    assert not bw.verder(WEG_WACHTTIJD - 1)


def test_twee_tabbladen(bw):
    bw.levend("A")
    bw.levend("B")
    bw.weg("A")
    assert not bw.verder(300, ping={"B": HARTSLAG})
    assert bw.open_paginas == 1
    bw.weg("B")
    assert bw.verder(WEG_WACHTTIJD)


def test_browser_gecrasht(bw):
    bw.levend("A")                                # daarna niets meer, ook geen /weg
    assert not bw.verder(TIJDLIMIET - 1)
    assert bw.verder(2)


def test_achtergrondtabblad_eens_per_minuut(bw):
    bw.levend("A")
    assert not bw.verder(30 * 60, ping={"A": 60})             # browser knijpt timers af
    assert bw.gestopt == []


def test_slaapstand(bw):
    bw.levend("A")
    bw.verder(10, ping={"A": HARTSLAG})
    bw.klok.t += 3600                             # computer sliep een uur
    bw.wand.t += 3600
    assert not bw.controleer()                    # niet stoppen bij het wakker worden
    assert not bw.verder(10, ping={"A": HARTSLAG})
    assert bw.open_paginas == 1


def test_slaapstand_alleen_wandklok(bw):
    """Op Linux telt time.monotonic de slaap niet mee: dan ziet alleen de wandklok het gat."""
    bw.levend("A")
    bw.wand.t += 3600
    assert not bw.controleer()
    assert not bw.verder(TIJDLIMIET - 5)


def test_nooit_een_pagina(bw):
    assert not bw.verder(EERSTE_PAGINA - 1)
    assert bw.verder(1)
    assert bw.reden == "geen pagina geopend na het starten"


def test_stop_nu(bw):
    bw.levend("A")
    bw.stop_nu()
    bw.stop_nu()
    assert bw.gestopt == [True] and bw.reden == "afgesloten via de knop"
    assert bw.controleer()


def test_lange_id_wordt_ingekort(bw):
    bw.levend("x" * 10_000)
    bw.weg("x" * 64)
    assert bw.open_paginas == 0


# ---------------- de webinterface ----------------
class NepBewaker:
    def __init__(self):
        self.tekens, self.gestopt = [], False

    def levend(self, p): self.tekens.append(("levend", p))
    def weg(self, p): self.tekens.append(("weg", p))
    def verzoek(self): self.tekens.append(("verzoek", None))
    def stop_nu(self): self.gestopt = True


@pytest.fixture
def app_met(tmp_path):
    from ui.app import maak_app
    nep = NepBewaker()
    app = maak_app(map=tmp_path, startfout="(test zonder databases)", sleutelfout=False, bewaker=nep)
    app.config["TESTING"] = True
    return app.test_client(), nep


def test_levend_en_weg(app_met):
    c, nep = app_met
    assert c.post("/levend", data="pagina-1", content_type="text/plain").status_code == 204
    assert c.post("/weg", data="pagina-1", headers={"Origin": "http://localhost"}).status_code == 204
    assert ("levend", "pagina-1") in nep.tekens and ("weg", "pagina-1") in nep.tekens
    assert ("verzoek", None) not in nep.tekens               # levenstekens zijn geen 'gewoon' verzoek


def test_weg_van_andere_website_telt_niet(app_met):
    c, nep = app_met
    c.post("/weg", data="pagina-1", headers={"Origin": "https://ergens.example"})
    assert ("weg", "pagina-1") not in nep.tekens


def test_gewone_pagina_telt_als_teken(app_met):
    c, nep = app_met
    c.get("/instellingen")
    assert ("verzoek", None) in nep.tekens


def test_script_en_knop_op_elke_pagina(app_met):
    c, _ = app_met
    for pad in ("/instellingen", "/atleten"):                 # ook de foutpagina
        html = c.get(pad).get_data(as_text=True)
        assert 'src="/static/levend.js" data-hartslag="15000"' in html, pad
        assert 'action="/afsluiten"' in html and "AVS afsluiten" in html, pad
    assert c.get("/static/levend.js").status_code == 200


def test_zonder_bewaker_geen_script_of_knop(tmp_path):
    from ui.app import maak_app
    app = maak_app(map=tmp_path, startfout="x", sleutelfout=False)
    html = app.test_client().get("/instellingen").get_data(as_text=True)
    assert "levend.js" not in html and "/afsluiten" not in html


def test_afsluiten(app_met):
    c, nep = app_met
    r = c.post("/afsluiten", headers={"Origin": "http://localhost"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and nep.gestopt
    assert "AVS is afgesloten" in html and "Je kunt dit tabblad nu sluiten" in html
    assert "levend.js" not in html and "/afsluiten" not in html and "Hoofdmenu" not in html


def test_afsluiten_door_andere_website(app_met):
    c, nep = app_met
    assert c.post("/afsluiten", headers={"Origin": "https://ergens.example"}).status_code == 403
    assert not nep.gestopt


# ---------------- echt: start() stopt vanzelf ----------------
def _vrije_poort() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(poort: int, pad: str, data: bytes = b"", origin: bool = True):
    kop = {"Content-Type": "text/plain"}
    if origin:
        kop["Origin"] = f"http://127.0.0.1:{poort}"
    verzoek = urllib.request.Request(f"http://127.0.0.1:{poort}{pad}", data=data, headers=kop, method="POST")
    with urllib.request.urlopen(verzoek, timeout=5) as r:
        return r.status, r.read().decode()


def _start_op_achtergrond(monkeypatch, tmp_path):
    from ui import app as app_mod
    poort = _vrije_poort()
    monkeypatch.setattr(app_mod, "_vrije_poort", lambda: poort)
    monkeypatch.setattr(app_mod, "init_db", lambda map=None: None)   # geen databases nodig
    monkeypatch.setattr(levensduur, "WEG_WACHTTIJD", 1)
    monkeypatch.setattr(levensduur, "CONTROLE", 0.05)
    klaar = threading.Event()

    def draai():
        with contextlib.redirect_stdout(io.StringIO()):
            app_mod.start(map=tmp_path, browser=False)
        klaar.set()
    threading.Thread(target=draai, daemon=True).start()
    for _ in range(100):                                       # wachten tot de server luistert
        try:
            _post(poort, "/levend", b"")
            break
        except OSError:
            klaar.wait(0.05)
    return poort, klaar


def test_start_stopt_als_laatste_pagina_weg_is(monkeypatch, tmp_path):
    poort, klaar = _start_op_achtergrond(monkeypatch, tmp_path)
    assert _post(poort, "/levend", b"p1")[0] == 204
    assert not klaar.wait(1.5)                                  # pagina open: AVS blijft draaien
    _post(poort, "/weg", b"p1")
    assert klaar.wait(5), "AVS is niet gestopt na het sluiten van de laatste pagina"


def test_start_stopt_met_de_knop(monkeypatch, tmp_path):
    poort, klaar = _start_op_achtergrond(monkeypatch, tmp_path)
    _post(poort, "/levend", b"p1")
    status, html = _post(poort, "/afsluiten")
    assert status == 200 and "AVS is afgesloten" in html       # de pagina komt nog aan ...
    assert klaar.wait(5)                                        # ... en daarna stopt AVS


# ---------------- __main__ ----------------
def test_onverwachte_fout_bij_starten(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("avs_main2", Path(__file__).resolve().parents[1] / "src" / "__main__.py")
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    meldingen = []
    monkeypatch.setattr(main, "_melding", meldingen.append)

    def kapot(browser=True):
        raise OSError("poort bezet")
    monkeypatch.setattr("ui.app.start", kapot)
    with contextlib.redirect_stderr(io.StringIO()):
        assert main.main([]) == 1
    assert len(meldingen) == 1 and "OSError: poort bezet" in meldingen[0] and "--zelftest" in meldingen[0]
