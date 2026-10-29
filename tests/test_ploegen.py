"""Tests voor ploegen (stap 3): tabellen ploeg/ploeg_lid/ploeg_opstelling, Opslag.ploeg*, de matrix
(ploeg/vergelijk.py), punten en controle van een opstelling (ploeg/opstelling.py)
en de pagina's /ploegen, /ploegen/nieuw, /ploeg/<id>.

Alleen nep-atleten en een vaste testsleutel.
"""

import contextlib
import io
import tempfile
from datetime import date
from pathlib import Path

from atleten import beheer
from db.init_db import init_db, verbind
from db.queries import Opslag, OpslagFout
from models import Inzet, Onderdeel, Ploeg, PloegLid, Prestatie, Wedstrijd
from ploeg import opstelling, regels, vergelijk
from ploeg.paginas import programma_label
from ui.app import maak_app
from hulp import TESTSLEUTEL, lege_opslag, verwacht as _verwacht

DAG = date(2027, 5, 15)            # wedstrijddag (zaterdag)
JAAR = DAG.year
BESTAND = "u14_u16_2026-2027"


@contextlib.contextmanager
def opslag():
    """(Opslag, map, ids). Atleten op de wedstrijddag: anna U16-V, bo U16-V, cato U14-V, dirk U16-M."""
    with lege_opslag() as (db, tmp):
        ids = {
            "anna": beheer.nieuwe_atleet(db, "Anna", "Proef", geslacht="V", geboortedatum=f"{JAAR - 15}-03-01"),
            "bo": beheer.nieuwe_atleet(db, "Bo", "Proef", geslacht="V", geboortedatum=f"{JAAR - 14}-06-01"),
            "cato": beheer.nieuwe_atleet(db, "Cato", "Proef", geslacht="V", geboortedatum=f"{JAAR - 13}"),
            "dirk": beheer.nieuwe_atleet(db, "Dirk", "Proef", geslacht="M", geboortedatum=f"{JAAR - 15}"),
        }
        ids = {k: a.master_id for k, a in ids.items()}
        o = {n: db.onderdeel_opslaan(Onderdeel(n, e, e == "tijd")) for n, e in (
            ("80 meter", "tijd"), ("80 meter Handtijd", "tijd"), ("800 meter", "tijd"),
            ("80 meter horden 76,2cm", "tijd"), ("Verspringen", "afstand"), ("Hoogspringen", "hoogte"),
            ("Kogelstoten 3kg", "afstand"), ("Kogelstoten 2kg", "afstand"), ("Discuswerpen 1kg", "afstand"))}

        def pr(wie, onderdeel, waarde, datum, wind=None):
            db.prestatie_opslaan(Prestatie(onderdeel, datum, waarde, atleet_id=ids[wie],
                                           onderdeel_id=o[onderdeel].id, wind=wind))

        pr("anna", "80 meter", 10.60, date(JAAR, 4, 20), wind=1.0)
        pr("anna", "80 meter", 10.20, date(JAAR, 4, 21), wind=3.1)       # te veel rugwind: telt niet
        pr("anna", "80 meter", 10.10, date(JAAR - 3, 6, 1), wind=0.0)    # te oud voor 'seizoen', wel PR
        pr("anna", "Verspringen", 5.10, date(JAAR - 1, 7, 1), wind=0.5)
        pr("bo", "80 meter", 10.90, date(JAAR, 4, 20), wind=0.0)
        pr("bo", "80 meter horden 76,2cm", 12.80, date(JAAR, 4, 20), wind=1.5)
        pr("cato", "80 meter Handtijd", 10.80, date(JAAR, 4, 20))        # handtijd: +0,24
        pr("cato", "Kogelstoten 2kg", 9.80, date(JAAR, 4, 20))           # U14-materiaal: hint
        pr("bo", "Kogelstoten 3kg", 10.50, date(JAAR, 5, 20))            # na de wedstrijddag: telt niet
        pr("anna", "Kogelstoten 3kg", 9.00, date(JAAR, 4, 1))
        yield db, Path(tmp), ids


def _ploeg(db, naam="U16 meisjes A", **kw) -> Ploeg:
    return db.ploeg_opslaan(Ploeg(naam, BESTAND, "U16-V", "wedstrijd_1", DAG, competitie="U14/U16-competitie", **kw))


