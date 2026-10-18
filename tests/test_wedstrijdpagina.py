"""Tests voor de pagina van één wedstrijd (wedstrijden.detail, /wedstrijd/<id>):
tijdschema met deelnemers, onderdelen zonder atleten achter een vinkje,
inschrijven (ook vanuit een regel van het tijdschema), afmelden en de import.

Alleen nepgegevens en een vaste testsleutel; niets van internet. Werkt met
pytest en los: `python tests/test_wedstrijdpagina.py`.
"""

import contextlib
import io
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_landingspagina import TESTSLEUTEL  # noqa: E402

from atleten import beheer  # noqa: E402
from db.init_db import init_db  # noqa: E402
from db.queries import Opslag, OpslagFout  # noqa: E402
from models import Onderdeel, ProgrammaOnderdeel  # noqa: E402
from wedstrijden import detail, planning  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "atletieknu_tijdschema" / "meerkamp.html"
DAG = date.today() + timedelta(days=8)


def _verwacht(fout, fn) -> None:
    try:
        fn()
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


@contextlib.contextmanager
def opslag():
    """(Opslag, map, ids) met een wedstrijd, een tijdschema en drie nep-atleten."""
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            honderd = db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
            ver = db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
            kogel = db.onderdeel_opslaan(Onderdeel("Kogelstoten", "afstand", False, "werpen"))
            jaar = DAG.year - 15                                         # U16 op de wedstrijddag
            anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum=f"{jaar}-03-14").master_id
            bram = beheer.nieuwe_atleet(db, "Bram", "Test", geslacht="M", geboortedatum=f"{jaar}-05-01").master_id
            cees = beheer.nieuwe_atleet(db, "Cees", "Nep", geslacht="M", geboortedatum=f"{DAG.year - 11}").master_id  # U12
            w = planning.plan_wedstrijd(db, "Clubkampioenschappen", DAG, "Sportpark",
                                        link="https://www.atletiek.nu/wedstrijd/main/45678/")
            regels = [
                ProgrammaOnderdeel(w.id, DAG, "10:00", honderd.id, categorie="Meisjes U16", ronde="serie", duur=30),
                ProgrammaOnderdeel(w.id, DAG, "10:15", ver.id, categorie="MU16", groep=1, duur=45),
                ProgrammaOnderdeel(w.id, DAG, "10:30", honderd.id, categorie="Jongens U16", duur=30),
                ProgrammaOnderdeel(w.id, DAG, "11:00", kogel.id, categorie="Jongens U12"),
                ProgrammaOnderdeel(w.id, DAG, "11:30", onderdeel_tekst="Hoogspringen", categorie="U14"),
            ]
            db.programma_vervangen(w.id, regels)
            planning.inschrijven(db, w.id, anna, ["100m", "Verspringen"])     # 100m 10:00 en ver 10:15: botsing
            planning.inschrijven(db, w.id, bram, ["100m", "Verspringen"])     # ver is alleen voor meisjes
            ids = dict(w=w.id, anna=anna, bram=bram, cees=cees, honderd=honderd.id, ver=ver.id, kogel=kogel.id,
                       regels=[r.id for r in regels])
            yield db, Path(tmp), ids


def test_detail():
    with opslag() as (db, _, ids):
        d = detail.wedstrijd_detail(db, ids["w"], peildatum=DAG - timedelta(days=8))
        assert d.dagen_tot == 8 and not d.geweest and d.heeft_tijdschema and not d.meerdaags
        rijen = d.dagen[0].rijen
        assert [r.tijd for r in rijen] == ["10:00–10:30", "10:15–11:00", "10:30–11:00", "11:00", "11:30"]
        assert [[a.voornaam for a in r.atleten] for r in rijen] == [["Anna"], ["Anna"], ["Bram"], [], []]
        assert rijen[0].details == "serie" and rijen[1].details == "groep 1"
        assert d.aantal_regels == 5 and d.aantal_met_atleten == 3 and d.aantal_zonder_atleten == 2
        # Deelnemers: Bram heeft Verspringen, maar geen regel voor jongens.
        dn = {p.atleet.voornaam: p for p in d.deelnemers}
        assert [o.naam for o in dn["Anna"].onderdelen] == ["100m", "Verspringen"] and not dn["Anna"].niet_in_tijdschema
        assert dn["Bram"].niet_in_tijdschema == ["Verspringen"] and dn["Anna"].categorie == "U16V"
        assert [p.atleet.voornaam for p in d.zonder_plek] == ["Bram"]
        # Botsing: Anna heeft 100m (10:00–10:30) en verspringen (10:15) tegelijk.
        assert len(d.botsingen) == 1 and "Anna" in d.botsingen[0].tekst
        assert detail.wedstrijd_detail(db, 9999) is None


