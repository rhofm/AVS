"""Tests voor src/atleten/prs_importeren.py en de knop 'Ophalen van atletiek.nu' op de atletenpagina.

Gebruikt de nagebouwde, geanonimiseerde profielpagina tests/fixtures/atletieknu_profiel.html
(nep-id 999999); er wordt nooit naar de echte site gegaan. Vaste testsleutel, alleen nepgegevens.

"""

from dataclasses import replace
from pathlib import Path

from test_app import client
from test_landingspagina import opslag, voorbeeld

from atleten.prs_importeren import GeenNummer, PRImport, prs_importeren
from db.queries import Opslag, OpslagFout
from importers.base import ImportFout
from hulp import TESTSLEUTEL, tekst, verwacht as _verwacht

PROFIEL = (Path(__file__).parent / "fixtures" / "atletieknu_profiel.html").read_text(encoding="utf-8")
NUMMER = "999999"
WEINIG = (Path(__file__).parent / "fixtures" / "atletieknu_profiel_weinig.html").read_text(encoding="utf-8")
WEINIG_NUMMER = "999998"


def _met_nummer(db, mid, nummer=NUMMER):
    db.atleet_opslaan(replace(db.atleet(mid), atletieknu_id=nummer))


def test_importeren_en_opnieuw():
    with opslag() as db:
        mid = voorbeeld(db)
        _met_nummer(db, mid)
        gevraagd = []

        def haal(nummer):
            gevraagd.append(nummer)
            return PROFIEL

        voor = len(db.prs(mid))
        r = prs_importeren(db, mid, haal)
        assert gevraagd == [NUMMER]
        assert (r.nieuw, r.bekend, r.overgeslagen) == (2, 0, 1)             # DNF telt niet
        assert r.nieuwe_prs and len(db.prs(mid)) >= voor
        assert r.tekst.startswith("PR's opgehaald van atletiek.nu: 2 nieuwe prestaties")

        # Nog een keer: niets dubbel, geen nieuwe PR's.
        r = prs_importeren(db, mid, haal)
        assert (r.nieuw, r.bekend, r.nieuwe_prs) == (0, 2, [])
        assert r.tekst == "PR's opgehaald van atletiek.nu: geen nieuwe prestaties."


def test_profiel_met_te_weinig_uitslagen():
    """Zonder grafieken ('Te weinig uitslagen') komen de prestaties uit de PR-tabel."""
    with opslag() as db:
        mid = voorbeeld(db)
        _met_nummer(db, mid, WEINIG_NUMMER)
        r = prs_importeren(db, mid, lambda nummer: WEINIG)
        assert (r.nieuw, r.bekend, r.overgeslagen) == (5, 0, 0)
        namen = {p.onderdeel for p in db.prestaties(mid) if p.bron == "atletieknu"}
        assert {"60 meter", "80 meter horden 76,2cm", "Kogelstoten 3kg", "Hoogspringen"} <= namen
        assert not any("Handtijd" in n or "windmeting" in n for n in namen)

        r = prs_importeren(db, mid, lambda nummer: WEINIG)               # opnieuw: niets dubbel
        assert (r.nieuw, r.bekend) == (0, 5)


def test_meldingen():
    assert PRImport(1, 0, 0, ["Kogelstoten"]).tekst == \
        "PR's opgehaald van atletiek.nu: 1 nieuwe prestatie, 1 nieuw PR (Kogelstoten)."
    assert PRImport(3, 1, 0, []).tekst == "PR's opgehaald van atletiek.nu: 3 nieuwe prestaties, geen nieuwe PR's."
    assert "2 nieuwe PR's (100m, Ver)" in PRImport(2, 0, 0, ["100m", "Ver"]).tekst


def test_fouten():
    with opslag() as db:
        mid = voorbeeld(db)
        # Geen nummer: er wordt niets opgehaald.
        _verwacht(GeenNummer, lambda: prs_importeren(db, mid, lambda n: 1 / 0))
        _verwacht(OpslagFout, lambda: prs_importeren(db, "0" * 32, lambda n: PROFIEL))

        _met_nummer(db, mid, "123456")
        voor = db.prs(mid)
        # Pagina van een ander profiel, onleesbare pagina, geen verbinding: niets opgeslagen.
        e = _verwacht(ImportFout, lambda: prs_importeren(db, mid, lambda n: PROFIEL))
        assert "999999" in str(e)
        _met_nummer(db, mid)
        _verwacht(ImportFout, lambda: prs_importeren(db, mid, lambda n: "<html>geen profiel</html>"))

        def offline(_):
            raise ConnectionError("geen netwerk")
        e = _verwacht(ImportFout, lambda: prs_importeren(db, mid, offline))
        assert "niet bereikbaar" in str(e)
        assert db.prs(mid) == voor


def test_knop_op_atletenpagina():
    with client() as (c, mid, tmp):
        c.application.config["AVS_HAAL_PROFIEL"] = lambda nummer: PROFIEL
        # Zonder nummer: link naar 'Gegevens aanpassen' in plaats van de knop.
        r = tekst(c.get(f"/atleet/{mid}"))
        assert "/prs/importeren" not in r and "+ atletiek.nu-nummer" in r

        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            _met_nummer(db, mid)
        r = tekst(c.get(f"/atleet/{mid}"))
        assert f'action="/atleet/{mid}/prs/importeren"' in r and "Ophalen van atletiek.nu" in r

        r = c.post(f"/atleet/{mid}/prs/importeren")
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/atleet/{mid}#kop-pr")
        r = tekst(c.get(f"/atleet/{mid}"))
        assert "PR&#39;s opgehaald van atletiek.nu: 2 nieuwe prestaties" in r
        assert r.count('class="melding"') == 1                   # bij de PR's, niet ook bovenaan
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            assert any(p.bron == "atletieknu" for p in db.prestaties(mid))

        # Fout (geen verbinding): melding bij de PR's, pagina blijft gewoon werken.
        def offline(_):
            raise ConnectionError
        c.application.config["AVS_HAAL_PROFIEL"] = offline
        c.post(f"/atleet/{mid}/prs/importeren")
        r = tekst(c.get(f"/atleet/{mid}"))
        assert "melding--fout" in r and "niet opgehaald" in r

        assert c.post("/atleet/" + "0" * 32 + "/prs/importeren").status_code == 404
        assert c.get(f"/atleet/{mid}/prs/importeren").status_code in (404, 405)
