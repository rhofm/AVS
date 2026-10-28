"""Tests voor de testsjabloon-editor (testen/editor.py) en de pagina's/routes voor testsjablonen en testresultaten.

Alleen nepgegevens en een vaste testsleutel (de nepgroep uit test_groep_landingspagina).

"""

import re

import pytest
from test_groep_landingspagina import opslag, voorbeeldgroep

from groepen import overzichten
from testen import editor
from testen import sjabloon as sj
from testen.sjabloon import SjabloonFout
from hulp import app_client


def form(naam="Sprongkracht", rijen=(), totaal=None, totaal_getoond=None, **extra):
    """Een formulier zoals de browser het stuurt. rij = (naam, soort, formule, [parameters])."""
    d = {"naam": naam}
    if totaal is not None:
        d["totaal"] = "1" if totaal else ""
    if totaal_getoond:
        d["totaal_getoond"] = "1"
    for i, (n, soort, formule, pars) in enumerate(rijen):
        d[f"onderdeel-naam-{i}"], d[f"onderdeel-soort-{i}"] = n, soort
        d[f"onderdeel-formule-{i}"], d[f"onderdeel-aantal-{i}"] = formule, str(len(pars))
        for j, p in enumerate(pars):
            d[f"onderdeel-par-{i}-{j}"] = p
    d.update(extra)
    return d


# ---------------- editor ----------------
def test_editor_rijen_en_parameters():
    c = editor.Concept()
    assert len(c.onderdelen) >= 1 and not c.totaal_mogelijk
    c = editor.pas_toe(c, "rij-toevoegen")
    assert len(c.onderdelen) == 2
    c = editor.pas_toe(c, "weg-0")
    assert len(c.onderdelen) == 1
    c = editor.pas_toe(c, "weg-0")                                   # de laatste rij blijft staan
    assert len(c.onderdelen) == 1
    c = editor.pas_toe(c, "weg-9")                                   # bestaat niet: niets
    assert len(c.onderdelen) == 1
    for _ in range(40):
        c = editor.pas_toe(c, "rij-toevoegen")
    assert len(c.onderdelen) == sj.MAX_ONDERDELEN


def test_editor_totaalvinkje_standaard_aan():
    f = form(rijen=[("A", "tijd", "C1 / T", ["10"]), ("B", "lengte", "", [])])
    c = editor.normaliseer(editor.concept_uit_formulier(f))
    assert not c.totaal_mogelijk                                      # maar één formule
    f = form(rijen=[("A", "tijd", "C1 / T", ["10"]), ("B", "lengte", "C1 * L", ["2"])])
    c = editor.normaliseer(editor.concept_uit_formulier(f))
    assert c.totaal_mogelijk and c.totaal_optellen and c.totaal_getoond        # net verschenen: aan
    f["totaal_getoond"] = "1"                                         # er was al een vinkje, nu uitgezet
    c = editor.normaliseer(editor.concept_uit_formulier(f))
    assert c.totaal_mogelijk and not c.totaal_optellen


def test_editor_naar_sjabloon():
    f = form("Test", [("A", "tijd", "C1 / T", ["10,5"]), ("B", "lengte", "", ["9"])], totaal=True, totaal_getoond=True)
    s = editor.naar_sjabloon(editor.normaliseer(editor.concept_uit_formulier(f)))
    assert s.onderdelen[0].parameters == [10.5] and s.onderdelen[1].parameters == []    # zonder formule: geen parameters
    assert not s.totaal_mogelijk
    for fout, pars, formule in (("vul een getal in voor C1", [""], "C1 / T"), ("vul een getal in voor C1", ["x"], "C1 / T")):
        f = form("Test", [("A", "tijd", formule, pars)])
        with pytest.raises(SjabloonFout, match=fout):
            editor.naar_sjabloon(editor.concept_uit_formulier(f))
    f = form("", [("", "tijd", "L * 2", [])])                       # naam leeg, formule met verkeerde letter
    with pytest.raises(SjabloonFout) as e:
        editor.naar_sjabloon(editor.concept_uit_formulier(f))
    assert len(e.value.problemen) >= 2                                # alle problemen in één keer


# ---------------- routes ----------------
def links_werken(c, html):
    for link in sorted(set(re.findall(r'href="(/(?:groep|atleet|testen)/[^"]*)"', html))):
        assert c.get(link).status_code == 200, link


