"""Tests voor 'Groep importeren' (src/groepen/groep_importeren.py en de route /importeren/groep).

Gebruikt de geanonimiseerde profielpagina uit tests/fixtures/ in plaats van atletiek.nu, een
tijdelijke map met versleutelde databases en een vaste testsleutel; alleen nepgegevens.

"""

import re
from pathlib import Path

from test_startpagina import opslag

from atleten import beheer
from db.queries import OpslagFout
from groepen import groep_importeren as gi
from importers.base import ImportFout
from ui.app import maak_app
from werkzeug.datastructures import MultiDict
from hulp import TESTSLEUTEL

PROFIEL = (Path(__file__).parent / "fixtures" / "atletieknu_profiel.html").read_text(encoding="utf-8")


def profiel(_nummer: str) -> str:
    return PROFIEL


def rij(voornaam="", achternaam="", atletieknu="", tussenvoegsel="", geboortedatum="", geslacht="", licentie=""):
    return {"voornaam": voornaam, "tussenvoegsel": tussenvoegsel, "achternaam": achternaam,
            "geboortedatum": geboortedatum, "geslacht": geslacht, "atletieknu": atletieknu,
            "au_licentienummer": licentie}


def formulier(rijen, **extra):
    """Formulier zoals de browser het stuurt: elk veld één keer per regel (ook lege regels)."""
    velden = [(v, r[v]) for r in rijen for v in gi.VELDEN]
    return MultiDict(velden + list(extra.items()))


def _client(tmp, haal=profiel):
    app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
    app.config["TESTING"] = True
    app.config["AVS_HAAL_PROFIEL"] = haal
    return app.test_client()


# ----------------------------------------------------------------- tabel → CSV

def test_rijen_uit_formulier_en_csv():
    f = formulier([rij("Test", "Vries", "999999", tussenvoegsel=" de "), rij(), rij("Proef", "Jansen; Smit", "")])
    rijen = gi.rijen_uit_formulier(f)
    assert len(rijen) == 2                                   # lege regel valt weg
    assert rijen[0]["tussenvoegsel"] == "de"
    tekst = gi.maak_csv(rijen)
    assert tekst.splitlines()[0] == "voornaam;tussenvoegsel;achternaam;geboortedatum;geslacht;atletieknu;au_licentienummer"
    assert '"Jansen; Smit"' in tekst                         # ; in een waarde wordt netjes ingepakt
    assert len(gi.aangevuld(rijen)) == gi.LEGE_RIJEN
    assert len(gi.aangevuld([rij("a")] * 10)) == 12           # altijd een paar lege regels erbij


def test_controleer_meldt_fouten_per_regel():
    try:
        gi.controleer([rij("Test", "Vries", "999999"), rij("Proef", "", "111111"),
                       rij("Nog", "Een", "999999"), rij("Datum", "Fout", "222222", geboortedatum="31-31-2011")])
        raise AssertionError("TabelFout verwacht")
    except gi.TabelFout as e:
        assert set(e.fouten) == {1, 2, 3}
        assert e.fouten[1].startswith("Voor- of achternaam ontbreekt")
        assert "regel 1" in e.fouten[2]                       # regelnummer in de tabel, niet in de CSV
        assert "geboortedatum" in e.fouten[3]
    try:
        gi.controleer([])
        raise AssertionError("TabelFout verwacht")
    except gi.TabelFout as e:
        assert e.algemeen and not e.fouten
    lees = gi.controleer([rij("Test", "Vries", "https://www.atletiek.nu/atleet/profiel/999999/", "de",
                              "2011", "meisje")])
    r = lees.regels[0]
    assert (r.voornaam, r.tussenvoegsel, r.achternaam, r.atletieknu_id, r.geboortedatum, r.geslacht) == \
        ("Test", "de", "Vries", "999999", "2011", "V")


def test_licentienummer_in_de_tabel():
    assert gi.VELDEN[-1] == "au_licentienummer"              # als laatste: oude plak-volgorde blijft gelijk
    lees = gi.controleer([rij("Test", "Vries", "999999", licentie="12 34 567"), rij("Proef", "Jansen", "888888")])
    assert [r.au_licentienummer for r in lees.regels] == ["1234567", None]
    try:
        gi.controleer([rij("Test", "Vries", "999999", licentie="AU12")])
        raise AssertionError("TabelFout verwacht")
    except gi.TabelFout as e:
        assert "AU-licentienummer" in e.fouten[0]


def test_importeren_met_licentienummer():
    with opslag(met_voorbeeld=False) as (db, _):
        res = gi.importeren(db, [rij("Test", "Vries", "999999", licentie="1234567")],
                            gi.Groepkeuze("nieuw", naam="Licenties"), haal_html=profiel)
        assert len(res.gelukt) == 1
        assert db.atleet_op_au_licentienummer("1234567").atletieknu_id == "999999"


