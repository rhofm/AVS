"""Tests voor het importeren van de uitslag van een gehouden wedstrijd:
wedstrijden.uitslag_import en de knop 'Uitslagen importeren' op de wedstrijdpagina.

Tegen opgeslagen, geanonimiseerde pagina's (fixtures/atletieknu_wedstrijd/teams en
fixtures/seltec_uitslagenoverzicht.html); er wordt niets van internet gehaald.


In de atletiek.nu-fixture (Test Teamwedstrijd 2026, 19-09-2026) staan van 'Atletiek Teststad'
o.a. Anna Voorbeeld (100m 11,54 +0,5; ver 6,64) en Pim Voorbeeld (100m 13,61 +0,4; ver 4,66),
plus atleten van andere clubs en estafetteteams.
"""

import contextlib
from datetime import date, timedelta
from pathlib import Path

from atleten import beheer
from db.queries import OpslagFout
from importers.atletieknu_wedstrijd import AtletiekNuWedstrijdImporter
from importers.seltec import SeltecImporter
from wedstrijden import detail, planning, uitslag_import
from hulp import app_client, lege_opslag, verwacht as _verwacht

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEAMS = FIXTURES / "atletieknu_wedstrijd" / "teams"
SELTEC = FIXTURES / "seltec_uitslagenoverzicht.html"
DAG = date(2026, 9, 19)


def _stil():
    return AtletiekNuWedstrijdImporter(log=lambda *a: None)


@contextlib.contextmanager
def opslag(link: str | None = "https://www.atletiek.nu/wedstrijd/main/90002/"):
    """(db, map, ids): een gehouden wedstrijd en vier nep-atleten."""
    with lege_opslag() as (db, tmp):
        anna = beheer.nieuwe_atleet(db, "Anna", "Voorbeeld", geslacht="V", geboortedatum="2004",
                                    club="Atletiek Teststad").master_id      # zeker: naam + club
        pim = beheer.nieuwe_atleet(db, "Pim", "Voorbeeld", geslacht="M").master_id   # ingeschreven
        niels = beheer.nieuwe_atleet(db, "Niels", "van Proefstra", geslacht="M").master_id  # alleen naam
        kiki = beheer.nieuwe_atleet(db, "Kiki", "van Proefstra", geslacht="V",
                                    club="Andere Club").master_id               # club botst: iemand anders
        w = planning.plan_wedstrijd(db, "Test Teamwedstrijd 2026", DAG, "Teststad", link=link)
        planning.inschrijven(db, w.id, pim, [])
        yield db, Path(tmp), dict(w=w.id, anna=anna, pim=pim, niels=niels, kiki=kiki)


def _van(db, mid):
    return sorted((p.onderdeel, p.waarde, p.wind) for p in db.prestaties(mid))


def test_importeren_en_koppelen():
    with opslag() as (db, _, ids):
        v = uitslag_import.uitslagen_importeren(db, ids["w"], str(TEAMS), importer=_stil())
        assert v.gelezen == 27 and v.atleten == ["Anna Voorbeeld", "Pim Voorbeeld"]
        assert _van(db, ids["anna"]) == [("100 meter", 11.54, 0.5), ("Verspringen", 6.64, 1.0)]   # met wind
        assert [x[:2] for x in _van(db, ids["pim"])] == [("100 meter", 13.61), ("Verspringen", 4.66)]
        assert v.nieuw == 4 and v.al_bekend == 0
        # Alleen de naam: te controleren, nog niet opgeslagen. Club botst: overgeslagen.
        assert [(t.naam, [a.voornaam for a in t.kandidaten]) for t in v.te_controleren] == \
            [("Niels van Proefstra", ["Niels"])]
        assert db.prestaties(ids["niels"]) == [] and db.prestaties(ids["kiki"]) == []
        # Alles hoort bij deze wedstrijd; geen namen in prestaties.db (alleen via de koppeling).
        assert all(p.wedstrijd_id == ids["w"] for p in db.prestaties(ids["anna"]))
        assert {o.naam for o in db.onderdelen()} >= {"100 meter", "Verspringen"}
        assert "100 meter" in v.nieuwe_onderdelen
        # Opnieuw importeren: niets dubbel.
        v2 = uitslag_import.uitslagen_importeren(db, ids["w"], str(TEAMS), importer=_stil())
        assert v2.nieuw == 0 and v2.al_bekend == 4 and not v2.nieuwe_onderdelen
        assert "4 stonden er al" in v2.tekst


def test_bevestigen():
    with opslag() as (db, _, ids):
        v = uitslag_import.uitslagen_importeren(db, ids["w"], str(TEAMS), importer=_stil())
        t = v.te_controleren[0]
        # Via het formulier heen en terug (zoals de pagina het doet).
        from werkzeug.datastructures import MultiDict
        form = MultiDict([("sleutel", t.sleutel), (f"naam-{t.sleutel}", t.naam), (f"club-{t.sleutel}", t.club),
                          (f"prestaties-{t.sleutel}", uitslag_import.naar_formulier(t)),
                          (f"kandidaat-{t.sleutel}", ids["niels"])])
        terug = uitslag_import.uit_formulier(db, ids["w"], form)
        assert len(terug) == 1 and terug[0].prestaties[0].waarde == 10.24
        nieuw, bekend, namen = uitslag_import.uitslagen_bevestigen(db, ids["w"], {t.sleutel: ids["niels"]}, terug)
        assert (nieuw, bekend, namen) == (1, 0, ["Niels van Proefstra"])
        assert [x[:2] for x in _van(db, ids["niels"])] == [("Hink-stap-springen", 10.24)]
        # Alleen een voorgestelde kandidaat mag; 'niet van ons' slaat niets op.
        _verwacht(OpslagFout, lambda: uitslag_import.uitslagen_bevestigen(db, ids["w"], {t.sleutel: ids["anna"]}, terug))
        assert uitslag_import.uitslagen_bevestigen(db, ids["w"], {t.sleutel: ""}, terug)[0] == 0
        # Geknoeid formulier: nette fout.
        form[f"prestaties-{t.sleutel}"] = "geen json"
        _verwacht(OpslagFout, lambda: uitslag_import.uit_formulier(db, ids["w"], form))