def _matrix(db, ids, basis="seizoen"):
    rs = regels.laad(BESTAND)
    return vergelijk.matrix(db, rs, "U16-V", "wedstrijd_1", DAG,
                            [db.atleet(ids[k]) for k in ("anna", "bo", "cato")], basis)


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------
def test_ploeg_zonder_datum_wordt_overgeslagen():
    """ploeg.datum mag leeg zijn (zo stond het in oudere databases); het overzicht slaat die over."""
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with contextlib.closing(verbind("personen", Path(tmp), TESTSLEUTEL)) as c, c:
            c.execute("INSERT INTO ploeg (id, naam) VALUES (1, 'Zonder datum')")
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            assert db.ploegen() == []


def test_ploeg_opslaan_en_lezen():
    with opslag() as (db, _, ids):
        w = db.wedstrijd_opslaan(Wedstrijd("Competitie 1", DAG))
        p = _ploeg(db, wedstrijd_id=w.id)
        assert db.ploeg(p.id).naam == "U16 meisjes A" and db.ploeg(p.id).prestatiebasis == "seizoen"
        leden = [PloegLid(ids["bo"]), PloegLid(ids["anna"]), PloegLid(ids["cato"], "reserve")]
        db.ploeg_opstelling_opslaan(p.id, leden, [Inzet(ids["anna"], "80m"), Inzet(ids["bo"], "80m")])
        assert [lid.atleet_id for lid in db.ploeg_leden(p.id)] == [ids["anna"], ids["bo"], ids["cato"]]   # op naam
        assert {i.atleet_id for i in db.ploeg_inzet(p.id)} == {ids["anna"], ids["bo"]}
        assert [x.id for x in db.ploegen(DAG)] == [p.id] and db.ploegen(date(2020, 1, 1)) == []

        _verwacht(OpslagFout, lambda: db.ploeg_opstelling_opslaan(p.id, leden, [Inzet(ids["dirk"], "80m")]))
        _verwacht(OpslagFout, lambda: db.ploeg_opstelling_opslaan(p.id, leden + [PloegLid(ids["bo"])], []))
        _verwacht(OpslagFout, lambda: db.ploeg_opslaan(Ploeg("X", BESTAND, "U16-V", "wedstrijd_1", DAG,
                                                             wedstrijd_id=999)))
        # wedstrijd weg: ploeg blijft, met zijn eigen datum
        db.wedstrijd_verwijderen(w.id)
        assert db.ploeg(p.id).wedstrijd_id is None and db.ploeg(p.id).datum == DAG
        # atleet weg (AVG): ook uit de ploeg en de opstelling
        db.atleet_verwijderen(ids["anna"])
        assert ids["anna"] not in {lid.atleet_id for lid in db.ploeg_leden(p.id)}
        assert {i.atleet_id for i in db.ploeg_inzet(p.id)} == {ids["bo"]}
        db.ploeg_verwijderen(p.id)
        assert db.ploeg(p.id) is None


def test_ploeg_model():
    _verwacht(ValueError, lambda: Ploeg(" ", BESTAND, "U16-V", "wedstrijd_1", DAG))
    _verwacht(ValueError, lambda: Ploeg("A", BESTAND, "U16-V", "wedstrijd_1", "2027-05-15"))
    _verwacht(ValueError, lambda: Ploeg("A", BESTAND, "U16-V", "wedstrijd_1", DAG, prestatiebasis="ooit"))


# ------------------------------------------------------------
# Matrix
# ------------------------------------------------------------
def test_matrix_beste_prestatie_en_punten():
    with opslag() as (db, _, ids):
        m = _matrix(db, ids)
        assert [r.sleutel for r in m.regels][:3] == ["80m", "800m", "80mH"]
        anna = m.cel(ids["anna"], "80m")
        assert anna.waarde == 10.60                          # 10,20 had te veel wind; 10,10 is te oud
        assert anna.punten == int(19933.0 / 10.60 - 1193)    # tabel U14/U16
        assert m.cel(ids["anna"], "verspringen").waarde == 5.10      # vorig seizoen telt mee
        assert m.cel(ids["bo"], "80mH").onderdeel_naam == "80 meter horden 76,2cm"
        assert m.cel(ids["bo"], "80mH").punten > 0
        assert m.cel(ids["bo"], "kogelstoten").waarde is None        # na de wedstrijddag
        assert m.rij(ids["cato"]).categorie == "U14-V" and m.rij(ids["cato"]).toegestaan


