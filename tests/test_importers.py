"""Tests voor importers, tegen opgeslagen (geanonimiseerde) pagina's in fixtures/."""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.importers import atletieknu_prs, atletieknu_wedstrijd, base, detect, seltec  # noqa: E402
from src.importers import seltec  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SELTEC_URL = "https://uitslagen.atletiek.nl/Competitions/Resultoverview/19133"


class TestSeltec(unittest.TestCase):
    """
    fixtures/seltec_uitslagenoverzicht.html: ingekort uitslagenoverzicht van een echte Seltec-wedstrijd
    (NK U18/U20 2026) met verzonnen namen, verenigingen, startnummers en id's. Prestaties, wind en
    pogingen zijn echt, zodat het parsen realistisch getest wordt.
    Testatleten: 'Tim Proefmans' en 'Bas Proefmans' (U18M) en 'Lotte Testerink' (U20V) van 'AV Testclub'.
    """

    @classmethod
    def setUpClass(cls):
        html = (FIXTURES / "seltec_uitslagenoverzicht.html").read_text(encoding="utf-8")
        cls.wedstrijd, cls.alle = seltec.parse_overzicht(html, SELTEC_URL)

    def zoek(self, atleet, onderdeel, ronde):
        rijen = [u for u in self.alle if u.atleet == atleet and u.onderdeel == onderdeel and u.ronde == ronde]
        self.assertEqual(len(rijen), 1, f"{atleet} {onderdeel} {ronde}")
        return rijen[0]

    # ---------------------------------------------------------------- wedstrijd

    def test_wedstrijd(self):
        w = self.wedstrijd
        self.assertEqual(w.wedstrijd_id, "19133")
        self.assertEqual(w.naam, "Testwedstrijd U18 & U20")
        self.assertEqual(w.plaats, "Teststad")
        self.assertEqual((w.datum, w.einddatum), ("2026-09-18", "2026-09-20"))

    def test_kop_met_een_dag_en_over_de_maand(self):
        from bs4 import BeautifulSoup
        een = seltec.parse_wedstrijd(BeautifulSoup("<h1>20 sep 2026 Clubmeet - Nijmegen</h1>", "html.parser"))
        self.assertEqual((een.naam, een.plaats, een.datum, een.einddatum),
                         ("Clubmeet", "Nijmegen", "2026-09-20", "2026-09-20"))
        twee = seltec.parse_wedstrijd(BeautifulSoup("<h1>30 sep - 2 okt 2026 Meerdaags - Plaats</h1>", "html.parser"))
        self.assertEqual((twee.datum, twee.einddatum), ("2026-09-30", "2026-10-02"))

    # ---------------------------------------------------------------- uitslagen

    def test_sprint_met_wind_per_serie(self):
        u = self.zoek("Tim Proefmans", "100 m", "Series")
        self.assertEqual((u.prestatie, u.waarde), ("11,74", 11.74))
        self.assertEqual(u.wind, "+0,9 m/s")             # serie II
        self.assertEqual((u.positie, u.kwalificatie, u.record), ("17", "Q", "PB"))
        self.assertEqual((u.categorie, u.geboortejaar, u.vereniging), ("U18M", "2009", "AV Testclub"))
        self.assertEqual(u.datum, "2026-09-18")
        self.assertEqual(u.onderdeel_code, "982650")
        self.assertEqual(u.uitslag_url, "https://uitslagen.atletiek.nl/Competitions/CurrentList/982650/19133")

    def test_halve_finale(self):
        u = self.zoek("Bas Proefmans", "100 m", "Halve finales")
        self.assertEqual((u.prestatie, u.wind, u.positie), ("12,03", "+0,1 m/s", "19"))

    def test_verspringen_pogingen_met_wind(self):
        u = self.zoek("Bas Proefmans", "Verspringen", "Kwalificatie")
        self.assertEqual((u.prestatie, u.wind), ("5,29", "+1,9 m/s"))
        self.assertEqual(u.pogingen, "5,24 (+2,1) | 5,29 (+1,9) | 5,23 (+2,5)")

    def test_werpen_zonder_wind(self):
        u = self.zoek("Lotte Testerink", "Speerwerpen", "Finale")
        self.assertEqual((u.prestatie, u.wind, u.pogingen), ("27,74", "", "x | x | 27,74"))
        self.assertEqual(u.datum, "2026-09-19")

    def test_hoogspringen_per_hoogte(self):
        hoog = [u for u in self.alle if u.onderdeel == "Hoogspringen" and u.positie == "1"]
        self.assertEqual(len(hoog), 1)
        self.assertEqual(hoog[0].prestatie, "1,68")
        self.assertTrue(hoog[0].pogingen.startswith("1,51 O | 1,55 O"))   # "-" op 1,46 overgeslagen
        self.assertTrue(hoog[0].pogingen.endswith("1,70 XXX"))

    def test_geen_geldige_prestatie(self):
        statussen = {u.prestatie for u in self.alle if u.waarde is None}
        self.assertTrue({"DNS", "DNF", "DQ", "nm."} <= statussen)
        for u in self.alle:
            if u.waarde is None:
                self.assertEqual((u.positie, u.wind), ("", ""))

    def test_opmerkingen_en_naamtoevoeging(self):
        dq = [u for u in self.alle if u.prestatie == "DQ" and "TR16.8" in u.opmerking]
        self.assertTrue(dq)
        gk = [u for u in self.alle if u.opmerking == "GK"]
        self.assertTrue(gk)
        self.assertNotIn("[", gk[0].atleet)

    def test_onderdeel_ronde_en_specificatie_uit_titel(self):
        self.assertEqual(seltec.splits_titel("100 m U18M Halve finales", "U18M"), ("100 m", "Halve finales", ""))
        self.assertEqual(seltec.splits_titel("Speerwerpen  U20V Finale", "U20V"), ("Speerwerpen", "Finale", ""))
        self.assertEqual(seltec.splits_titel("Kogelstoten U18V 3kg Finale", "U18V"), ("Kogelstoten", "Finale", "3kg"))

    def test_to_number(self):
        self.assertEqual(seltec.to_number("4:19,57"), 259.57)
        self.assertEqual(seltec.to_number("1:02:03,4"), 3723.4)
        self.assertIsNone(seltec.to_number("nm."))

    # ---------------------------------------------------------------- filteren

    def test_filter_atleten(self):
        gevonden, ontbrekend = seltec.filter_atleten(
            self.alle, ["tim proefmans", "Bas Proefmans", "Lotte Testerink", "Niet Bestaand"])
        self.assertEqual(len(gevonden), 7)
        self.assertEqual(ontbrekend, ["Niet Bestaand"])

    def test_filter_vereniging(self):
        self.assertEqual(len(seltec.filter_vereniging(self.alle, "AV Testclub")), 42)
        self.assertEqual(len(seltec.filter_vereniging(self.alle, "testclub")), 42)   # 'bevat', hoofdletterongevoelig

    def test_alleen_een_onderdeellijst(self):
        html = (FIXTURES / "seltec_uitslagenoverzicht.html").read_text(encoding="utf-8")
        _, rijen = seltec.parse_overzicht(html, SELTEC_URL, alleen_lijst="982650")
        self.assertTrue(rijen)
        self.assertEqual({(u.onderdeel, u.ronde) for u in rijen}, {("100 m", "Series")})

    # ---------------------------------------------------------------- interface

    def test_can_handle_en_urls(self):
        self.assertTrue(seltec.can_handle(SELTEC_URL))
        self.assertTrue(seltec.can_handle("https://uitslagen.atletiek.nl/Competitions/CurrentList/982650/19133"))
        self.assertFalse(seltec.can_handle("https://www.atletiek.nu/wedstrijd/uitslagen/43465/"))
        self.assertEqual(seltec.overzicht_url("https://uitslagen.atletiek.nl/Competitions/CurrentList/982650/19133"),
                         SELTEC_URL)
        self.assertEqual(seltec.overzicht_url("19133"), SELTEC_URL)