# ----------------------------------------------------------------- importeren

def test_importeren_in_nieuwe_groep():
    with opslag(met_voorbeeld=False) as (db, _):
        res = gi.importeren(db, [rij("Test", "Vries", "999999", "de", "25-03-2011", "M"),
                                 rij("Proef", "Jansen", "888888")],
                            gi.Groepkeuze("nieuw", naam="U14 import", seizoen="2026-2027"), haal_html=profiel)
        assert len(res.gelukt) == 2 and not res.mislukt and res.nieuwe_atleten == 2
        assert res.groep_nieuw and res.groep.naam == "U14 import" and res.groep.seizoen == "2026-2027"
        g = db.groep(res.groep.id)
        assert sorted(db.atleet(m).naam for m in g.leden) == ["Proef Jansen", "Test de Vries"]
        a = db.atleet_op_atletieknu_id("999999")
        assert (a.geboortedatum, a.geslacht) == ("2011-03-25", "M")
        assert "Groep U14 import aangemaakt met 2 atleten" in res.tekst
        assert "Test" not in res.tekst                         # samenvatting zonder namen


def test_importeren_in_bestaande_groep_en_opnieuw():
    with opslag() as (db, _):
        g = db.groepen()[0]                                    # 'U16 sprint' met Anna
        anna = g.leden[0]
        res = gi.importeren(db, [rij("Test", "Vries", "999999")], gi.Groepkeuze("bestaand", g.id),
                            haal_html=profiel)
        assert [a.naam for a in res.in_groep_erbij] == ["Test Vries"] and res.al_in_groep == 0
        leden = db.groep(g.id).leden
        assert anna in leden and len(leden) == 2               # wie er al in zat, blijft erin
        # Nog eens: niets dubbel, en de atleet zat er al in.
        res2 = gi.importeren(db, [rij("Test", "Vries", "999999")], gi.Groepkeuze("bestaand", g.id),
                             haal_html=profiel)
        assert res2.gelukt[0].uitkomst.status == "bestond" and res2.gelukt[0].uitkomst.nieuw == 0
        assert res2.al_in_groep == 1 and not res2.in_groep_erbij
        assert len(db.groep(g.id).leden) == 2
        assert len(db.atleten(alleen_actief=False)) == 2
        assert "(1 zat er al in)" in res2.tekst


def test_fouten_vooraf_veranderen_niets():
    with opslag() as (db, _):
        bestaande = db.groepen()[0]
        # Tabel klopt niet: niets opgehaald.
        opgehaald = []
        try:
            gi.importeren(db, [rij("Test", "", "999999")], gi.Groepkeuze("nieuw", naam="X"),
                          haal_html=lambda n: opgehaald.append(n) or PROFIEL)
            raise AssertionError("TabelFout verwacht")
        except gi.TabelFout:
            pass
        # Groep bestaat niet / naam bestaat al / geen naam: niets opgehaald.
        for keuze in (gi.Groepkeuze("bestaand", 9999), gi.Groepkeuze("bestaand", None),
                      gi.Groepkeuze("nieuw", naam=bestaande.naam, seizoen=bestaande.seizoen),
                      gi.Groepkeuze("nieuw", naam="")):
            try:
                gi.importeren(db, [rij("Test", "Vries", "999999")], keuze,
                              haal_html=lambda n: opgehaald.append(n) or PROFIEL)
                raise AssertionError(f"OpslagFout verwacht voor {keuze}")
            except OpslagFout:
                pass
        assert not opgehaald
        assert len(db.atleten(alleen_actief=False)) == 1 and len(db.groepen()) == 1


def test_een_mislukte_atleet_stopt_de_rest_niet():
    def haal(nummer):
        if nummer == "111111":
            raise ConnectionError("geen internet")             # wordt een nette ImportFout
        return PROFIEL

    with opslag(met_voorbeeld=False) as (db, _):
        res = gi.importeren(db, [rij("Weg", "Fout", "111111"), rij("Test", "Vries", "999999")],
                            gi.Groepkeuze("nieuw", naam="Gemengd"), haal_html=haal)
        assert [r.index for r in res.mislukt] == [0] and [r.index for r in res.gelukt] == [1]
        assert "niet bereikbaar" in res.mislukt[0].reden
        assert len(db.groep(res.groep.id).leden) == 1
        # Alles mislukt in een nieuwe groep: geen lege groep aanmaken.
        res = gi.importeren(db, [rij("Weg", "Fout", "111111")], gi.Groepkeuze("nieuw", naam="Leeg"),
                            haal_html=lambda _: (_ for _ in ()).throw(ImportFout("browsercontrole")))
        assert res.groep is None and [g.naam for g in db.groepen()] == ["Gemengd"]