def test_matrix_handtijd_en_ander_materiaal():
    with opslag() as (db, _, ids):
        m = _matrix(db, ids)
        cato = m.cel(ids["cato"], "80m")
        assert cato.handtijd and cato.waarde == 10.80
        assert cato.punten == int(19933.0 / (10.80 + 0.24) - 1193)
        assert "hand" in cato.tekst
        kogel = m.cel(ids["cato"], "kogelstoten")             # U14 in de U16-ploeg: 3 kg nodig
        assert kogel.onderdeel_naam == "Kogelstoten 3kg" and kogel.datum is None
        assert kogel.hint == "2kg: 9,80 m"
        # geen 3 kg-prestatie: voorspeld uit de 2 kg (9,80 x 0.87 = 8,53 m; punten x 0.95), zie test_voorspeller
        assert kogel.voorspeld and kogel.bron == "voorspeld uit Kogelstoten 2kg: 9,80 m" and kogel.waarde < 8.53
        estafette = m.cel(ids["cato"], "4x80m")
        assert estafette.waarde is None and estafette.hint is None
        assert estafette.beentijd == "11,04"                     # handtijd 10,80 + 0,24


def test_matrix_prestatiebasis():
    with opslag() as (db, _, ids):
        assert _matrix(db, ids, "pr").cel(ids["anna"], "80m").waarde == 10.10
        twaalf = _matrix(db, ids, "12mnd")
        assert twaalf.cel(ids["anna"], "80m").waarde == 10.60                # de PR van 3 jaar terug telt niet
        assert twaalf.cel(ids["anna"], "verspringen").waarde == 5.10         # juli vorig jaar: binnen 12 mnd
        _verwacht(ValueError, lambda: _matrix(db, ids, "ooit"))
    assert vergelijk.normaliseer("80 Meter Horden 76,20 cm") == "80meterhorden76.2cm"
    assert vergelijk.normaliseer("Kogelstoten 3,00kg") == "kogelstoten3kg"


# ------------------------------------------------------------
# Opstelling: punten en controle
# ------------------------------------------------------------
def test_stand_beste_twee_tellen_bij_lopen():
    with opslag() as (db, _, ids):
        m = _matrix(db, ids)
        inzet = [Inzet(ids[k], "80m") for k in ("anna", "bo", "cato")] + [Inzet(ids["anna"], "verspringen"),
                                                                          Inzet(ids["bo"], "verspringen")]
        s = opstelling.stand(m, inzet)
        tachtig = s.onderdelen["80m"]
        punten = sorted((m.punten(ids[k], "80m") for k in ("anna", "bo", "cato")), reverse=True)
        assert len(tachtig.tellend) == 2 and tachtig.punten == punten[0] + punten[1]
        assert s.onderdelen["verspringen"].tellend == [ids["anna"]]          # technisch: beste één
        assert s.totaal == tachtig.punten + m.punten(ids["anna"], "verspringen")
        assert s.per_atleet[ids["anna"]] == 2


def test_controleer_met_andere_ploeg_en_geen_prestatie():
    with opslag() as (db, _, ids):
        rs = regels.laad(BESTAND)
        a, b = _ploeg(db), _ploeg(db, "U16 meisjes B")
        db.ploeg_opstelling_opslaan(b.id, [PloegLid(ids["bo"])], [])
        m = _matrix(db, ids)
        leden = [PloegLid(ids["anna"]), PloegLid(ids["bo"])]
        uit = opstelling.controleer(db, rs, a, leden, [Inzet(ids["anna"], "800m")], m)
        codes = sorted(o.code for o in uit)
        assert codes == ["geen_prestatie", "twee_ploegen"]
        assert next(o for o in uit if o.code == "twee_ploegen").atleet_id == ids["bo"]


