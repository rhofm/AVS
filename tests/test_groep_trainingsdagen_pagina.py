"""Tests voor de pagina 'Trainingsdagen wijzigen' van een groep (/groep/<id>/trainingsdagen),
groepen.groep.trainingsdagen_opslaan() en de gedeelde dag/tijd-keuze (_tijdkeuze.html).

Gebruikt de nepgroep uit test_groep_landingspagina (alleen nepgegevens, testsleutel).
Werkt met pytest en los: `python tests/test_groep_trainingsdagen_pagina.py`.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_groep_landingspagina import TESTSLEUTEL, opslag, voorbeeldgroep  # noqa: E402

from db.queries import OpslagFout  # noqa: E402
from groepen import groep as groepsbeheer  # noqa: E402

UI = Path(__file__).resolve().parents[1] / "src" / "ui"


def test_trainingsdagen_opslaan():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)
        gid = ids["groep"]
        leden = sorted(db.groep(gid).leden)
        w = groepsbeheer.trainingsdagen_opslaan(db, gid, {"dinsdag": "18:30", "zaterdag": "9:00"})
        assert w.dagen == {"dinsdag": "18:30", "zaterdag": "09:00"} and not w.toegevoegd and not w.verwijderd
        assert db.groep(gid).trainingsdagen == {"dinsdag": "18:30", "zaterdag": "09:00"}
        assert sorted(db.groep(gid).leden) == leden                                       # leden ongemoeid
        # Zaterdag is nieuw: aangevuld in de schema's van wie hem nog niet had (Bram en Cas; Anna al wel).
        assert sorted(a.voornaam for a in w.schema_aangevuld) == ["Bram", "Cas"]
        assert "zaterdag" in db.trainingsschema(ids["bram"]).dagen

        assert groepsbeheer.trainingsdagen_opslaan(db, gid, {"dinsdag": "18:30", "zaterdag": "09:00"}).leeg
        w = groepsbeheer.trainingsdagen_opslaan(db, gid, {})
        assert w.tekst == "Geen vaste trainingsdagen meer." and db.groep(gid).trainingsdagen == {}
        assert "zaterdag" in db.trainingsschema(ids["bram"]).dagen                         # schema blijft staan

        for fout in ({"dinsdag": "25:00"}, {"feestdag": "18:00"}):
            try:
                groepsbeheer.trainingsdagen_opslaan(db, gid, fout)
                assert False, fout
            except OpslagFout:
                pass
        try:
            groepsbeheer.trainingsdagen_opslaan(db, 9999, {})
            assert False
        except OpslagFout:
            pass


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        gid = ids["groep"]
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        # Knop 'Wijzigen' bij de trainingsdagen op de landingspagina.
        assert f'href="/groep/{gid}/trainingsdagen"' in c.get(f"/groep/{gid}").get_data(as_text=True)

        html = c.get(f"/groep/{gid}/trainingsdagen").get_data(as_text=True)
        assert "Trainingsdagen wijzigen" in html and html.count('type="time"') == 7
        assert 'class="tijdkeuze"' in html and "dagkeuze" not in html
        assert "de app gaat nu uit van Di, Do" in html                                    # nog geen vaste dagen

        r = c.post(f"/groep/{gid}/trainingsdagen", data={"dag-dinsdag": "1", "tijd-dinsdag": "18:30",
                                                          "tijd-zaterdag": "9.00", "lid": ["genegeerd"]})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/groep/{gid}#kop-dagen")
        tekst = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Trainingsdagen nu: Di 18:30u, Za 09:00u." in tekst and "Trainingsschema aangevuld voor 2 atleten." in tekst
        assert "Vaste trainingsdagen van de groep" in tekst and "09:00" in tekst
        assert len(db.groep(gid).leden) == 3                                              # leden niet aangeraakt

        # Opnieuw openen: ingevuld met de opgeslagen tijden.
        html = c.get(f"/groep/{gid}/trainingsdagen").get_data(as_text=True)
        assert 'id="dag-dinsdag" name="dag-dinsdag" value="1" checked' in html and 'value="18:30"' in html
        assert "de app gaat nu uit van" not in html

        # Fout: niets opgeslagen, ingevulde waarden blijven staan.
        r = c.post(f"/groep/{gid}/trainingsdagen", data={"dag-woensdag": "1", "tijd-woensdag": "31:00",
                                                          "tijd-vrijdag": "17:15"})
        tekst = r.get_data(as_text=True)
        assert r.status_code == 400 and "Niet opgeslagen" in tekst
        assert 'id="dag-woensdag" name="dag-woensdag" value="1" checked' in tekst and 'value="17:15"' in tekst
        assert db.groep(gid).trainingsdagen == {"dinsdag": "18:30", "zaterdag": "09:00"}

        assert c.get("/groep/9999/trainingsdagen").status_code == 404
        assert c.post("/groep/9999/trainingsdagen", data={}).status_code == 404

        # Nieuwe groep en Groep wijzigen gebruiken dezelfde keuze.
        for pad in ("/groepen/nieuw", f"/groep/{gid}/leden"):
            html = c.get(pad).get_data(as_text=True)
            assert 'class="tijdkeuze"' in html and html.count('type="time"') == 7, pad


def test_geen_botsende_klassen():
    """De groepskeuze mag geen klassen delen met .dagkeuze van het trainingsschema van een atleet:
    die regel verbergt alle inputs in .dagkeuze__dag, waardoor de tijdvelden over de dagknoppen vielen."""
    for naam in ("_tijdkeuze.html", "groep_leden.html", "groep_trainingsdagen.html"):
        tekst = (UI / "templates" / naam).read_text(encoding="utf-8")
        assert 'class="dagkeuze' not in tekst and '".dagkeuze' not in tekst, naam          # niet als klasse/selector
    css = (UI / "static" / "avs.css").read_text(encoding="utf-8")
    assert re.search(r"\.dagkeuze__dag input \{[^}]*position: absolute", css)        # athlete-pagina: zo bedoeld
    assert not re.search(r"\.tijdkeuze__dag input(\[type=\"time\"\])? \{[^}]*position: absolute", css)


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