class NepAntwoord:
    """Minimale vervanger van requests.Response voor de ophaal-tests."""

    def __init__(self, status=200, tekst="<html>ok</html>", headers=None):
        self.status_code, self.text, self.headers, self.encoding = status, tekst, headers or {}, "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


class NepSessie:
    def __init__(self, antwoorden):
        self.antwoorden, self.urls = list(antwoorden), []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self.antwoorden.pop(0)


class TestBase(unittest.TestCase):
    """De gedeelde Importer-basisklasse en hulpfuncties uit importers/base.py."""

    def importer(self, klasse, antwoorden):
        imp = klasse()
        imp._sessie = NepSessie(antwoorden)
        imp.eerste_wachttijd = 0          # niet echt wachten in tests
        imp.pauze = 0
        return imp

    def test_to_number_beide_uurnotaties(self):
        self.assertEqual(base.to_number("1:54,71"), 114.71)
        self.assertEqual(base.to_number("1.02:03,4"), 3723.4)    # atletiek.nu
        self.assertEqual(base.to_number("1:02:03,4"), 3723.4)    # Seltec
        self.assertEqual(base.to_number("10,1h"), 10.1)
        self.assertIsNone(base.to_number("DNF"))

    def test_alle_importers_erven_en_zijn_geregistreerd(self):
        klassen = base.Importer.importers()
        for k in (atletieknu_prs.AtletiekNuPRImporter, atletieknu_wedstrijd.AtletiekNuWedstrijdImporter,
                  seltec.SeltecImporter):
            self.assertTrue(issubclass(k, base.Importer))
            self.assertIn(k, klassen)

    def test_detect_kiest_juiste_importer(self):
        gevallen = {
            "https://www.atletiek.nu/atleet/profiel/90001/": atletieknu_prs.AtletiekNuPRImporter,
            "https://www.atletiek.nu/wedstrijd/uitslagen/90002/": atletieknu_wedstrijd.AtletiekNuWedstrijdImporter,
            SELTEC_URL: seltec.SeltecImporter,
        }
        for url, klasse in gevallen.items():
            self.assertIsInstance(detect.kies_importer(url), klasse, url)
        with self.assertRaises(base.ImportFout):
            detect.kies_importer("https://example.com/iets")

    def test_parse_opgeslagen_pagina(self):
        imp = detect.kies_importer(SELTEC_URL)
        wedstrijd, rijen = imp.parse(str(FIXTURES / "seltec_uitslagenoverzicht.html"))
        self.assertEqual(wedstrijd.naam, "Testwedstrijd U18 & U20")
        self.assertTrue(rijen)

    def test_opnieuw_proberen_bij_te_veel_verzoeken(self):
        imp = self.importer(atletieknu_wedstrijd.AtletiekNuWedstrijdImporter, [
            NepAntwoord(200, "<title>Too many requests</title>"),     # status 200, toch geblokkeerd
            NepAntwoord(429, "", {"Retry-After": "0"}),
            NepAntwoord(200, "<div class='pageTitle'>Echt</div>"),
        ])
        self.assertIn("Echt", imp.haal_op("https://www.atletiek.nu/wedstrijd/uitslagen/1/"))
        self.assertEqual(len(imp._sessie.urls), 3)

    def test_geeft_op_na_max_pogingen(self):
        imp = self.importer(seltec.SeltecImporter, [NepAntwoord(503)] * seltec.SeltecImporter.max_pogingen)
        with self.assertRaises(base.ImportFout):
            imp.haal_op(SELTEC_URL)

    def test_browsercontrole_wordt_importfout(self):
        imp = self.importer(atletieknu_prs.AtletiekNuPRImporter,
                            [NepAntwoord(200, "<html>Checking your browser</html>")])
        with self.assertRaises(base.ImportFout):
            imp.haal_op("https://www.atletiek.nu/atleet/profiel/1/")

    def test_lege_map_wordt_importfout(self):
        import tempfile
        with tempfile.TemporaryDirectory() as leeg:
            with self.assertRaises(base.ImportFout):
                seltec.SeltecImporter().parse(leeg)

    # ---------------------------------------------------------------- browser imiteren (curl_cffi)

    def test_atletieknu_imiteert_chrome_seltec_niet(self):
        self.assertEqual(atletieknu_prs.AtletiekNuPRImporter.imiteer_browser, "chrome")
        self.assertEqual(atletieknu_wedstrijd.AtletiekNuWedstrijdImporter.imiteer_browser, "chrome")
        self.assertIsNone(seltec.SeltecImporter.imiteer_browser)

    def test_zonder_curl_cffi_duidelijke_fout(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"curl_cffi": None}):
            with self.assertRaises(base.ImportFout) as ctx:
                atletieknu_prs.AtletiekNuPRImporter().haal_op("https://www.atletiek.nu/atleet/profiel/1/")
        self.assertIn("pip install curl_cffi", str(ctx.exception))

    def test_ophalen_via_curl_cffi(self):
        """Echte curl_cffi-sessie tegen een lokale testserver (geen internet nodig)."""
        try:
            import curl_cffi  # noqa: F401
        except ImportError:
            self.skipTest("curl_cffi niet geïnstalleerd")
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                code = 404 if "fout" in self.path else 200
                body = "<div class='pageTitle'>Wedstrijd é</div>".encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            basis = f"http://127.0.0.1:{server.server_port}"
            imp = atletieknu_wedstrijd.AtletiekNuWedstrijdImporter()
            imp.pauze = 0
            self.assertIn("Wedstrijd é", imp.haal_op(basis + "/ok"))
            self.assertEqual(type(imp.sessie).__module__.split(".")[0], "curl_cffi")
            with self.assertRaises(base.ImportFout):
                imp.haal_op(basis + "/fout")
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
