"""Tests voor doelen: groep- en persoonlijke doelen, meestal bij een wedstrijd.

  * models/doel.py: controles per soort;
  * Opslag: opslaan en lezen (pseudoniem in prestaties.db), controles, opruimen
    bij het verwijderen van een atleet of wedstrijd;
  * groepen/doelen.py: status per regel (prestatie, leerdoel, vrij, met de hand),
    formulier, aanvullen uit inschrijvingen;
  * blokken op de groeps-, atleet- en wedstrijdpagina en de pagina's zelf.

Alleen nepgegevens en een testsleutel. Werkt met pytest en los: `python tests/test_doelen.py`.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_groep_landingspagina import TESTSLEUTEL, VANDAAG, opslag  # noqa: E402

from db.queries import OpslagFout  # noqa: E402
from groepen import doelen as doelbeheer  # noqa: E402
from models import (Atleet, Doel, DoelRegel, Groep, Inschrijving, LeerdoelScore, Prestatie,  # noqa: E402
                    Wedstrijd)

WEDSTRIJDDAG = VANDAAG + timedelta(days=8)              # za 24 okt 2026


def _fout(f, *, soort=OpslagFout):
    try:
        f()
    except soort as e:
        return str(e)
    raise AssertionError("verwachtte een fout")


def _basis(db):
    """Groep met Anna en Bram, een wedstrijd, en de ids van 100m en verspringen."""
    anna = db.atleet_opslaan(Atleet("Anna", "Voorbeeld", geslacht="V", geboortedatum="2011")).master_id
    bram = db.atleet_opslaan(Atleet("Bram", "Test", geslacht="M", geboortedatum="2012")).master_id
    cas = db.atleet_opslaan(Atleet("Cas", "Proef")).master_id                    # niet in de groep
    g = db.groep_opslaan(Groep("U16 sprint", "2026-2027", [anna, bram]))
    w = db.wedstrijd_opslaan(Wedstrijd("Competitiefinale", WEDSTRIJDDAG))
    return {"anna": anna, "bram": bram, "cas": cas, "groep": g.id, "w": w.id,
            "100m": db.onderdeel("100m").id, "ver": db.onderdeel("Verspringen").id}


def _prestatie(db, ids, wie, onderdeel, waarde, datum, *, wedstrijd=None, wind=1.0):
    db.prestatie_opslaan(Prestatie(onderdeel=onderdeel, datum=datum, waarde=waarde, atleet_id=ids[wie],
                                   wedstrijd_id=wedstrijd, wind=wind, bron="handmatig"))


# ============================================================
# Model
# ============================================================
def test_model():
    r = DoelRegel("vrij", omschrijving="  Ploeg haalt 18 000 punten ", onderdeel_id=3, streefwaarde=1)
    assert (r.omschrijving, r.onderdeel_id, r.streefwaarde, r.voor_groep) == ("Ploeg haalt 18 000 punten", None, None, True)
    for f in (lambda: DoelRegel("snelheid"), lambda: DoelRegel("prestatie", onderdeel_id=1),
              lambda: DoelRegel("leerdoel", leerdoel_id="SPR-U14-01", streefwaarde=6),
              lambda: DoelRegel("leerdoel", leerdoel_id="SPR-U14-01", streefwaarde=2.5),
              lambda: DoelRegel("vrij"), lambda: DoelRegel("vrij", omschrijving="x", beoordeling="top"),
              lambda: Doel(" "), lambda: Doel("x" * 121),
              lambda: Doel("NK", startdatum=date(2026, 11, 1), datum=date(2026, 10, 1))):
        _fout(f, soort=ValueError)
    assert Doel("NK", groep_id=None).persoonlijk


# ============================================================
# Opslag
# ============================================================
def test_opslag():
    with opslag() as (db, _):
        ids = _basis(db)
        d = db.doel_opslaan(Doel("Finale", ids["groep"], ids["w"], regels=[
            DoelRegel("prestatie", ids["anna"], ids["100m"], streefwaarde=12.8),
            DoelRegel("vrij", omschrijving="Ploeg haalt 18 000 punten")]))
        terug = db.doel(d.id)
        assert terug.startdatum == date.today() and terug.datum is None
        assert [(r.soort, r.atleet_id, r.streefwaarde) for r in terug.regels] == [
            ("prestatie", ids["anna"], 12.8), ("vrij", None, None)]
        # In prestaties.db staat geen master_id, alleen het pseudoniem.
        ruw = db.prestaties_db.execute("SELECT atleet_ref FROM doel_regel WHERE atleet_ref IS NOT NULL").fetchone()[0]
        assert ruw != ids["anna"] and len(ruw) == 32

        assert "groep" in _fout(lambda: db.doel_opslaan(Doel("x", ids["groep"], ids["w"], regels=[
            DoelRegel("prestatie", ids["cas"], ids["100m"], streefwaarde=13)])))
        assert "precies één atleet" in _fout(lambda: db.doel_opslaan(Doel("x", None, ids["w"], regels=[
            DoelRegel("prestatie", ids["anna"], ids["100m"], streefwaarde=13),
            DoelRegel("prestatie", ids["bram"], ids["100m"], streefwaarde=13)])))
        assert "precies één atleet" in _fout(lambda: db.doel_opslaan(Doel("x", None, ids["w"])))
        assert "wedstrijd of een streefdatum" in _fout(lambda: db.doel_opslaan(Doel("x", ids["groep"])))
        assert "Leerdoel" in _fout(lambda: db.doel_opslaan(Doel("x", ids["groep"], ids["w"], regels=[
            DoelRegel("leerdoel", ids["anna"], leerdoel_id="XXX-U99-99", streefwaarde=3)])))
        assert "voor de startdatum" in _fout(lambda: db.doel_opslaan(Doel("x", ids["groep"], ids["w"],
                                                                           startdatum=WEDSTRIJDDAG + timedelta(1))))
        _fout(lambda: db.doel_opslaan(Doel("x", 9999, ids["w"])))
        _fout(lambda: db.doel_opslaan(Doel("x", ids["groep"], 9999)))

        # Wie de groep verliet, mag in een bestaand doel blijven staan.
        g = db.groep(ids["groep"])
        g.verwijder(ids["anna"])
        db.groep_opslaan(g)
        terug.titel = "Finale 2026"
        db.doel_opslaan(terug)
        assert db.doel(d.id).titel == "Finale 2026"

        persoonlijk = db.doel_opslaan(Doel("NK indoor", None, datum=WEDSTRIJDDAG + timedelta(days=100), regels=[
            DoelRegel("prestatie", ids["bram"], ids["ver"], streefwaarde=5.2)]))
        assert [x.titel for x in db.doelen_van_atleet(ids["bram"])] == ["NK indoor"]
        assert [x.titel for x in db.doelen_van_atleet(ids["anna"])] == ["Finale 2026"]
        assert [x.titel for x in db.doelen_van_groep(ids["groep"])] == ["Finale 2026"]
        assert [x.id for x in db.doelen_van_wedstrijd(ids["w"])] == [d.id]

        # Wedstrijd weg (nog geen prestaties): het doel houdt de datum.
        db.wedstrijd_verwijderen(ids["w"])
        assert (db.doel(d.id).wedstrijd_id, db.doel(d.id).datum) == (None, WEDSTRIJDDAG)

        # Atleet weg (AVG): zijn regels weg; een persoonlijk doel zonder regels ook.
        db.atleet_verwijderen(ids["bram"])
        assert db.doel(persoonlijk.id) is None
        db.atleet_verwijderen(ids["anna"])
        assert [r.soort for r in db.doel(d.id).regels] == ["vrij"]
        db.doel_verwijderen(d.id)
        assert db.doel(d.id) is None and db.prestaties_db.execute("SELECT COUNT(*) FROM doel_regel").fetchone()[0] == 0


# ============================================================
# Status
# ============================================================
def test_status_prestatie_bij_wedstrijd():
    with opslag() as (db, _):
        ids = _basis(db)
        d = db.doel_opslaan(Doel("Finale", ids["groep"], ids["w"], startdatum=VANDAAG - timedelta(30), regels=[
            DoelRegel("prestatie", ids["anna"], ids["100m"], streefwaarde=12.8),
            DoelRegel("prestatie", ids["bram"], ids["ver"], streefwaarde=5.0),
            DoelRegel("vrij", omschrijving="Ploeg haalt 18 000 punten")]))
        # Een snellere tijd vóór de wedstrijd telt niet: het doel is bij de wedstrijd.
        _prestatie(db, ids, "anna", "100m", 12.5, VANDAAG - timedelta(5))
        s = doelbeheer.doelstand(db, d, vandaag=VANDAAG)
        assert [r.status for r in s.standen] == ["open", "open", "open"] and s.dagen_tot == 8
        assert s.standen[0].wat == "100m ≤ 12,80" and s.standen[1].wat == "Verspringen ≥ 5,00 m"
        assert s.standen[2].wie == "Hele groep"

        _prestatie(db, ids, "anna", "100m", 12.6, WEDSTRIJDDAG, wedstrijd=ids["w"], wind=2.4)     # te veel wind
        _prestatie(db, ids, "anna", "100m", 12.75, WEDSTRIJDDAG, wedstrijd=ids["w"])
        _prestatie(db, ids, "bram", "Verspringen", 4.9, WEDSTRIJDDAG, wedstrijd=ids["w"], wind=0.5)
        s = doelbeheer.doelstand(db, d, vandaag=WEDSTRIJDDAG + timedelta(1))
        assert [(r.status, r.resultaat) for r in s.standen] == [
            ("behaald", "12,75"), ("niet", "4,90 m"), ("te_beoordelen", None)]
        assert s.behaald == 1 and s.telling["niet"] == 1 and s.geweest

        # Met de hand beoordelen gaat voor.
        d.regels[2].beoordeling = "behaald"
        d.regels[1].beoordeling = "deels"
        db.doel_opslaan(d)
        s = doelbeheer.doelstand(db, db.doel(d.id), vandaag=WEDSTRIJDDAG + timedelta(1))
        assert [r.status for r in s.standen] == ["behaald", "deels", "behaald"]


def test_status_zonder_uitslag_en_periode():
    with opslag() as (db, _):
        ids = _basis(db)
        bij_wedstrijd = db.doel_opslaan(Doel("Finale", ids["groep"], ids["w"], regels=[
            DoelRegel("prestatie", ids["bram"], ids["100m"], streefwaarde=13.5)]))
        s = doelbeheer.doelstand(db, bij_wedstrijd, vandaag=WEDSTRIJDDAG + timedelta(1))
        assert (s.standen[0].status, s.standen[0].uitleg) == ("te_beoordelen", "nog geen uitslag")

        periode = db.doel_opslaan(Doel("Najaar", ids["groep"], startdatum=VANDAAG, datum=VANDAAG + timedelta(60), regels=[
            DoelRegel("prestatie", ids["anna"], ids["ver"], streefwaarde=5.0)]))
        _prestatie(db, ids, "anna", "Verspringen", 5.3, VANDAAG - timedelta(1))           # vóór de start
        assert doelbeheer.doelstand(db, periode, vandaag=VANDAAG).standen[0].status == "open"
        _prestatie(db, ids, "anna", "Verspringen", 5.05, VANDAAG + timedelta(20))
        r = doelbeheer.doelstand(db, periode, vandaag=VANDAAG + timedelta(21)).standen[0]
        assert (r.status, r.resultaat, r.resultaat_datum) == ("behaald", "5,05 m", VANDAAG + timedelta(20))
        leeg = db.doel_opslaan(Doel("Leeg", ids["groep"], startdatum=VANDAAG, datum=VANDAAG + timedelta(5), regels=[
            DoelRegel("prestatie", ids["bram"], ids["ver"], streefwaarde=5.0)]))
        r = doelbeheer.doelstand(db, leeg, vandaag=VANDAAG + timedelta(6)).standen[0]
        assert (r.status, r.uitleg) == ("niet", "geen prestatie in deze periode")


def test_status_leerdoel():
    with opslag() as (db, _):
        ids = _basis(db)
        ld = db.leerdoelen()[0]
        d = db.doel_opslaan(Doel("Techniek", ids["groep"], startdatum=VANDAAG, datum=VANDAAG + timedelta(30), regels=[
            DoelRegel("leerdoel", ids["anna"], leerdoel_id=ld.id, streefwaarde=4)]))
        r = doelbeheer.doelstand(db, d, vandaag=VANDAAG).standen[0]
        assert r.status == "open" and r.wat.startswith(f"{ld.id}: score ≥ 4")
        db.leerdoelscore_opslaan(LeerdoelScore(ids["anna"], ld.id, 3, VANDAAG + timedelta(5)))
        assert doelbeheer.doelstand(db, d, vandaag=VANDAAG + timedelta(6)).standen[0].resultaat == "score 3"
        db.leerdoelscore_opslaan(LeerdoelScore(ids["anna"], ld.id, 4, VANDAAG + timedelta(25)))
        db.leerdoelscore_opslaan(LeerdoelScore(ids["anna"], ld.id, 2, VANDAAG + timedelta(40)))   # na de streefdatum
        r = doelbeheer.doelstand(db, d, vandaag=VANDAAG + timedelta(45)).standen[0]
        assert (r.status, r.resultaat) == ("behaald", "score 4")


# ============================================================
# Formulier
# ============================================================
def _form(ids, **extra):
    f = {"titel": "Competitiefinale", "wedstrijd": str(ids["w"]), "startdatum": VANDAAG.isoformat(), "datum": "",
         "beschrijving": "Laatste wedstrijd van het seizoen",
         "regel-0-atleet": ids["anna"], "regel-0-soort": "prestatie", "regel-0-onderdeel": str(ids["100m"]),
         "regel-0-streef": "12,80",
         "regel-1-atleet": "", "regel-1-soort": "vrij", "regel-1-omschrijving": "Ploeg haalt 18 000 punten",
         "regel-2-atleet": ids["bram"], "regel-2-soort": "prestatie", "regel-2-onderdeel": str(ids["ver"]),
         "regel-2-streef": "",                                           # leeg: telt niet mee
         "regel-3-atleet": ids["bram"], "regel-3-soort": "vrij", "regel-3-omschrijving": "", "regel-3-beoordeling": ""}
    f.update(extra)
    return f


def test_formulier_en_opslaan():
    with opslag() as (db, _):
        ids = _basis(db)
        f = doelbeheer.doelformulier(db, groep_id=ids["groep"], vandaag=VANDAAG)
        assert f.nieuw and not f.persoonlijk and len(f.regels) == doelbeheer.LEGE_REGELS
        assert [a.voornaam for a in f.atleten] == ["Bram", "Anna"] and f.waarden["startdatum"] == VANDAAG.isoformat()
        assert ids["w"] in [w.id for w in f.wedstrijden]

        d = doelbeheer.opslaan(db, _form(ids), groep_id=ids["groep"])
        assert [(r.soort, r.atleet_id, r.streefwaarde) for r in d.regels] == [
            ("prestatie", ids["anna"], 12.8), ("vrij", None, None)]
        f = doelbeheer.doelformulier(db, doel_id=d.id, vandaag=VANDAAG)
        assert [(r.soort, r.streef) for r in f.regels[:2]] == [("prestatie", "12,80"), ("vrij", "")]
        assert f.waarden["wedstrijd"] == str(ids["w"]) and not f.nieuw

        for extra, tekst in (({"regel-0-streef": "snel"}, "Regel 1: 'snel' is geen geldige tijd"),
                             ({"regel-0-onderdeel": ""}, "Regel 1: kies een onderdeel"),
                             ({"regel-1-omschrijving": "", "regel-1-beoordeling": "behaald"}, "Regel 2: beschrijf"),
                             ({"regel-2-soort": "leerdoel", "regel-2-leerdoel": "XX", "regel-2-streef": "3"}, "bestaand leerdoel"),
                             ({"titel": ""}, "titel"), ({"datum": "morgen"}, "Streefdatum")):
            assert tekst in _fout(lambda: doelbeheer.opslaan(db, _form(ids, **extra), doel_id=d.id)), extra
        d2 = doelbeheer.opslaan(db, _form(ids, **{"regel-0-streef": "2:05,00", "regel-0-onderdeel": str(ids["100m"]),
                                                   "evaluatie": "Goed gegaan"}), doel_id=d.id)
        assert d2.id == d.id and d2.regels[0].streefwaarde == 125.0 and db.doel(d.id).evaluatie == "Goed gegaan"
        assert doelbeheer.doelformulier(db, doel_id=9999) is None
        assert doelbeheer.doelformulier(db, groep_id=9999) is None


def test_persoonlijk_doel():
    with opslag() as (db, _):
        ids = _basis(db)
        f = doelbeheer.doelformulier(db, master_id=ids["cas"], vandaag=VANDAAG)
        assert f.persoonlijk and [a.voornaam for a in f.atleten] == ["Cas"] and f.regels[0].atleet == ids["cas"]
        form = {"titel": "Clubrecord", "datum": (VANDAAG + timedelta(90)).isoformat(), "startdatum": VANDAAG.isoformat(),
                "regel-0-atleet": ids["anna"],                                  # wordt genegeerd: persoonlijk
                "regel-0-soort": "prestatie", "regel-0-onderdeel": str(ids["ver"]), "regel-0-streef": "5,50"}
        d = doelbeheer.opslaan(db, form, master_id=ids["cas"])
        assert d.persoonlijk and d.regels[0].atleet_id == ids["cas"]
        assert "minstens één regel" in _fout(lambda: doelbeheer.opslaan(db, {"titel": "x", "datum": "2026-12-01"},
                                                                        master_id=ids["cas"]))
        assert doelbeheer.doelformulier(db, doel_id=d.id).atleet.voornaam == "Cas"


def test_aanvullen_uit_inschrijvingen():
    with opslag() as (db, _):
        ids = _basis(db)
        for wie, o in (("anna", "100m"), ("anna", "ver"), ("bram", "100m"), ("cas", "100m")):
            db.inschrijving_opslaan(Inschrijving(ids[wie], ids["w"], ids[o]))
        db.inschrijving_opslaan(Inschrijving(ids["bram"], ids["w"], None))           # onderdelen volgen later
        _prestatie(db, ids, "anna", "100m", 12.93, VANDAAG - timedelta(40))
        f = doelbeheer.doelformulier(db, groep_id=ids["groep"], ingevuld=_form(ids, **{"regel-1-soort": "vrij"}),
                                     vandaag=VANDAAG)
        f = doelbeheer.aanvullen(db, f)
        paren = [(r.atleet, r.onderdeel) for r in f.regels if r.onderdeel]
        # Anna 100m stond er al; Anna verspringen en Bram 100m komen erbij; Cas zit niet in de groep.
        assert paren.count((ids["anna"], str(ids["100m"]))) == 1
        assert (ids["anna"], str(ids["ver"])) in paren and (ids["bram"], str(ids["100m"])) in paren
        assert all(a != ids["cas"] for a, _ in paren) and "2 regels toegevoegd" in f.melding
        assert next(r for r in f.regels if r.onderdeel == str(ids["100m"]) and r.atleet == ids["anna"]).pr == "12,93"
        f = doelbeheer.aanvullen(db, doelbeheer.doelformulier(db, groep_id=ids["groep"], vandaag=VANDAAG))
        assert "Kies eerst een wedstrijd" in f.melding


# ============================================================
# Blokken en pagina's
# ============================================================
def test_blokken():
    from atleten import landingspagina as atleetpagina
    from groepen import landingspagina as groeppagina
    with opslag() as (db, _):
        ids = _basis(db)
        db.doel_opslaan(Doel("Finale", ids["groep"], ids["w"], regels=[
            DoelRegel("prestatie", ids["anna"], ids["100m"], streefwaarde=12.8),
            DoelRegel("prestatie", ids["bram"], ids["100m"], streefwaarde=13.5)]))
        oud = db.doel_opslaan(Doel("Voorjaar", ids["groep"], startdatum=VANDAAG - timedelta(100),
                                   datum=VANDAAG - timedelta(50), regels=[DoelRegel("vrij", omschrijving="Iedereen een PR")]))
        lp = groeppagina.landingspagina(db, ids["groep"], peildatum=VANDAAG)
        assert [s.doel.titel for s in lp.doelen] == ["Finale"] and lp.aantal_doelen == 1
        assert [b.titel for b in lp.jaar.doelen] == ["Voorjaar", "Finale"]          # markeringen, ook zonder periodisering
        ap = atleetpagina.landingspagina(db, ids["anna"], peildatum=VANDAAG)
        assert [(s.doel.titel, len(s.standen)) for s in ap.doelen] == [("Finale", 1)]   # alleen haar eigen regel
        o = doelbeheer.doelenoverzicht(db, ids["groep"], vandaag=VANDAAG)
        assert [s.doel.titel for s in o.komend] == ["Finale"] and [s.doel.id for s in o.geweest] == [oud.id]
        assert doelbeheer.doelenoverzicht(db, 9999) is None


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        ids = _basis(db)
        db.inschrijving_opslaan(Inschrijving(ids["anna"], ids["w"], ids["100m"]))
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        gid = ids["groep"]
        html = c.get(f"/groep/{gid}").get_data(as_text=True)
        assert f'href="/groep/{gid}/doelen"' in html and "Geen komende doelen" in html
        assert "Geen komende doelen" in c.get(f"/groep/{gid}/doelen").get_data(as_text=True)

        pad = f"/groep/{gid}/doel/nieuw"
        assert 'name="regel-0-soort"' in c.get(pad).get_data(as_text=True)
        r = c.post(pad, data={"titel": "", "wedstrijd": str(ids["w"]), "stap": "aanvullen"})
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "1 regel toegevoegd uit de inschrijvingen" in html
        assert db.doelen_van_groep(gid) == []                                       # aanvullen slaat niets op
        r = c.post(pad, data=_form(ids, stap="opslaan"))
        assert r.status_code == 302
        did = db.doelen_van_groep(gid)[0].id
        html = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Doel &#39;Competitiefinale&#39; opgeslagen." in html and "100m ≤ 12,80" in html and "Hele groep" in html
        assert c.post(pad, data=_form(ids, **{"regel-0-streef": "snel"})).status_code == 400

        assert "Competitiefinale" in c.get(f"/groep/{gid}").get_data(as_text=True)
        assert "100m ≤ 12,80" in c.get(f"/atleet/{ids['anna']}").get_data(as_text=True)
        assert "Competitiefinale" in c.get(f"/wedstrijd/{ids['w']}").get_data(as_text=True)

        assert 'value="12,80"' in c.get(f"/doel/{did}/bewerken").get_data(as_text=True)
        r = c.post(f"/doel/{did}/bewerken", data=_form(ids, titel="Finale", evaluatie="Mooi"))
        assert r.status_code == 302 and db.doel(did).titel == "Finale"

        pad = f"/atleet/{ids['cas']}/doel/nieuw"
        assert "Persoonlijk doel van Cas Proef" in c.get(pad).get_data(as_text=True)
        r = c.post(pad, data={"titel": "Clubrecord", "datum": "2027-01-31", "startdatum": "2026-10-19",
                              "regel-0-soort": "vrij", "regel-0-omschrijving": "Hordenritme in drie passen"})
        assert r.status_code == 302
        persoonlijk = db.doelen_van_atleet(ids["cas"])[0]
        assert "Persoonlijk doel" in c.get(f"/doel/{persoonlijk.id}").get_data(as_text=True)

        r = c.post(f"/doel/{persoonlijk.id}/verwijderen")
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/atleet/{ids['cas']}#kop-wed")
        r = c.post(f"/doel/{did}/verwijderen")
        assert r.headers["Location"].endswith(f"/groep/{gid}/doelen")
        for pad in ("/doel/9999", "/doel/9999/bewerken", "/groep/9999/doelen", "/groep/9999/doel/nieuw",
                    "/atleet/" + "0" * 32 + "/doel/nieuw"):
            assert c.get(pad).status_code == 404, pad
        assert c.post("/doel/9999/verwijderen").status_code == 404


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
