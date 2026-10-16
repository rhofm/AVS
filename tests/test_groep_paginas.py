"""Tests voor de pagina's onder een groep: groepen/overzichten.py, groepen/trainingen.py en de routes.

Gebruikt de nepgroep uit test_groep_landingspagina (alleen nepgegevens, testsleutel).
Werkt met pytest en los: `python tests/test_groep_paginas.py`.
"""

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_groep_landingspagina import MAANDAG, TESTSLEUTEL, VANDAAG, opslag, voorbeeldgroep  # noqa: E402

from atleten import beheer, prestaties  # noqa: E402
from db.queries import OpslagFout  # noqa: E402
from groepen import overzichten, trainingen  # noqa: E402
from models import Test, Testresultaat  # noqa: E402


def _met_prestaties(db, ids):
    prestaties.handmatig_toevoegen(db, ids["anna"], "100m", date(2026, 6, 1), "13,20", wind=1.0)
    prestaties.handmatig_toevoegen(db, ids["bram"], "100m", date(2026, 6, 1), "12,90", wind=1.0)
    prestaties.handmatig_toevoegen(db, ids["cas"], "Verspringen", date(2026, 6, 1), "4,10", wind=0.0)
    t = db.test_opslaan(Test("30m vliegend", "s", True))
    db.testresultaat_opslaan(Testresultaat(ids["anna"], t.id, date(2026, 9, 1), 4.25))
    db.testresultaat_opslaan(Testresultaat(ids["anna"], t.id, date(2026, 10, 1), 4.10))
    db.testresultaat_opslaan(Testresultaat(ids["bram"], t.id, date(2026, 9, 1), 4.40))


def test_prs_en_testen():
    """'Beste' alleen binnen de eigen categorie: U16M met U16M, U16V met U16V."""
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)                    # Anna U16V, Bram U16M, Cas U14M
        _met_prestaties(db, ids)
        g = db.groep(ids["groep"])
        dirk = beheer.nieuwe_atleet(db, "Dirk", "Extra", geslacht="M", geboortedatum="2011").master_id   # U16M
        eva = beheer.nieuwe_atleet(db, "Eva", "Extra", geslacht="V", geboortedatum="2011").master_id     # U16V
        zonder = beheer.nieuwe_atleet(db, "Zoë", "Onbekend", geslacht="V").master_id                     # geen categorie
        for m in (dirk, eva, zonder):
            g.voeg_toe(m)
        g = db.groep(db.groep_opslaan(g).id)          # opnieuw ophalen: leden op achternaam
        prestaties.handmatig_toevoegen(db, dirk, "100m", date(2026, 6, 1), "13,40", wind=1.0)
        prestaties.handmatig_toevoegen(db, eva, "100m", date(2026, 6, 1), "13,10", wind=1.0)
        prestaties.handmatig_toevoegen(db, zonder, "100m", date(2026, 6, 1), "11,00", wind=1.0)

        t = overzichten.prs(db, g, peildatum=VANDAAG)
        assert [k.naam for k in t.kolommen] == ["Verspringen", "100m"]            # springen < sprint
        assert [(c, [r.atleet.voornaam for r in rijen]) for c, rijen in t.per_categorie] == [
            ("U14M", ["Cas"]), ("U16M", ["Dirk", "Bram"]), ("U16V", ["Eva", "Anna"]), (None, ["Zoë"])]
        rij = {r.atleet.voornaam: r for r in t.rijen}
        assert rij["Bram"].cellen[1].tekst == "12,90" and rij["Bram"].cellen[1].beste       # beste U16M
        assert not rij["Dirk"].cellen[1].beste
        assert rij["Eva"].cellen[1].beste and not rij["Anna"].cellen[1].beste               # 13,10 < 13,20 bij U16V
        assert not rij["Zoë"].cellen[1].beste                                               # snelste, maar geen categorie
        assert not rij["Cas"].cellen[0].beste                                               # alleen in U14M
        assert rij["Anna"].cellen[0] is None and t.gevuld == 6

        t = overzichten.testresultaten(db, g, peildatum=VANDAAG)
        assert [(k.naam, k.sub) for k in t.kolommen] == [("30m vliegend", "s")]
        rij = {r.atleet.voornaam: r for r in t.rijen}
        assert rij["Anna"].cellen[0].tekst == "4,1" and rij["Anna"].cellen[0].datum == date(2026, 10, 1)
        # Anna (U16V) en Bram (U16M) zitten in verschillende categorieën: geen van beiden 'beste'.
        assert not rij["Anna"].cellen[0].beste and not rij["Bram"].cellen[0].beste and rij["Cas"].cellen[0] is None
        test_id = db.testen()[0].id
        db.testresultaat_opslaan(Testresultaat(eva, test_id, date(2026, 10, 2), 4.30))
        rij = {r.atleet.voornaam: r for r in overzichten.testresultaten(db, g, peildatum=VANDAAG).rijen}
        assert rij["Anna"].cellen[0].beste and not rij["Eva"].cellen[0].beste               # lager is beter