def test_kandidaten_en_formulier():
    with opslag() as (db, _, ids):
        rs = regels.laad(BESTAND)
        p = _ploeg(db)
        k = [a.master_id for a in opstelling.kandidaten(db, rs, p)]
        assert set(k) == {ids["anna"], ids["bo"], ids["cato"]}               # geen jongen
        assert ids["dirk"] in [a.master_id for a in opstelling.kandidaten(db, rs, p, [PloegLid(ids["dirk"])])]

        class Form(dict):
            def getlist(self, k):
                v = self.get(k, [])
                return v if isinstance(v, list) else [v]

        form = Form({"inzet": [f"{ids['anna']}|80m", f"{ids['bo']}|80m", f"{ids['bo']}|80m",
                               f"{ids['dirk']}|80m", f"{ids['anna']}|hamer"],
                     f"rol-{ids['cato']}": "reserve", f"rol-{ids['bo']}": "kapot"})
        leden, inzet = opstelling.lees_formulier(form, k, ["80m", "800m"])
        assert {(lid.atleet_id, lid.rol) for lid in leden} == {(ids["anna"], "deelnemer"), (ids["bo"], "deelnemer"),
                                                               (ids["cato"], "reserve")}
        assert [(i.atleet_id, i.onderdeel) for i in inzet] == [(ids["anna"], "80m"), (ids["bo"], "80m")]
    assert programma_label("finale_2027") == "Finale 2027" and programma_label("wedstrijd_2") == "Wedstrijd 2"


# ------------------------------------------------------------
# Pagina's
# ------------------------------------------------------------
@contextlib.contextmanager
def client():
    with opslag() as (db, tmp, ids):
        db.sluit()
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        yield app.test_client(), tmp, ids


def tekst(r) -> str:
    return r.get_data(as_text=True)


def test_paginas_nieuwe_ploeg_opstellen_en_verwijderen():
    with client() as (c, tmp, ids):
        assert "Nog geen ploegen" in tekst(c.get("/ploegen"))
        html = tekst(c.get("/ploegen/nieuw"))
        assert f'value="{BESTAND}|U16-V"' in html and 'value="finale_2027"' in html

        r = c.post("/ploegen/nieuw", data={"naam": "", "ploeg": f"{BESTAND}|U16-V", "programma": "wedstrijd_1"})
        assert r.status_code == 400 and "Geef de ploeg een naam" in tekst(r)
        r = c.post("/ploegen/nieuw", data={"naam": "U16 A", "ploeg": f"{BESTAND}|U16-V",
                                           "programma": "wedstrijd_1", "datum": DAG.isoformat()})
        assert r.status_code == 302
        pad = r.headers["Location"]
        html = tekst(c.get(pad))
        assert "U16 A" in html and "Anna Proef" in html and "Dirk Proef" not in html
        assert "80 meter horden" in html and "max 3 · telt 2" in html

        r = c.post(pad, data={"inzet": [f"{ids['anna']}|80m", f"{ids['bo']}|80m", f"{ids['anna']}|verspringen"],
                              f"rol-{ids['cato']}": "reserve"})
        html = tekst(r)
        assert r.status_code == 200 and "Opgeslagen." in html and "voldoet aan de regels" in html
        assert 'class="ploegstand__getal">' in html
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            p = db.ploegen()[0]
            assert len(db.ploeg_inzet(p.id)) == 3 and len(db.ploeg_leden(p.id)) == 3

        # 4 onderdelen voor Anna: fout, met haar naam erbij
        r = c.post(pad, data={"inzet": [f"{ids['anna']}|{o}" for o in ("80m", "800m", "verspringen", "kogelstoten")]})
        assert "Dit mag nog niet" in tekst(r) and "Anna Proef: 4 onderdelen" in tekst(r)

        assert "U16 A" in tekst(c.get("/ploegen"))
        r = c.post(f"{pad}/gegevens", data={"naam": "U16 B", "ploeg": f"{BESTAND}|U16-V",
                                             "programma": "wedstrijd_2", "datum": DAG.isoformat()})
        assert r.status_code == 302
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            p = db.ploegen()[0]
            assert p.naam == "U16 B" and p.programma == "wedstrijd_2"
            assert {i.onderdeel for i in db.ploeg_inzet(p.id)} == {"verspringen", "kogelstoten"}   # 80m/800m vervallen

        assert c.post(f"{pad}/verwijderen").status_code == 302
        assert c.get(pad).status_code == 404
        assert "Nog geen ploegen" in tekst(c.get("/ploegen"))