def test_seltec_met_geboortejaar():
    with opslag(link="https://uitslagen.atletiek.nl/Competitions/Details/19133") as (db, _, ids):
        femke = beheer.nieuwe_atleet(db, "Femke", "Dummelink", geboortedatum="2007").master_id   # naam + jaar
        w = planning.plan_wedstrijd(db, "Testwedstrijd U18 & U20", date(2026, 9, 18),
                                    link="https://uitslagen.atletiek.nl/Competitions/Details/19133")
        v = uitslag_import.uitslagen_importeren(db, w.id, str(SELTEC), importer=SeltecImporter(log=lambda *a: None))
        assert "Femke Dummelink" in v.atleten
        assert ("100 m", 11.35) in [x[:2] for x in _van(db, femke)]
        assert all(p.datum >= date(2026, 9, 18) for p in db.prestaties(femke))


def test_fouten():
    with opslag(link=None) as (db, _, ids):
        _verwacht(OpslagFout, lambda: uitslag_import.uitslagen_importeren(db, ids["w"]))          # geen link
        _verwacht(OpslagFout, lambda: uitslag_import.uitslagen_importeren(db, 999))
        _verwacht(OpslagFout, lambda: uitslag_import.uitslagen_importeren(db, ids["w"], "https://example.com/x"))


def test_detail_toont_uitslagen():
    with opslag() as (db, _, ids):
        uitslag_import.uitslagen_importeren(db, ids["w"], str(TEAMS), importer=_stil())
        d = detail.wedstrijd_detail(db, ids["w"], peildatum=DAG + timedelta(days=1))
        assert d.uitslag_mogelijk and d.aantal_met_uitslag == 2
        assert [(r.atleet.voornaam, r.onderdeel, r.prestatie) for r in d.uitslagen] == [
            ("Anna", "100 meter", "11,54"), ("Anna", "Verspringen", "6,64 m"),
            ("Pim", "100 meter", "13,61"), ("Pim", "Verspringen", "4,66 m")]
        assert all(r.pr for r in d.uitslagen)                      # enige prestaties = PR
        assert d.uitslagen[0].wind_tekst == "+0,5"
        assert not detail.wedstrijd_detail(db, ids["w"], peildatum=DAG - timedelta(days=1)).uitslag_mogelijk


def test_pagina_en_knop():
    # De wedstrijd 'linkt' naar de opgeslagen map, zodat de knop zonder internet werkt.
    with opslag(link=str(TEAMS)) as (db, tmp, ids):
        c = app_client(tmp)
        html = c.get(f"/wedstrijd/{ids['w']}").get_data(as_text=True)          # 19-09-2026 is geweest
        assert ">Uitslagen importeren</button>" in html and 'id="kop-uitslagen"' in html
        r = c.post(f"/wedstrijd/{ids['w']}/uitslagen")
        html = r.get_data(as_text=True)
        # Niels moet gecontroleerd worden: controlepagina, de rest is al opgeslagen.
        assert r.status_code == 200 and "Uitslagen controleren" in html and "Niels van Proefstra" in html
        assert "Uitslagen geïmporteerd: 4 nieuwe prestaties van 2 atleten." in html
        assert f'name="kandidaat-p0" value="{ids["niels"]}"' in html
        assert "Pim" not in html.split('id="tabel-controle"')[1]                # geen andere namen in het formulier
        prestaties = html.split('name="prestaties-p0" value="')[1].split('"')[0]
        r = c.post(f"/wedstrijd/{ids['w']}/uitslagen/bevestigen", data={
            "sleutel": "p0", "naam-p0": "Niels van Proefstra", "club-p0": "", "kandidaat-p0": ids["niels"],
            "prestaties-p0": prestaties.replace("&#34;", '"').replace("&quot;", '"'), "keuze-p0": ids["niels"]})
        assert r.status_code == 302 and r.headers["Location"].endswith("#kop-uitslagen")
        html = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "1 prestatie opgeslagen voor Niels van Proefstra." in html
        assert "Uitslagen bijwerken" in html and "11,54" in html and ">PR</span>" in html
        assert 'id="tabel-uitslagen"' in html
        # Overzicht 'Wedstrijden': de afgelopen wedstrijd heeft nu een uitslag.
        assert "5 prestaties" in c.get("/wedstrijden?afgelopen=1").get_data(as_text=True)


def test_knop_alleen_na_de_wedstrijd():
    with opslag() as (db, tmp, ids):
        later = planning.plan_wedstrijd(db, "Straks", date.today() + timedelta(days=5),
                                        link="https://www.atletiek.nu/wedstrijd/main/12345/")
        html = app_client(tmp).get(f"/wedstrijd/{later.id}").get_data(as_text=True)
        assert "Uitslagen importeren" not in html and 'id="kop-uitslagen"' not in html
        los = planning.plan_wedstrijd(db, "Zonder link", DAG)
        html = app_client(tmp).get(f"/wedstrijd/{los.id}").get_data(as_text=True)
        assert "Uitslagen importeren</button>" not in html and "Gegevens wijzigen</a>" in html
        assert "de link naar de wedstrijd op atletiek.nu of Seltec in" in html
