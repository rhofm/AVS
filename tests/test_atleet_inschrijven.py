"""Tests voor '+ Inschrijven' op de wedstrijdplanning van een atleet: een komende wedstrijd
kiezen (wedstrijden.detail.wedstrijdkeuze, /atleet/<id>/inschrijven) of een nieuwe maken,
dan het inschrijfformulier met die atleet al aangevinkt, en terug naar zijn planning.

Alleen nepgegevens en een vaste testsleutel; niets van internet.
"""

from datetime import date, timedelta

from hulp import app_client
from test_wedstrijdpagina import DAG, opslag

from wedstrijden import detail, planning

# Uit test_wedstrijdpagina.opslag(): 'Clubkampioenschappen' over 8 dagen met tijdschema;
# Anna (U16V) staat ingeschreven voor 100m en Verspringen, Bram (U16M) ook, Cees (U12M) niet.


def _extra(db):
    los = planning.plan_wedstrijd(db, "Indoor Cup", date.today() + timedelta(days=40), "Apeldoorn", indoor=True)
    planning.plan_wedstrijd(db, "Vorig jaar", date.today() - timedelta(days=30))
    vandaag = planning.plan_wedstrijd(db, "Avondwedstrijd", date.today())
    return los, vandaag


def test_wedstrijdkeuze():
    with opslag() as (db, _, ids):
        los, vandaag = _extra(db)
        planning.inschrijven(db, los.id, ids["cees"])                          # gaat mee, onderdelen volgen
        k = detail.wedstrijdkeuze(db, ids["anna"])
        assert k.atleet.voornaam == "Anna" and k.categorie
        assert [r.wedstrijd.naam for r in k.wedstrijden] == ["Avondwedstrijd", "Clubkampioenschappen", "Indoor Cup"]
        club = k.wedstrijden[1]
        assert club.ingeschreven and club.onderdelen == ["100m", "Verspringen"] and club.heeft_tijdschema
        assert not k.wedstrijden[2].ingeschreven and not k.wedstrijden[2].heeft_tijdschema
        assert k.wedstrijden[0].dagen_tot == 0 and "apeldoorn" in k.wedstrijden[2].zoektekst
        cees = detail.wedstrijdkeuze(db, ids["cees"])
        indoor = next(r for r in cees.wedstrijden if r.wedstrijd.id == los.id)
        assert indoor.ingeschreven and indoor.onderdelen == []
        assert detail.wedstrijdkeuze(db, "0" * 32) is None


def test_knop_en_keuzepagina():
    with opslag() as (db, tmp, ids):
        los, _ = _extra(db)
        c = app_client(tmp)
        html = c.get(f"/atleet/{ids['cees']}/wedstrijden").get_data(as_text=True)
        assert f'href="/atleet/{ids["cees"]}/inschrijven">+ Inschrijven</a>' in html
        r = c.get(f"/atleet/{ids['cees']}/inschrijven")
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "Deze pagina komt nog" not in html
        assert "Clubkampioenschappen" in html and "Indoor Cup" in html and "Vorig jaar" not in html
        assert f'href="/wedstrijd/{los.id}/inschrijven?atleet={ids["cees"]}"' in html
        assert f'href="/wedstrijden/nieuw?atleet={ids["cees"]}">+ Nieuwe wedstrijd</a>' in html
        assert "nog geen tijdschema" in html and "filter.js" in html
        # Anna staat al bij de clubkampioenschappen: knop om onderdelen toe te voegen.
        assert "Onderdelen toevoegen" in c.get(f"/atleet/{ids['anna']}/inschrijven").get_data(as_text=True)
        assert c.get(f"/atleet/{'0' * 32}/inschrijven").status_code == 404


def test_inschrijven_vanaf_atleet():
    with opslag() as (db, tmp, ids):
        c = app_client(tmp)
        url = f"/wedstrijd/{ids['w']}/inschrijven?atleet={ids['cees']}"
        html = c.get(url).get_data(as_text=True)
        assert f'name="atleet" value="{ids["cees"]}" id="atl-{ids["cees"]}" checked' in html     # al aangevinkt
        assert f'name="atleet" value="{ids["bram"]}" id="atl-{ids["bram"]}">' in html            # anderen niet
        assert f'name="van_atleet" value="{ids["cees"]}"' in html
        assert "Andere wedstrijd kiezen voor Cees Nep" in html
        assert f'href="/atleet/{ids["cees"]}/wedstrijden">Annuleren</a>' in html
        # Opslaan: terug naar de planning van de atleet, met melding.
        r = c.post(f"/wedstrijd/{ids['w']}/inschrijven",
                   data={"van_atleet": ids["cees"], "atleet": [ids["cees"]], "onderdeel": [ids["kogel"]]})
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/atleet/{ids['cees']}/wedstrijden#w-{ids['w']}")
        html = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "1 atleet ingeschreven voor Kogelstoten." in html and "Clubkampioenschappen" in html
        # Zonder atleet (of met een onbekende) werkt alles zoals voorheen.
        html = c.get(f"/wedstrijd/{ids['w']}/inschrijven?atleet=onzin").get_data(as_text=True)
        assert 'name="van_atleet"' not in html and " checked" not in html.split('id="tabel-atleten"')[1]


def test_nieuwe_wedstrijd_vanaf_atleet():
    with opslag() as (db, tmp, ids):
        c = app_client(tmp)
        html = c.get(f"/wedstrijden/nieuw?atleet={ids['cees']}").get_data(as_text=True)
        assert html.count(f'name="van_atleet" value="{ids["cees"]}"') == 2            # in beide formulieren
        assert "Inschrijven Cees Nep" in html and "Daarna schrijf je Cees in." in html
        r = c.post("/wedstrijden/nieuw", data={"soort": "hand", "van_atleet": ids["cees"], "naam": "Pupillendag",
                                               "datum": (DAG + timedelta(days=20)).isoformat(), "locatie": ""})
        w = next(x for x in db.wedstrijden() if x.naam == "Pupillendag")
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/wedstrijd/{w.id}/inschrijven?atleet={ids['cees']}")
        html = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Wedstrijd Pupillendag aangemaakt" in html and f'id="atl-{ids["cees"]}" checked' in html
        # Fout in het formulier: de atleet blijft onthouden.
        r = c.post("/wedstrijden/nieuw", data={"soort": "hand", "van_atleet": ids["cees"], "naam": "X", "datum": ""})
        assert r.status_code == 400 and f'name="van_atleet" value="{ids["cees"]}"' in r.get_data(as_text=True)
