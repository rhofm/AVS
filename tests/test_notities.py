"""Tests voor src/atleten/notities.py en de notitiepagina's.

Alleen nepgegevens en een vaste testsleutel.
"""

from datetime import date, timedelta

from test_app import client
from test_landingspagina import VANDAAG, opslag, voorbeeld

from atleten import beheer, notities
from db.queries import Opslag, OpslagFout
from hulp import TESTSLEUTEL, tekst, verwacht as _verwacht


def test_beheer():
    with opslag() as db:
        mid = voorbeeld(db)                                   # 7 notities, VANDAAG t/m 6 dagen terug
        np = notities.notitiespagina(db, mid, peildatum=VANDAAG)
        assert np.totaal == 7 and np.aantal == 7 and [m.naam for m in np.maanden] == ["oktober 2026"]
        n = notities.toevoegen(db, mid, date(2026, 9, 3), "  Goede 60m  ")
        assert n.inhoud == "Goede 60m"
        np = notities.notitiespagina(db, mid, peildatum=VANDAAG)
        assert [m.naam for m in np.maanden] == ["oktober 2026", "september 2026"]
        zoek = notities.notitiespagina(db, mid, zoek="60M")
        assert zoek.aantal == 1 and zoek.totaal == 8

        n2 = notities.bijwerken(db, mid, n.id, date(2026, 9, 4), "Goede 60m, mooie start")
        assert n2.datum == date(2026, 9, 4) and n2.bijgewerkt_op is not None
        assert notities.bijwerken(db, mid, n.id, date(2026, 9, 4), "Goede 60m, mooie start").inhoud == n2.inhoud

        _verwacht(OpslagFout, lambda: notities.toevoegen(db, mid, VANDAAG, "   "))
        _verwacht(OpslagFout, lambda: notities.bijwerken(db, mid, n.id, VANDAAG, ""))
        _verwacht(OpslagFout, lambda: notities.lees_datum("gisteren"))
        _verwacht(OpslagFout, lambda: notities.lees_datum((date.today() + timedelta(days=1)).isoformat()))
        assert notities.lees_datum("2026-10-01") == date(2026, 10, 1)

        # Een notitie van een andere atleet is niet via deze atleet aan te passen of te verwijderen.
        bas = beheer.nieuwe_atleet(db, "Bas", "Proef").master_id
        _verwacht(OpslagFout, lambda: notities.bijwerken(db, bas, n.id, VANDAAG, "x"))
        _verwacht(OpslagFout, lambda: notities.verwijderen(db, bas, n.id))
        assert notities.haal_notitie(db, bas, n.id) is None

        assert notities.verwijderen(db, mid, n.id).id == n.id
        assert db.notitie(n.id) is None
        assert notities.notitiespagina(db, "0" * 32) is None


def test_paginas():
    with client() as (c, mid, tmp):
        assert c.get(f"/atleet/{mid}/notities").status_code == 200
        r = c.get(f"/atleet/{mid}/notities/nieuw")
        assert r.status_code == 200 and "autofocus" in tekst(r)

        r = c.post(f"/atleet/{mid}/notities", data={"datum": "2026-10-02", "inhoud": "Blokstart <b>beter</b>"})
        assert r.status_code == 302
        r = c.get(r.headers["Location"])
        assert "Notitie van 02-10-2026 opgeslagen." in tekst(r)
        assert "Blokstart &lt;b&gt;beter&lt;/b&gt;" in tekst(r)            # tekst wordt nooit als HTML getoond

        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            nid = [n for n in db.notities(mid) if "Blokstart" in n.inhoud][0].id
        assert "Blokstart" in tekst(c.get(f"/atleet/{mid}/notities?zoek=blokstart"))
        assert "Blokstart" not in tekst(c.get(f"/atleet/{mid}/notities?zoek=zzz"))

        # Fout: tekst blijft staan, niets opgeslagen.
        r = c.post(f"/atleet/{mid}/notities", data={"datum": "2999-01-01", "inhoud": "Toekomst"})
        assert r.status_code == 400 and "toekomst" in tekst(r) and ">Toekomst</textarea>" in tekst(r)

        r = c.get(f"/atleet/{mid}/notities/{nid}")
        assert r.status_code == 200 and "Notitie bewerken" in tekst(r)
        r = c.post(f"/atleet/{mid}/notities/{nid}", data={"actie": "opslaan", "datum": "2026-10-03", "inhoud": "Aangepast"},
                   follow_redirects=True)
        assert "Notitie opgeslagen." in tekst(r) and "Aangepast" in tekst(r)

        r = c.post(f"/atleet/{mid}/notities/{nid}", data={"actie": "verwijderen"})
        assert r.status_code == 400 and "Vink eerst aan" in tekst(r)
        r = c.post(f"/atleet/{mid}/notities/{nid}", data={"actie": "verwijderen", "zeker": "1"}, follow_redirects=True)
        assert "Notitie van 03-10-2026 verwijderd." in tekst(r)
        assert c.get(f"/atleet/{mid}/notities/{nid}").status_code == 404
        assert c.get("/atleet/" + "0" * 32 + "/notities").status_code == 404