def test_inschrijfformulier_en_inschrijven():
    with opslag() as (db, _, ids):
        kogel_regel = ids["regels"][3]                                 # Kogelstoten Jongens U12
        f = detail.inschrijfformulier(db, ids["w"], kogel_regel)
        assert f.gekozen_onderdelen == {ids["kogel"]}
        assert {o.naam for o in f.onderdelen} == {"100m", "Verspringen", "Kogelstoten"} and not f.overige_onderdelen
        assert [k.atleet.voornaam for k in f.passend] == ["Cees"]      # alleen jongens U12
        assert {k.atleet.voornaam for k in f.niet_passend} == {"Anna", "Bram"}
        al = {k.atleet.voornaam: k for k in f.kandidaten}
        assert al["Anna"].ingeschreven == ["100m", "Verspringen"] and al["Anna"].al_mee and not al["Cees"].al_mee
        # Zonder regel: iedereen past.
        assert len(detail.inschrijfformulier(db, ids["w"]).passend) == 3
        assert detail.inschrijfformulier(db, ids["w"], 9999) is None

        assert detail.inschrijven_uit_formulier(db, ids["w"], [ids["cees"]], [str(ids["kogel"])]) == 1
        d = detail.wedstrijd_detail(db, ids["w"])
        assert [a.voornaam for a in d.dagen[0].rijen[3].atleten] == ["Cees"]
        # Zonder onderdelen: gaat mee, onderdelen volgen nog.
        nieuw = beheer.nieuwe_atleet(db, "Dirk", "Nep").master_id
        detail.inschrijven_uit_formulier(db, ids["w"], [nieuw], [])
        assert next(p for p in detail.wedstrijd_detail(db, ids["w"]).deelnemers if p.atleet.voornaam == "Dirk").volgt_nog
        # Fouten: niemand gekozen, onbekend onderdeel. Er wordt niets half opgeslagen.
        _verwacht(OpslagFout, lambda: detail.inschrijven_uit_formulier(db, ids["w"], [], [ids["kogel"]]))
        _verwacht(OpslagFout, lambda: detail.inschrijven_uit_formulier(db, ids["w"], [ids["bram"]], ["999"]))


def test_afmelden():
    with opslag() as (db, _, ids):
        assert "afgemeld voor Verspringen" in detail.afmelden(db, ids["w"], ids["bram"], ids["ver"])
        detail.afmelden(db, ids["w"], ids["bram"], ids["honderd"])          # laatste onderdeel
        bram = next(p for p in detail.wedstrijd_detail(db, ids["w"]).deelnemers if p.atleet.voornaam == "Bram")
        assert bram.volgt_nog                                              # blijft mee
        detail.afmelden(db, ids["w"], ids["bram"])                         # hele wedstrijd
        assert "Bram" not in {p.atleet.voornaam for p in detail.wedstrijd_detail(db, ids["w"]).deelnemers}


def _client(tmp):
    from ui.app import maak_app
    app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
    app.config["TESTING"] = True
    return app.test_client()


def test_pagina():
    with opslag() as (db, tmp, ids):
        c = _client(tmp)
        r = c.get(f"/wedstrijd/{ids['w']}")
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "Clubkampioenschappen" in html and "Sportpark" in html
        assert 'href="https://www.atletiek.nu/wedstrijd/uitslagen/45678/"' in html
        # Onderdelen zonder atleten: in de pagina, maar achter het vinkje (standaard uit).
        assert 'id="toon-alle" name="alle" value="1">' in html
        assert "Toon alle onderdelen" in html and "(2 zonder atleten)" in html
        assert len(re.findall(r'class="zonder-atleten"', html)) == 2 and len(re.findall(r'class="met-atleten"', html)) == 3
        assert "Hoogspringen" in html and "niet gekoppeld" in html            # wel in de pagina, als tekst
        assert 'value="1" checked>' in c.get(f"/wedstrijd/{ids['w']}?alle=1").get_data(as_text=True)
        # Atleten bij hun regel, met link naar de atleet; botsing en 'niet in tijdschema'.
        assert f'href="/atleet/{ids["anna"]}">Anna Voorbeeld</a>' in html
        assert "botsing" in html and "niet in tijdschema" in html
        # Knoppen: inschrijven, en per regel '+'.
        assert f'href="/wedstrijd/{ids["w"]}/inschrijven"' in html
        assert f'href="/wedstrijd/{ids["w"]}/inschrijven?regel={ids["regels"][3]}"' in html
        css = c.get("/static/avs.css").get_data(as_text=True)
        assert ".tijdschema__vink:not(:checked) ~ .tijdschema__dag tr.zonder-atleten" in css
        # Overzicht linkt naar deze pagina.
        assert f'href="/wedstrijd/{ids["w"]}"' in c.get("/wedstrijden").get_data(as_text=True)
        assert c.get("/wedstrijd/9999").status_code == 404