def test_zelfde_naam_zonder_nummer():
    with opslag(met_voorbeeld=False) as (db, _):
        oud = beheer.nieuwe_atleet(db, "Test", "Jansen")
        keuze = gi.Groepkeuze("nieuw", naam="A")
        res = gi.importeren(db, [rij("Test", "Jansen", "999999")], keuze, haal_html=profiel)   # overslaan
        assert not res.gelukt and "Zelfde naam" in res.mislukt[0].reden and res.groep is None
        res = gi.importeren(db, [rij("Test", "Jansen", "999999")], keuze, haal_html=profiel, dubbel="zelfde")
        assert res.gelukt[0].uitkomst.status == "id_toegevoegd"
        assert db.atleet(oud.master_id).atletieknu_id == "999999"
        assert db.groep(res.groep.id).leden == [oud.master_id]
        res = gi.importeren(db, [rij("Test", "Jansen", "888888")], gi.Groepkeuze("nieuw", naam="B"),
                            haal_html=profiel, dubbel="nieuw")
        assert res.gelukt[0].uitkomst.status == "nieuw"
        assert len(db.atleten(alleen_actief=False)) == 2


# ----------------------------------------------------------------- pagina

def test_pagina_leeg():
    with opslag() as (db, tmp):
        c = _client(tmp)
        html = c.get("/importeren/groep").get_data(as_text=True)
        assert html.count('name="voornaam"') == gi.LEGE_RIJEN
        assert 'href="/importeren">&larr; Importeren' in html
        assert 'value="bestaand" id="soort-bestaand" checked' in html
        assert "U16 sprint (2026-2027)" in html
        g = db.groepen()[0]
        html = c.get(f"/importeren/groep?groep={g.id}").get_data(as_text=True)
        assert f'<option value="{g.id}" selected>' in html
        assert "Anna" not in html                              # geen namen van bestaande atleten
    with opslag(met_voorbeeld=False) as (_, tmp):
        html = _client(tmp).get("/importeren/groep").get_data(as_text=True)
        assert "nog geen groepen" in html and 'id="soort-bestaand" disabled' in html
        assert 'value="nieuw" id="soort-nieuw" checked' in html


def test_pagina_importeren_en_mislukte_regels_terug_in_tabel():
    def haal(nummer):
        if nummer == "111111":
            raise ImportFout("atletiek.nu gaf een browsercontrole-pagina terug.")
        return PROFIEL

    with opslag() as (db, tmp):
        c = _client(tmp, haal)
        f = formulier([rij("Test", "Vries", "999999", "de"), rij("Weg", "Fout", "111111"), rij()],
                      groepsoort="nieuw", groepnaam="Import U14", seizoen="2026-2027", dubbel="overslaan")
        r = c.post("/importeren/groep", data=f)
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        g = next(g for g in db.groepen() if g.naam == "Import U14")
        assert "1 van de 2 atleten geïmporteerd" in html and "Groep Import U14 aangemaakt met 1 atleet" in html
        assert f'href="/groep/{g.id}"' in html and "Test de Vries" in html
        # De mislukte regel staat weer in de tabel, met de reden; een nieuwe poging gaat naar dezelfde groep.
        assert 'value="Weg"' in html and "browsercontrole" in html and 'value="Test"' not in html
        assert f'<option value="{g.id}" selected>' in html
        assert 'value="bestaand" id="soort-bestaand" checked' in html


def test_pagina_fouten_en_regels_toevoegen():
    with opslag() as (db, tmp):
        c = _client(tmp, lambda _: (_ for _ in ()).throw(AssertionError("mag niet ophalen")))
        # Fout in de tabel: alles blijft staan, rode melding bij de regel, niets opgeslagen.
        f = formulier([rij("Test", "Vries", "999999"), rij("Zonder", "Nummer")],
                      groepsoort="nieuw", groepnaam="Nieuw", seizoen="")
        r = c.post("/importeren/groep", data=f)
        html = r.get_data(as_text=True)
        assert r.status_code == 400 and "Niet geïmporteerd" in html
        assert html.count('class="importrij importrij--fout"') == 1 and "Atletiek.nu-nummer ontbreekt" in html
        assert 'value="Zonder"' in html and 'value="Nieuw"' in html
        assert len(db.groepen()) == 1
        # Geen groep gekozen.
        f = formulier([rij("Test", "Vries", "999999")], groepsoort="bestaand", groep_id="")
        r = c.post("/importeren/groep", data=f)
        assert r.status_code == 400 and "Kies de groep" in r.get_data(as_text=True)
        # 'Regel toevoegen' zonder JavaScript: ingevulde regels blijven, er komen lege bij.
        f = formulier([rij("Test", "Vries", "999999")] * 9, actie="rijen", groepsoort="nieuw", groepnaam="X")
        html = c.post("/importeren/groep", data=f).get_data(as_text=True)
        assert len(re.findall(r'name="voornaam" value="Test"', html)) == 9
        assert html.count('name="voornaam"') >= 9 + gi.RIJEN_ERBIJ
        assert len(db.groepen()) == 1