def test_leerdoelen():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        t = overzichten.leerdoelen(db, db.groep(ids["groep"]), peildatum=VANDAAG)
        codes = [k.sub for k in t.kolommen]
        i = codes.index("SPR")
        rij = {r.atleet.voornaam: r for r in t.rijen}
        anna = rij["Anna"].cellen[i]
        assert (anna.zelfstandig, anna.beoordeeld, anna.gemiddelde) == (1, 2, 3.0)
        assert rij["Cas"].cellen[i].beoordeeld == 0 and rij["Cas"].cellen[i].gemiddelde is None
        # Sorteerwaarde: % zelfstandig, dan gemiddelde; niet beoordeeld = None (altijd onderaan).
        assert anna.sortering == anna.pct + 0.3 and rij["Cas"].cellen[i].sortering is None
        assert rij["Bram"].cellen[i].sortering > anna.sortering                     # 1/n zelfstandig, gem. 5
        assert t.gemiddelden[i].beoordeeld == 2 and t.gemiddelden[i].gemiddelde_score == 4.0
        assert all(g is None for n, g in enumerate(t.gemiddelden) if n != i)


def test_register():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        reg = overzichten.aanwezigheid(db, db.groep(ids["groep"]), peildatum=VANDAAG)
        assert [t.onderwerp for t in reg.trainingen] == ["Starts", "Horden", "Niet ingevuld"]   # oudste eerst
        rij = {r.atleet.voornaam: r for r in reg.rijen}
        assert [c.letter for c in rij["Bram"].cellen] == ["X", "A", "?"]
        assert [c.letter for c in rij["Cas"].cellen] == ["?", "M", "?"]
        assert rij["Anna"].percentage == 100.0 and rij["Bram"].percentage == 50.0 and rij["Cas"].percentage == 0.0
        assert [reg.aanwezig_op(i) for i in range(3)] == [1, 2, 0]
        assert reg.percentage == 60.0 and [d.dag for d in reg.per_dag] == ["dinsdag", "donderdag"]
        assert len(overzichten.aanwezigheid(db, db.groep(ids["groep"]), peildatum=VANDAAG, weken=52).trainingen) == 4


