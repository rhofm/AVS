"""Tests voor src/groepen/groep.py (atleten van een groep wijzigen) en de route /groep/<id>/leden.

Gebruikt de nepgroep uit test_groep_landingspagina (alleen nepgegevens, testsleutel).
Werkt met pytest en los: `python tests/test_groep_leden.py`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_groep_landingspagina import TESTSLEUTEL, VANDAAG, opslag, voorbeeldgroep  # noqa: E402

from atleten import beheer  # noqa: E402
from db.queries import OpslagFout  # noqa: E402
from groepen import groep as groepsbeheer  # noqa: E402


def test_formulier():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)                       # U16 sprint: Anna, Bram, Cas; Dirk Buiten zit nergens in
        oud = beheer.nieuwe_atleet(db, "Oud", "Lid", actief=False).master_id
        f = groepsbeheer.ledenformulier(db, ids["groep"], peildatum=VANDAAG)
        assert [k.atleet.voornaam for k in f.leden] == ["Cas", "Bram", "Anna"]             # op achternaam
        assert {k.atleet.voornaam: k.andere_groepen for k in f.leden}["Cas"] == ["Werpgroep"]
        assert [k.atleet.voornaam for k in f.overigen] == ["Dirk"]                          # niet-actieve niet
        assert oud not in [k.atleet.master_id for k in f.overigen]
        assert groepsbeheer.ledenformulier(db, 9999) is None


def test_opslaan():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        dirk = [a for a in db.atleten() if a.voornaam == "Dirk"][0].master_id
        w = groepsbeheer.leden_opslaan(db, ids["groep"], [ids["anna"], ids["cas"], dirk, dirk, ""])
        assert [a.voornaam for a in w.toegevoegd] == ["Dirk"] and [a.voornaam for a in w.verwijderd] == ["Bram"]
        assert w.tekst == "Atleten gewijzigd: 1 toegevoegd (Dirk Buiten); 1 verwijderd (Bram Test)."
        assert set(db.groep(ids["groep"]).leden) == {ids["anna"], ids["cas"], dirk}
        # De geschiedenis van Bram blijft bewaard.
        assert [a.status for a in db.absenties_van_atleet(ids["bram"])] == ["afwezig", "aanwezig"]
        assert db.groep(ids["werp"]).leden == [ids["cas"]]                                  # andere groep ongemoeid

        w = groepsbeheer.leden_opslaan(db, ids["groep"], [ids["anna"], ids["cas"], dirk])
        assert w.leeg and w.tekst == "Niets gewijzigd."
        w = groepsbeheer.leden_opslaan(db, ids["groep"], [])
        assert len(w.verwijderd) == 3 and db.groep(ids["groep"]).leden == []

        for fout in (["0" * 32], ["kort"]):
            try:
                groepsbeheer.leden_opslaan(db, ids["groep"], fout)
                assert False, "onbekende atleet moet een fout geven"
            except OpslagFout:
                pass
        assert db.groep(ids["groep"]).leden == []                                           # niets half opgeslagen
        try:
            groepsbeheer.leden_opslaan(db, 9999, [])
            assert False
        except OpslagFout:
            pass


def test_seizoen():
    from datetime import date
    assert groepsbeheer.huidig_seizoen(date(2026, 10, 16)) == "2026-2027"
    assert groepsbeheer.huidig_seizoen(date(2027, 3, 1)) == "2026-2027"
    assert groepsbeheer.huidig_seizoen(date(2027, 9, 1)) == "2027-2028"


def test_groep_aanmaken():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        f = groepsbeheer.nieuw_formulier(db, peildatum=VANDAAG)
        assert f.nieuw and f.groep.seizoen == "2026-2027" and not f.leden
        assert [k.atleet.voornaam for k in f.overigen] == ["Dirk", "Cas", "Bram", "Anna"]       # alle actieve
        assert {k.atleet.voornaam: k.andere_groepen for k in f.overigen}["Cas"] == ["U16 sprint", "Werpgroep"]

        g = groepsbeheer.groep_aanmaken(db, "  U16   meisjes ", "2026-2027", [ids["anna"], ids["anna"]])
        assert (g.naam, g.seizoen, db.groep(g.id).leden) == ("U16 meisjes", "2026-2027", [ids["anna"]])
        assert g.id in [x.id for x in db.groepen_van_atleet(ids["anna"])]

        leeg = groepsbeheer.groep_aanmaken(db, "Nog leeg", "", [])
        assert leeg.seizoen is None and db.groep(leeg.id).leden == []

        aantal = len(db.groepen())
        for naam, seizoen, keuze, tekst in [("", "2026-2027", [], "naam"),
                                            ("u16 MEISJES", "2026-2027", [], "al een groep"),
                                            ("x" * 81, None, [], "te lang"),
                                            ("Goed", None, ["0" * 32], "Onbekende atleet")]:
            try:
                groepsbeheer.groep_aanmaken(db, naam, seizoen, keuze)
                assert False, naam
            except OpslagFout as e:
                assert tekst in str(e), (tekst, str(e))
        assert len(db.groepen()) == aantal                                                       # niets aangemaakt
        # Zelfde naam in een ander seizoen mag wel.
        assert groepsbeheer.groep_aanmaken(db, "U16 meisjes", "2027-2028", []).id


def test_trainingsdagen_lezen():
    lees = groepsbeheer.lees_trainingsdagen
    form = {"dag-dinsdag": "1", "tijd-dinsdag": "18:30", "dag-donderdag": "1", "tijd-zaterdag": "9.00",
            "tijd-maandag": "", "dag-zondag": ""}
    assert lees(form) == {"dinsdag": "18:30", "donderdag": None, "zaterdag": "09:00"}   # tijd zonder vinkje telt
    assert lees({}) == {}
    for fout in ("25:00", "18:75", "half zeven"):
        try:
            lees({"dag-dinsdag": "1", "tijd-dinsdag": fout})
            assert False, fout
        except OpslagFout as e:
            assert "begintijd" in str(e)
        assert lees({"dag-dinsdag": "1", "tijd-dinsdag": fout}, streng=False) == {"dinsdag": None}


def test_groep_met_trainingsdagen():
    from groepen import landingspagina
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        g = groepsbeheer.groep_aanmaken(db, "Avondgroep", "2026-2027", [ids["anna"], ids["bram"]],
                                        {"donderdag": "19:00", "dinsdag": "9:15", "zaterdag": None})
        opnieuw = db.groep(g.id)
        assert opnieuw.trainingsdagen == {"dinsdag": "09:15", "donderdag": "19:00", "zaterdag": None}
        assert list(opnieuw.trainingsdagen) == ["dinsdag", "donderdag", "zaterdag"]          # op weekvolgorde

        # Leden wijzigen (groep_opslaan) laat de trainingsdagen staan.
        groepsbeheer.leden_opslaan(db, g.id, [ids["anna"]])
        assert db.groep(g.id).trainingsdagen == opnieuw.trainingsdagen

        # De landingspagina gebruikt de vaste dagen, ook zonder trainingen.
        lp = landingspagina.landingspagina(db, g.id, peildatum=VANDAAG)
        assert lp.dagen_bron == landingspagina.BRON_VAST
        assert [(d.kort, d.starttijd) for d in lp.trainingsdagen] == [("Di", "09:15"), ("Do", "19:00"), ("Za", None)]
        anna = lp.leden[0]                       # Anna traint di, do, za: alle drie met de groep
        assert [d.soort for d in anna.dagen] == [None, "groep", None, "groep", None, "groep", None]
        assert dict((gr.naam, dagen) for gr, dagen in landingspagina.overzicht(db, peildatum=VANDAAG))["Avondgroep"] \
            == ["Di 09:15", "Do 19:00", "Za"]

        # Ongeldige dagen/tijden: niets aangemaakt.
        aantal = len(db.groepen())
        for dagen in ({"feestdag": None}, {"dinsdag": "25:00"}):
            try:
                groepsbeheer.groep_aanmaken(db, "Fout", None, [], dagen)
                assert False
            except OpslagFout:
                pass
        assert len(db.groepen()) == aantal
        # Ook de database zelf weigert een verkeerde dag of tijd.
        for dag, tijd in (("feestdag", None), ("dinsdag", "9:00")):
            try:
                with db.personen:
                    db.personen.execute("INSERT INTO groep_trainingsdag VALUES (?, ?, ?)", (g.id, dag, tijd))
                assert False, (dag, tijd)
            except Exception as e:
                assert "CHECK" in str(e) or "constraint" in str(e).lower()


def test_trainingsdagen_wijzigen():
    from groepen import landingspagina
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        gid = ids["groep"]
        leden = db.groep(gid).leden
        # Zonder vaste dagen: het formulier geeft als hint wat de app nu afleidt.
        f = groepsbeheer.ledenformulier(db, gid, peildatum=VANDAAG)
        assert f.afgeleide_dagen == "Di, Do" and not any(aan for _, _, aan, _ in f.dagen)
        # Alleen leden opslaan (trainingsdagen leeg gelaten) legt geen dagen vast.
        w = groepsbeheer.leden_opslaan(db, gid, leden, {})
        assert w.leeg and w.tekst == "Niets gewijzigd." and db.groep(gid).trainingsdagen == {}

        w = groepsbeheer.leden_opslaan(db, gid, leden, {"donderdag": "19:00", "dinsdag": "18:30"})
        assert w.dagen == {"dinsdag": "18:30", "donderdag": "19:00"} and not w.toegevoegd
        assert w.tekst == "Trainingsdagen nu: Di 18:30, Do 19:00."
        assert db.groep(gid).trainingsdagen == {"dinsdag": "18:30", "donderdag": "19:00"}
        f = groepsbeheer.ledenformulier(db, gid, peildatum=VANDAAG)
        assert f.afgeleide_dagen == "" and [(d, t) for d, _, aan, t in f.dagen if aan] == [
            ("dinsdag", "18:30"), ("donderdag", "19:00")]
        assert landingspagina.landingspagina(db, gid, peildatum=VANDAAG).dagen_bron == landingspagina.BRON_VAST

        # Zelfde dagen nog eens: niets gewijzigd. Leden + dagen tegelijk: één melding.
        assert groepsbeheer.leden_opslaan(db, gid, leden, {"dinsdag": "18:30", "donderdag": "19:00"}).leeg
        w = groepsbeheer.leden_opslaan(db, gid, [ids["anna"]], {"dinsdag": "18:30"})
        assert w.tekst == ("Atleten gewijzigd: 2 verwijderd (Cas Proef, Bram Test). "
                           "Trainingsdagen nu: Di 18:30.")
        # None = dagen niet aanpassen; {} = vaste dagen weghalen.
        groepsbeheer.leden_opslaan(db, gid, [ids["anna"], ids["bram"]])
        assert db.groep(gid).trainingsdagen == {"dinsdag": "18:30"}
        w = groepsbeheer.leden_opslaan(db, gid, [ids["anna"], ids["bram"]], {})
        assert w.tekst == "Geen vaste trainingsdagen meer." and db.groep(gid).trainingsdagen == {}

        # Ongeldige tijd: niets opgeslagen, ook de leden niet.
        try:
            groepsbeheer.leden_opslaan(db, gid, [ids["cas"]], {"dinsdag": "25:00"})
            assert False
        except OpslagFout:
            pass
        assert set(db.groep(gid).leden) == {ids["anna"], ids["bram"]}


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        gid = ids["groep"]
        dirk = [a for a in db.atleten() if a.voornaam == "Dirk"][0].master_id
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        assert f'href="/groep/{gid}/leden"' in c.get(f"/groep/{gid}").get_data(as_text=True)
        html = c.get(f"/groep/{gid}/leden").get_data(as_text=True)
        assert f'value="{ids["anna"]}" id="lid-{ids["anna"]}" checked' in html
        assert f'value="{dirk}" id="lid-{dirk}">' in html
        r = c.post(f"/groep/{gid}/leden", data={"lid": [ids["anna"], dirk]})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/groep/{gid}#kop-dagen")
        tekst = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "1 toegevoegd (Dirk Buiten); 2 verwijderd (Cas Proef, Bram Test)" in tekst
        assert "Dirk Buiten" in tekst
        # Dagen en tijden wijzigen via het formulier.
        html = c.get(f"/groep/{gid}/leden").get_data(as_text=True)
        assert "Groep wijzigen" in html and html.count('type="time"') == 7 and "de app gaat nu uit van" in html
        r = c.post(f"/groep/{gid}/leden", data={"lid": [ids["anna"], dirk], "dag-dinsdag": "1",
                                                "tijd-dinsdag": "18:30", "tijd-donderdag": "19.00"})
        assert r.status_code == 302
        tekst = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Trainingsdagen nu: Di 18:30, Do 19:00." in tekst and "Vaste trainingsdagen van de groep" in tekst
        # Fout in een tijd: alles wat ingevuld was blijft staan, niets opgeslagen.
        r = c.post(f"/groep/{gid}/leden", data={"lid": [ids["anna"]], "dag-woensdag": "1", "tijd-woensdag": "31:00"})
        tekst = r.get_data(as_text=True)
        assert r.status_code == 400 and "Ongeldige begintijd" in tekst
        assert 'id="dag-woensdag" name="dag-woensdag" value="1" checked' in tekst
        assert f'value="{dirk}" id="lid-{dirk}">' in tekst                              # Dirk uitgevinkt gelaten
        assert f'value="{ids["anna"]}" id="lid-{ids["anna"]}" checked' in tekst
        assert db.groep(gid).trainingsdagen == {"dinsdag": "18:30", "donderdag": "19:00"}
        r = c.post(f"/groep/{gid}/leden", data={"lid": ["0" * 32]})
        assert r.status_code == 400 and "Niet opgeslagen" in r.get_data(as_text=True)
        # Nieuwe groep vanaf de pagina Groepen.
        assert 'href="/groepen/nieuw"' in c.get("/groepen").get_data(as_text=True)
        html = c.get("/groepen/nieuw").get_data(as_text=True)
        assert "Nieuwe groep" in html and 'name="naam"' in html and 'name="seizoen"' in html
        r = c.post("/groepen/nieuw", data={"naam": "U16 sprint", "seizoen": "2026-2027", "lid": [ids["anna"]]})
        assert r.status_code == 400 and "al een groep" in r.get_data(as_text=True)
        assert f'value="{ids["anna"]}" id="lid-{ids["anna"]}" checked' in r.get_data(as_text=True)   # keuze blijft staan
        assert 'value="U16 sprint"' in r.get_data(as_text=True)
        r = c.post("/groepen/nieuw", data={"naam": "Werpers", "seizoen": "2026-2027", "lid": [ids["anna"], dirk]})
        assert r.status_code == 302
        tekst = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Groep Werpers aangemaakt met 2 atleten." in tekst and "Anna Voorbeeld" in tekst
        html = c.get("/groepen/nieuw").get_data(as_text=True)
        assert html.count('type="time"') == 7 and 'name="dag-dinsdag"' in html
        r = c.post("/groepen/nieuw", data={"naam": "Ochtend", "dag-dinsdag": "1", "tijd-dinsdag": "7:30",
                                           "tijd-vrijdag": "99:99", "lid": [dirk]})
        tekst = r.get_data(as_text=True)
        assert r.status_code == 400 and "Ongeldige begintijd" in tekst
        assert 'id="dag-dinsdag" name="dag-dinsdag" value="1" checked' in tekst and 'value="07:30"' in tekst  # blijft staan
        r = c.post("/groepen/nieuw", data={"naam": "Ochtend", "dag-dinsdag": "1", "tijd-dinsdag": "7:30", "lid": [dirk]})
        tekst = c.get(r.headers["Location"]).get_data(as_text=True)
        assert r.status_code == 302 and "Vaste trainingsdagen van de groep" in tekst and "07:30" in tekst
        assert "Di 07:30" in c.get("/groepen").get_data(as_text=True)
        r = c.post("/groepen/nieuw", data={"naam": "", "lid": ["0" * 32]})
        assert r.status_code == 400 and "Geef de groep een naam" in r.get_data(as_text=True)
        assert c.get("/groep/9999/leden").status_code == 404
        assert c.post("/groep/9999/leden", data={}).status_code == 404


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