def test_sjablonenlijst_en_download():
    with opslag() as (db, tmp):
        c = app_client(tmp)
        r = c.get("/testen/sjablonen")
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "30 m vliegend" in html and "Verspringen vanuit stand" in html
        links_werken(c, html)
        r = c.get("/testen/sjablonen/30m_vliegend/yaml")
        assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
        assert sj.Sjabloon.uit_yaml(r.get_data(as_text=True)).naam == "30 m vliegend"
        assert c.get("/testen/sjablonen/bestaat-niet").status_code == 404
        assert c.get("/testen/sjablonen/bestaat-niet/yaml").status_code == 404


def test_nieuw_sjabloon_via_formulier_en_naar_atleet():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        c = app_client(tmp)
        html = c.get(f"/testen/sjablonen/nieuw?atleet={anna}").get_data(as_text=True)
        assert 'name="onderdeel-naam-0"' in html and f'value="{anna}"' in html
        # Rij erbij (knop), blijft op het formulier.
        d = form("Sprongkracht", [("Hoog", "lengte", "C1 * L", ["100"])], actie="rij-toevoegen", atleet=anna)
        r = c.post("/testen/sjablonen/nieuw", data=d)
        assert r.status_code == 200 and 'name="onderdeel-naam-1"' in r.get_data(as_text=True)
        # Fout: niets opgeslagen, alle meldingen zichtbaar.
        d = form("", [("", "tijd", "L", [])], actie="opslaan", atleet=anna)
        r = c.post("/testen/sjablonen/nieuw", data=d)
        assert r.status_code == 400 and not (tmp / "testsjablonen").exists()
        # Goed: bestand komt in de datamap en je gaat door naar het invoeren van een resultaat voor de atleet.
        d = form("Sprongkracht", [("Hoog", "lengte", "C1 * L", ["100"]), ("Sprint", "tijd", "C1 / T", ["150"])],
                 actie="opslaan", atleet=anna)
        r = c.post("/testen/sjablonen/nieuw", data=d)
        assert r.status_code == 302 and r.headers["Location"] == f"/atleet/{anna}/testen/nieuw?sjabloon=sprongkracht"
        assert (tmp / "testsjablonen" / "sprongkracht.yaml").exists()
        s = sj.laad_bibliotheek(tmp).vind("sprongkracht").sjabloon
        assert s.totaal_optellen and s.totaal_mogelijk                  # het vinkje stond standaard aan
        # Dezelfde naam nog eens: geweigerd.
        r = c.post("/testen/sjablonen/nieuw", data=d)
        assert r.status_code == 400 and "al een test" in r.get_data(as_text=True)
        # Zonder atleet: terug naar de lijst.
        d2 = form("Los", [("x", "gewicht", "", [])], actie="opslaan")
        r = c.post("/testen/sjablonen/nieuw", data=d2)
        assert r.status_code == 302 and r.headers["Location"] == "/testen/sjablonen"
        assert "Los" in c.get("/testen/sjablonen").get_data(as_text=True)


