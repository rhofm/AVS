"""Tests voor stap 4: csv voor atletiek.nu (ploeg/export.py) en de ploeg op de
wedstrijdpagina (ploeg/inschrijven.py: inschrijvingen in prestaties.db).

Alleen nep-atleten en een vaste testsleutel.
"""

import csv
import io

from test_ploegen import BESTAND, DAG, opslag

from db.queries import Opslag
from models import Inzet, Onderdeel, Ploeg, PloegLid, Wedstrijd
from ploeg import export, paginas
from wedstrijden import planning
from hulp import TESTSLEUTEL, app_client


class Form(dict):
    def getlist(self, k):
        v = self.get(k, [])
        return v if isinstance(v, list) else [v]


def _ploeg(db, wedstrijd_id=None) -> Ploeg:
    return paginas.ploeg_opslaan(db, Ploeg("U16 meisjes A", BESTAND, "U16-V", "wedstrijd_1", DAG,
                                           wedstrijd_id=wedstrijd_id, competitie="U14/U16-competitie"))


def _lezen(e) -> list[list[str]]:
    tekst = e.inhoud.decode("utf-8")
    assert tekst.startswith("﻿")
    return list(csv.reader(io.StringIO(tekst[1:]), delimiter=";"))


def _inschrijvingen(db, wid) -> set[tuple[str, str | None]]:
    namen = {o.id: o.naam for o in db.onderdelen()}
    return {(i.atleet_id, namen.get(i.onderdeel_id)) for i in db.deelnemers(wid)}


# ------------------------------------------------------------
# Csv
# ------------------------------------------------------------
def test_csv_voor_atletieknu():
    with opslag() as (db, _, ids):
        anna = db.atleet(ids["anna"])
        anna.au_licentienummer, anna.club = "1234567", "AV Proef"
        db.atleet_opslaan(anna)
        p = _ploeg(db)
        db.ploeg_opstelling_opslaan(p.id, [PloegLid(ids["bo"]), PloegLid(ids["anna"]), PloegLid(ids["cato"], "reserve")],
                                    [Inzet(ids["anna"], "80m"), Inzet(ids["anna"], "800m"), Inzet(ids["bo"], "80mH"),
                                     Inzet(ids["anna"], "4x80m")])
        e = export.atletieknu_csv(db, p.id)
        assert e.bestandsnaam == f"ploeg_u16_meisjes_a_{DAG.isoformat()}.csv" and e.atleten == 3
        rijen = _lezen(e)
        kop = rijen[0]
        assert kop[:7] == export.KOPPEN
        assert kop[7:11] == ["80 meter", "800 meter", "80 meter horden", "4 x 80 meter"]
        per_naam = {r[1]: dict(zip(kop, r)) for r in rijen[1:]}
        assert [r[1] for r in rijen[1:]] == ["Anna Proef", "Bo Proef", "Cato Proef"]     # reserves achteraan
        a = per_naam["Anna Proef"]
        assert (a["AU nummer"], a["Geslacht"], a["Geboortedatum"], a["Vereniging"]) == (
            "1234567", "V", f"01-03-{DAG.year - 15}", "AV Proef")
        assert (a["Categorie"], a["Team"]) == ("U16-V", "U16 meisjes A")
        assert a["80 meter"] == "10,60"                     # prestatie die AVS gebruikt
        assert a["800 meter"] == "x"                        # opgesteld, geen prestatie
        assert a["4 x 80 meter"] == "x" and a["Verspringen"] == ""
        assert per_naam["Bo Proef"]["80 meter horden"] == "12,80"
        assert per_naam["Cato Proef"]["Geboortedatum"] == str(DAG.year - 13)          # alleen geboortejaar
        assert all(v == "" for k, v in per_naam["Cato Proef"].items() if k not in export.KOPPEN)
        assert export.atletieknu_csv(db, 999) is None


def test_csv_route():
    with opslag() as (db, tmp, ids):
        p = _ploeg(db)
        db.ploeg_opstelling_opslaan(p.id, [PloegLid(ids["anna"])], [Inzet(ids["anna"], "80m")])
        db.sluit()
        c = app_client(tmp)
        r = c.get(f"/ploeg/{p.id}/atletieknu.csv")
        assert r.status_code == 200 and r.mimetype == "text/csv"
        assert r.headers["Content-Disposition"].startswith("attachment;") and r.headers["Cache-Control"] == "no-store"
        assert "Anna Proef" in r.get_data(as_text=True)
        assert c.get("/ploeg/999/atletieknu.csv").status_code == 404
        assert f'href="/ploeg/{p.id}/atletieknu.csv"' in c.get(f"/ploeg/{p.id}").get_data(as_text=True)