def test_pagina_zonder_tijdschema():
    with opslag() as (db, tmp, ids):
        w = planning.plan_wedstrijd(db, "Losse wedstrijd", DAG)
        html = _client(tmp).get(f"/wedstrijd/{w.id}").get_data(as_text=True)
        assert "Nog geen tijdschema" in html and 'name="link"' in html and 'id="toon-alle"' not in html
        assert "Nog niemand ingeschreven" in html


def test_inschrijven_route():
    with opslag() as (db, tmp, ids):
        c = _client(tmp)
        regel = ids["regels"][3]
        html = c.get(f"/wedstrijd/{ids['w']}/inschrijven?regel={regel}").get_data(as_text=True)
        assert f'name="onderdeel" value="{ids["kogel"]}" checked' in html
        assert "Ook atleten uit andere categorieën" in html and 'class="andere-categorie"' in html
        r = c.post(f"/wedstrijd/{ids['w']}/inschrijven",
                   data={"regel": regel, "atleet": [ids["cees"]], "onderdeel": [ids["kogel"]]})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/wedstrijd/{ids['w']}#regel-{regel}")
        html = c.get(f"/wedstrijd/{ids['w']}").get_data(as_text=True)
        assert "1 atleet ingeschreven voor Kogelstoten." in html and "Cees Nep" in html
        # Niemand aangevinkt: foutmelding, onderdeel blijft aan.
        r = c.post(f"/wedstrijd/{ids['w']}/inschrijven", data={"onderdeel": [ids["ver"]]})
        html = r.get_data(as_text=True)
        assert r.status_code == 400 and "Vink minstens één atleet aan" in html
        assert f'name="onderdeel" value="{ids["ver"]}" checked' in html
        assert c.get(f"/wedstrijd/{ids['w']}/inschrijven?regel=9999").status_code == 404
        assert c.get("/wedstrijd/9999/inschrijven").status_code == 404


def test_afmelden_route():
    with opslag() as (db, tmp, ids):
        c = _client(tmp)
        r = c.post(f"/wedstrijd/{ids['w']}/afmelden", data={"atleet": ids["anna"], "onderdeel": ids["ver"]})
        assert r.status_code == 302
        html = c.get(f"/wedstrijd/{ids['w']}").get_data(as_text=True)
        assert "Anna Voorbeeld is afgemeld voor Verspringen." in html and "botsing" not in html
        c.post(f"/wedstrijd/{ids['w']}/afmelden", data={"atleet": ids["anna"]})
        html = c.get(f"/wedstrijd/{ids['w']}").get_data(as_text=True)
        assert "afgemeld voor deze wedstrijd" in html and f'href="/atleet/{ids["anna"]}"' not in html
        assert c.post(f"/wedstrijd/{ids['w']}/afmelden", data={"atleet": "0" * 32}).status_code == 400


def test_import_route():
    with opslag() as (db, tmp, ids):
        c = _client(tmp)
        # Een opgeslagen pagina werkt als 'link' (niets van internet).
        r = c.post(f"/wedstrijd/{ids['w']}/tijdschema", data={"link": str(FIXTURE)})
        assert r.status_code == 302
        html = c.get(f"/wedstrijd/{ids['w']}").get_data(as_text=True)
        assert "Tijdschema geïmporteerd" in html
        r = c.post(f"/wedstrijd/{ids['w']}/tijdschema", data={"link": "https://example.com/iets"})
        assert r.status_code == 400 and "Tijdschema niet geïmporteerd" in r.get_data(as_text=True)


def test_links_vanaf_atleet_en_groep():
    """Op de pagina's van een atleet en een groep linkt een wedstrijd naar de wedstrijdpagina in AVS,
    niet naar atletiek.nu (die link staat op de wedstrijdpagina zelf)."""
    from models import Groep
    with opslag() as (db, tmp, ids):
        g = db.groep_opslaan(Groep("U16 sprint", None, [ids["anna"], ids["bram"]]))
        c = _client(tmp)
        intern = f'href="/wedstrijd/{ids["w"]}"'
        for pad in (f"/atleet/{ids['anna']}", f"/atleet/{ids['anna']}/wedstrijden",
                    f"/atleet/{ids['anna']}/wedstrijden?weergave=kalender",
                    f"/groep/{g.id}", f"/groep/{g.id}/wedstrijden"):
            html = c.get(pad).get_data(as_text=True)
            assert intern in html, pad
            assert "atletiek.nu/wedstrijd" not in html, pad
        assert c.get(f"/wedstrijd/{ids['w']}").status_code == 200
        # Op de wedstrijdpagina zelf staat de link naar de site nog wel.
        assert "atletiek.nu/wedstrijd/uitslagen/45678" in c.get(f"/wedstrijd/{ids['w']}").get_data(as_text=True)


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("ok ", naam)