def test_resultaat_invoeren_tonen_en_verwijderen():
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        anna = ids["anna"]
        c = app_client(tmp)
        d = form("Sprongkracht", [("Hoog", "lengte", "C1 * L", ["100"]), ("Sprint", "tijd", "C1 / T", ["150"])],
                 actie="opslaan")
        c.post("/testen/sjablonen/nieuw", data=d)
        pad = f"/atleet/{anna}/testen/nieuw"
        html = c.get(f"{pad}?sjabloon=sprongkracht").get_data(as_text=True)
        assert 'name="waarde-0"' in html and 'name="waarde-1"' in html and 'name="datum"' in html
        assert c.get(f"{pad}?sjabloon=bestaat-niet").status_code == 404
        assert c.get(f"{pad}").status_code == 404                                  # zonder sjabloon
        assert c.get("/atleet/" + "0" * 32 + "/testen").status_code == 404
        # Foute invoer: formulier blijft staan met de ingevulde waarden.
        r = c.post(pad, data={"sjabloon": "sprongkracht", "datum": "2026-10-20", "waarde-0": "0,5", "waarde-1": "abc"})
        assert r.status_code == 400 and "geen geldig getal" in r.get_data(as_text=True) and 'value="0,5"' in r.get_data(as_text=True)
        r = c.post(pad, data={"sjabloon": "sprongkracht", "datum": "kapot", "waarde-0": "1", "waarde-1": "1"})
        assert r.status_code == 400 and "geldige datum" in r.get_data(as_text=True)
        r = c.post(pad, data={"sjabloon": "bestaat-niet", "datum": "2026-10-20"})
        assert r.status_code == 404
        assert db.testresultaten(anna) == []
        # Goed.
        r = c.post(pad, data={"sjabloon": "sprongkracht", "datum": "2026-10-20", "waarde-0": "0,5", "waarde-1": "4",
                              "notities": "goede dag"}, follow_redirects=True)
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "opgeslagen" in html and "87,5" in html and "Hoog" in html
        links_werken(c, html)
        assert "Sprongkracht" in c.get(f"/atleet/{anna}").get_data(as_text=True)
        # Het sjabloon met resultaten laat zich niet meer verwijderen en staat vast voor aantal/soort.
        pag = c.get("/testen/sjablonen/sprongkracht").get_data(as_text=True)
        assert 'value="verwijderen"' not in pag
        # De groepstabel krijgt een kolom per onderdeel en een totaal.
        t = overzichten.testresultaten(db, db.groep(ids["groep"]), bibliotheek=sj.laad_bibliotheek(tmp))
        namen = [k.naam for k in t.kolommen]
        assert any("Hoog" in n for n in namen) and any("totaal" in n.lower() for n in namen)
        assert "Hoog" in c.get(f"/groep/{ids['groep']}/testen").get_data(as_text=True)
        # Verwijderen van het resultaat.
        rid = db.testresultaten(anna)[0].id
        assert c.post(f"/atleet/{anna}/testen/{rid + 99}/verwijderen").status_code == 404
        assert c.post(f"/atleet/{ids['bram']}/testen/{rid}/verwijderen").status_code == 404      # niet van Bram
        assert c.post(f"/atleet/{anna}/testen/{rid}/verwijderen").status_code == 302
        assert db.testresultaten(anna) == []
        assert c.get(f"/atleet/{anna}/testen").status_code == 200


def test_sjabloon_bewerken_en_verwijderen():
    with opslag() as (db, tmp):
        c = app_client(tmp)
        # Een meegeleverd sjabloon bewerken geeft een eigen versie onder dezelfde bestandsnaam.
        d = form("30 m vliegend", [("Tijd", "tijd", "", [])], actie="opslaan")
        r = c.post("/testen/sjablonen/30m_vliegend", data=d)
        assert r.status_code == 302 and (tmp / "testsjablonen" / "30m_vliegend.yaml").exists()
        # Verwijderen vraagt om bevestiging en haalt alleen de eigen versie weg (het meegeleverde komt terug).
        r = c.post("/testen/sjablonen/30m_vliegend", data=form("30 m vliegend", [("Tijd", "tijd", "", [])], actie="verwijderen"))
        assert r.status_code == 400 and (tmp / "testsjablonen" / "30m_vliegend.yaml").exists()
        r = c.post("/testen/sjablonen/30m_vliegend",
                   data=form("30 m vliegend", [("Tijd", "tijd", "", [])], actie="verwijderen", zeker="1"))
        assert r.status_code == 302 and not (tmp / "testsjablonen" / "30m_vliegend.yaml").exists()
        assert c.get("/testen/sjablonen/30m_vliegend").status_code == 200
        # Een meegeleverd sjabloon zonder eigen versie is niet te verwijderen.
        r = c.post("/testen/sjablonen/30m_vliegend",
                   data=form("30 m vliegend", [("Tijd", "tijd", "", [])], actie="verwijderen", zeker="1"))
        assert r.status_code == 404
        assert c.post("/testen/sjablonen/bestaat-niet", data=form("x", [("a", "tijd", "", [])])).status_code == 404


def test_sjabloon_met_resultaten_vergrendeld():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        c = app_client(tmp)
        c.post("/testen/sjablonen/nieuw", data=form("Twee", [("a", "tijd", "C1 / T", ["10"]), ("b", "lengte", "", [])], actie="opslaan"))
        c.post(f"/atleet/{anna}/testen/nieuw", data={"sjabloon": "twee", "datum": "2026-10-20", "waarde-0": "5", "waarde-1": "2"})
        r = c.post("/testen/sjablonen/twee", data=form("Twee", [("a", "tijd", "C1 / T", ["10"])], actie="opslaan"))   # onderdeel eraf
        assert r.status_code == 400 and "aantal onderdelen" in r.get_data(as_text=True)
        r = c.post("/testen/sjablonen/twee", data=form("Twee", [("a2", "tijd", "C1 / T", ["20"]), ("b", "lengte", "", [])], actie="opslaan"))
        assert r.status_code == 302                                     # namen en formules wel