# ------------------------------------------------------------
# Inschrijvingen op de gekoppelde wedstrijd
# ------------------------------------------------------------
def test_opslaan_schrijft_in_voor_de_wedstrijd():
    with opslag() as (db, _, ids):
        w = db.wedstrijd_opslaan(Wedstrijd("Competitie 1", DAG))
        p = _ploeg(db, w.id)
        a, b, c = ids["anna"], ids["bo"], ids["cato"]
        # de trainer had Anna zelf al ingeschreven voor de 150 m (staat niet in de ploeg)
        db.onderdeel_opslaan(Onderdeel("150 meter", "tijd", True))
        planning.inschrijven(db, w.id, a, ["150 meter"])

        form = Form({"inzet": [f"{a}|80m", f"{b}|80mH", f"{a}|4x80m"], f"rol-{c}": "reserve"})
        _, wijz = paginas.opstelling_opslaan(db, p.id, form)
        assert _inschrijvingen(db, w.id) == {(a, "150 meter"), (a, "80 meter"), (a, "4 x 80 meter"),
                                             (b, "80 meter horden 76,2cm"), (c, None)}
        assert wijz.ingeschreven == 4 and wijz.afgemeld == 0
        assert db.onderdeel("4 x 80 meter") is not None        # bestond nog niet: aangemaakt

        # Anna van de 80 m af, Bo uit de ploeg, Cato krijgt een onderdeel
        form = Form({"inzet": [f"{a}|4x80m", f"{c}|kogelstoten"]})
        _, wijz = paginas.opstelling_opslaan(db, p.id, form)
        assert _inschrijvingen(db, w.id) == {(a, "150 meter"), (a, "4 x 80 meter"), (c, "Kogelstoten 3kg")}
        assert wijz.afgemeld == 2                              # Anna 80 m, Bo 80 m horden

        # opnieuw opslaan zonder wijziging: niets verandert
        _, wijz = paginas.opstelling_opslaan(db, p.id, form)
        assert not wijz.iets


def test_andere_wedstrijd_en_verwijderen():
    with opslag() as (db, _, ids):
        w1 = db.wedstrijd_opslaan(Wedstrijd("Competitie 1", DAG))
        w2 = db.wedstrijd_opslaan(Wedstrijd("Competitie 1 (verzet)", DAG))
        p = _ploeg(db, w1.id)
        paginas.opstelling_opslaan(db, p.id, Form({"inzet": [f"{ids['anna']}|80m"]}))
        assert _inschrijvingen(db, w1.id) == {(ids["anna"], "80 meter")}

        p.wedstrijd_id = w2.id                                  # 'Gegevens wijzigen': andere wedstrijd
        paginas.ploeg_opslaan(db, p)
        assert _inschrijvingen(db, w1.id) == set() and _inschrijvingen(db, w2.id) == {(ids["anna"], "80 meter")}

        paginas.ploeg_verwijderen(db, p.id)
        assert db.ploeg(p.id) is None and _inschrijvingen(db, w2.id) == set()


def test_zonder_wedstrijd_geen_inschrijvingen():
    with opslag() as (db, _, ids):
        p = _ploeg(db)
        _, wijz = paginas.opstelling_opslaan(db, p.id, Form({"inzet": [f"{ids['anna']}|80m"]}))
        assert not wijz.iets


def test_pagina_meldt_wedstrijd_bijgewerkt():
    with opslag() as (db, tmp, ids):
        w = db.wedstrijd_opslaan(Wedstrijd("Competitie 1", DAG))
        p = _ploeg(db, w.id)
        db.sluit()
        c = app_client(tmp)
        html = c.post(f"/ploeg/{p.id}", data={"inzet": [f"{ids['anna']}|80m"]}).get_data(as_text=True)
        assert "Wedstrijd Competitie 1 bijgewerkt: 1 ingeschreven, 0 afgemeld." in html
        assert "Opslaan zet de ploeg ook op de wedstrijdpagina" in html
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db2:
            assert len(db2.deelnemers(w.id)) == 1