def test_trainingen_en_invullen():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        g = db.groep(ids["groep"])
        lijst = trainingen.trainingenlijst(db, g, peildatum=VANDAAG)
        assert [r.training.onderwerp for r in lijst.komend] == ["Startblok", None]
        assert [r.training.onderwerp for r in lijst.geweest] == ["Niet ingevuld", "Horden", "Starts", "Te oud"]
        assert lijst.geweest[1].stand.aanwezig == 2 and lijst.geweest[1].stand.ingevuld == 3
        assert lijst.nog_invullen == 2                                              # 'Niet ingevuld' en 'Te oud'

        di = lijst.geweest[0].training
        tp = trainingen.trainingpagina(db, di.id, peildatum=VANDAAG)
        assert tp.dagen_tot == -3 and tp.vorige.onderwerp == "Horden" and tp.volgende.onderwerp == "Startblok"
        assert {d.status for d in tp.deelnemers} == {"niet_ingevuld"} and len(tp.deelnemers) == 3
        assert {d.status_tekst for d in tp.deelnemers} == {"Niet ingevuld"}
        komend = trainingen.trainingpagina(db, lijst.komend[0].training.id, peildatum=VANDAAG)
        assert {d.status_tekst for d in komend.deelnemers} == {"Verwacht"}
        assert trainingen.trainingpagina(db, 9999) is None

        f = trainingen.invulformulier(db, di.id, peildatum=VANDAAG)
        assert not f.al_ingevuld and [r.status for r in f.regels] == ["aanwezig"] * 3
        assert all(r.ingeroosterd and not r.opgeslagen for r in f.regels)

        form = {f"status-{ids['anna']}": "aanwezig", f"reden-{ids['anna']}": "hoort weg",
                f"status-{ids['bram']}": "blessure", f"reden-{ids['bram']}": "  enkel   verzwikt " + "x" * 100,
                f"status-{ids['cas']}": "", "status-" + "f" * 32: "aanwezig", "iets-anders": "1"}
        assert trainingen.aanwezigheid_opslaan(db, di.id, form) == 2                # Cas leeg, onbekende genegeerd
        opgeslagen = {a.atleet_id: a for a in db.absenties(di.id)}
        assert opgeslagen[ids["anna"]].reden is None
        assert opgeslagen[ids["bram"]].status == "blessure"
        assert opgeslagen[ids["bram"]].reden.startswith("enkel verzwikt x")
        assert len(opgeslagen[ids["bram"]].reden) == trainingen.MAX_REDEN
        f = trainingen.invulformulier(db, di.id, peildatum=VANDAAG)
        assert f.al_ingevuld and {r.atleet.voornaam: r.opgeslagen for r in f.regels} == {"Anna": True, "Bram": True, "Cas": False}

        try:
            trainingen.aanwezigheid_opslaan(db, di.id, {f"status-{ids['cas']}": "ziek"})
            assert False, "onbekende status moet een fout geven"
        except OpslagFout:
            pass

        # Iemand die niet ingeroosterd staat (Anna traint niet op maandag), komt zonder voorstel op de lijst.
        werp_ma = db.trainingen(ids["werp"])[0]
        g.voeg_toe(ids["cas"])
        f = trainingen.invulformulier(db, werp_ma.id, peildatum=VANDAAG)
        assert [(r.atleet.voornaam, r.status, r.ingeroosterd) for r in f.regels] == [("Cas", "aanwezig", True)]


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        _met_prestaties(db, ids)
        gid = ids["groep"]
        di = [t for t in db.trainingen(gid) if t.datum == MAANDAG.replace(day=MAANDAG.day + 1)][0]
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        for pad in ("prs", "testen", "leerdoelen", "aanwezigheid", "aanwezigheid?weken=4", "aanwezigheid?weken=x",
                    "trainingen", "wedstrijden"):
            r = c.get(f"/groep/{gid}/{pad}")
            assert r.status_code == 200, pad
            # Elke link op deze pagina werkt.
            for link in sorted(set(re.findall(r'href="(/(?:groep|atleet|training)/[^"]*)"', r.get_data(as_text=True)))):
                assert c.get(link).status_code == 200, (pad, link)
        ld_html = c.get(f"/groep/{gid}/leerdoelen").get_data(as_text=True)
        assert "sorteerbaar" in ld_html and ld_html.count('class="sorteer"') >= 3 and 'data-eerst="af"' in ld_html
        assert "/static/sorteer.js" in ld_html and c.get("/static/sorteer.js").status_code == 200
        prs_html = c.get(f"/groep/{gid}/prs").get_data(as_text=True)
        assert "12,90" in prs_html and ">U16M</td>" in prs_html and "matrix__groep" not in prs_html
        # Sorteerbaar: ruwe waarde per cel, en de sorteerrichting per kolom (100m: laag = beter).
        assert 'data-sort="12.9"' in prs_html and 'data-sort="test bram"' in prs_html
        assert prs_html.count('class="sorteer"') == 2 + 2 and 'data-eerst="op"' in prs_html
        assert "30m vliegend" in c.get(f"/groep/{gid}/testen").get_data(as_text=True)
        for pad in ("prs", "testen", "leerdoelen", "aanwezigheid", "trainingen"):
            assert c.get(f"/groep/9999/{pad}").status_code == 404

        r = c.get(f"/training/{di.id}")
        assert r.status_code == 200 and "Niet ingevuld" in r.get_data(as_text=True)
        r = c.get(f"/training/{di.id}/aanwezigheid")
        assert r.status_code == 200 and f'name="status-{ids["bram"]}" value="aanwezig" checked' in r.get_data(as_text=True)
        r = c.post(f"/training/{di.id}/aanwezigheid",
                   data={f"status-{ids['anna']}": "aanwezig", f"status-{ids['bram']}": "afgemeld",
                         f"reden-{ids['bram']}": "school", f"status-{ids['cas']}": "aanwezig"})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/training/{di.id}")
        tekst = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Aanwezigheid van 3 atleten opgeslagen." in tekst and "school" in tekst, re.findall(r"class=.melding[^<]*", tekst)
        r = c.post(f"/training/{di.id}/aanwezigheid", data={f"status-{ids['cas']}": "ziek"})
        assert r.status_code == 400 and "Niet opgeslagen" in r.get_data(as_text=True)
        assert c.get("/training/9999").status_code == 404
        assert c.get("/training/9999/aanwezigheid").status_code == 404
        assert c.post("/training/9999/aanwezigheid", data={}).status_code == 404


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
