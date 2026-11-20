"""Tests voor stap 7: het tijdschema bij een ploeg (ploeg/tijdschema.py: botsingen,
dagdelen, groepen), meer ploegen op één dag (paginas.dag_optimaliseren, pagina
/ploegen/dag/<datum>) en age grading voor masters (punten.Leeftijdsfactoren).

Alleen nepgegevens.
"""

import contextlib
from datetime import date

from test_ploegen import BESTAND, DAG, JAAR, opslag

from atleten import beheer
from db.queries import Opslag
from models import Inzet, Onderdeel, Ploeg, PloegLid, Prestatie, ProgrammaOnderdeel, Wedstrijd
from ploeg import opstelling, paginas, punten, regels, strategieen, tijdschema, vergelijk
from ploeg.optimaliseer import optimaliseer
from ui.app import maak_app
from hulp import TESTSLEUTEL, app_client, verwacht as _verwacht

RS = regels.laad(BESTAND)


def _tijdschema(db, wid: int) -> None:
    def regel(tekst, tijd, categorie="Meisjes U16", groep=None, duur=30):
        db.programma_opslaan(ProgrammaOnderdeel(wid, DAG, tijd, onderdeel_tekst=tekst, categorie=categorie,
                                                groep=groep, duur=duur))
    regel("80m", "10:00")
    regel("80m", "10:00", categorie="Jongens U16")          # niet voor meisjes
    regel("Verspringen", "10:00", duur=60)                    # botst met de 80 m
    regel("Kogelstoten 3kg", "11:00", groep=1, duur=60)
    regel("Kogelstoten 3kg", "14:00", groep=2, duur=60)
    regel("800m", "14:30")
    regel("4 x 80 meter", "15:30")


@contextlib.contextmanager
def met_wedstrijd():
    """(db, map, ids, ploeg) met een U16-ploeg die aan een wedstrijd met tijdschema hangt."""
    with opslag() as (db, tmp, ids):
        w = db.wedstrijd_opslaan(Wedstrijd("Competitie 1", DAG))
        _tijdschema(db, w.id)
        p = db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG, wedstrijd_id=w.id))
        yield db, tmp, ids, p


def _schema(db, p):
    pg = paginas.ploegpagina(db, p.id)
    return pg, pg.schema


# ------------------------------------------------------------
# Tijdschema
# ------------------------------------------------------------
def test_schema_koppelt_naam_en_categorie():
    with met_wedstrijd() as (db, _, ids, p):
        pg, s = _schema(db, p)
        anna = ids["anna"]
        assert [r.starttijd for r in s.van(anna, "80m")] == ["10:00"]            # niet die van de jongens
        assert s.groepen(anna, "kogelstoten") == [1, 2]
        assert s.van(ids["cato"], "kogelstoten")             # U14 in de U16-ploeg: tijdschema van de U16
        assert s.van(anna, "4x80m") and not s.van(anna, "hoogspringen")
        assert s.botst(anna, "80m", "verspringen") and not s.botst(anna, "80m", "800m")
        assert not s.botst(anna, "kogelstoten", "verspringen")                    # groep 2 kan wel
        assert pg.tijden("kogelstoten") == "11:00 / 14:00"
        assert s.past_dagdeel(anna, "80m", "ochtend") and not s.past_dagdeel(anna, "80m", "middag")
        assert s.past_dagdeel(anna, "kogelstoten", "middag")                      # groep 2 om 14:00
        assert s.past_dagdeel(anna, "hoogspringen", "middag")                     # geen tijd: geen beperking


def test_geen_schema_zonder_wedstrijd_of_tijdschema():
    with opslag() as (db, _, ids):
        p = db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG))
        assert paginas.ploegpagina(db, p.id).schema is None
        w = db.wedstrijd_opslaan(Wedstrijd("Zonder schema", DAG))
        p.wedstrijd_id = w.id
        db.ploeg_opslaan(p)
        pg = paginas.ploegpagina(db, p.id)
        assert pg.schema is None and pg.tijden("80m") == ""


def test_controle_botsing_en_dagdeel():
    with met_wedstrijd() as (db, _, ids, p):
        pg, s = _schema(db, p)
        anna = ids["anna"]
        leden = [PloegLid(anna, beschikbaar="middag")]
        inzet = [Inzet(anna, "80m"), Inzet(anna, "verspringen")]
        uit = opstelling.controleer(db, RS, p, leden, inzet, pg.matrix, s)
        codes = [(o.code, o.onderdeel) for o in uit]
        assert ("botsing", "verspringen") in codes
        assert ("dagdeel", "80m") in codes and ("dagdeel", "verspringen") in codes
        assert all(o.ernst == "waarschuwing" for o in uit if o.code in ("botsing", "dagdeel"))


def test_optimaliseren_houdt_rekening_met_tijdschema():
    with met_wedstrijd() as (db, _, ids, p):
        pg, s = _schema(db, p)
        a = [ids[k] for k in ("anna", "bo", "cato")]
        leden = [PloegLid(ids["anna"]), PloegLid(ids["bo"], beschikbaar="ochtend"), PloegLid(ids["cato"])]
        zonder = optimaliseer(pg.matrix, RS, strategieen.strategie("max_punten"), a, leden, [], False)
        assert {("80m"), ("verspringen")} <= {i.onderdeel for i in zonder.inzet if i.atleet_id == ids["anna"]}
        met = optimaliseer(pg.matrix, RS, strategieen.strategie("max_punten"), a, leden, [], False, s)
        for x in a:
            eigen = [i.onderdeel for i in met.inzet if i.atleet_id == x]
            assert not s.botsingen(x, eigen), (x, eigen)
        bo = [i.onderdeel for i in met.inzet if i.atleet_id == ids["bo"]]
        assert "800m" not in bo and all(s.past_dagdeel(ids["bo"], e, "ochtend") for e in bo)
        assert opstelling.stand(pg.matrix, met.inzet).totaal <= opstelling.stand(pg.matrix, zonder.inzet).totaal
        # een vaste keuze buiten het dagdeel kan niet
        try:
            optimaliseer(pg.matrix, RS, strategieen.strategie("max_punten"), a, leden,
                         [Inzet(ids["bo"], "800m", vast=True)], False, s)
        except Exception as e:                                                    # OptimalisatieFout
            assert "geen opstelling" in str(e)
        else:
            raise AssertionError("OptimalisatieFout verwacht")


def test_groepen_en_formulier_met_dagdeel():
    with met_wedstrijd() as (db, tmp, ids, p):
        db.sluit()
        c = app_client(tmp)
        anna, cato = ids["anna"], ids["cato"]
        r = c.post(f"/ploeg/{p.id}", data={
            f"rol-{anna}": "deelnemer", f"beschikbaar-{anna}": "middag",
            f"rol-{cato}": "deelnemer", f"beschikbaar-{cato}": "iets",          # onzin: hele dag
            "inzet": [f"{anna}|kogelstoten", f"{cato}|kogelstoten", f"{anna}|80m"]})
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "11:00 / 14:00" in html and "gr. 1" in html and "gr. 2" in html
        assert 'value="middag" selected' in html and "maar deze atleet is er alleen" in html
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db2:
            leden = {lid.atleet_id: lid.beschikbaar for lid in db2.ploeg_leden(p.id)}
            assert leden == {anna: "middag", cato: "hele_dag"}
            groepen = {i.atleet_id: i.groep for i in db2.ploeg_inzet(p.id) if i.onderdeel == "kogelstoten"}
            assert groepen[anna] == 2 and groepen[cato] == 1          # anna 's middags: groep 2 (14:00)
            assert not any(i.groep for i in db2.ploeg_inzet(p.id) if i.onderdeel == "80m")


def test_groepen_indelen_zonder_schema_of_een_groep():
    inzet = [Inzet("a" * 32, "kogelstoten", groep=3)]
    assert tijdschema.groepen_indelen(None, RS, inzet)[0].groep is None


# ------------------------------------------------------------
# Meer ploegen op één dag
# ------------------------------------------------------------
def _extra_meisjes(db, n: int) -> list[str]:
    o = next(x for x in db.onderdelen() if x.naam == "80 meter")
    uit = []
    for k in range(n):
        a = beheer.nieuwe_atleet(db, f"Extra{k}", "Proef", geslacht="V", geboortedatum=f"{JAAR - 15}-02-0{k + 1}")
        db.prestatie_opslaan(Prestatie("80 meter", date(JAAR, 4, 20), 11.0 + k / 10, atleet_id=a.master_id,
                                       onderdeel_id=o.id, wind=0.0))
        uit.append(a.master_id)
    return uit


def test_dag_optimaliseren_na_elkaar():
    with opslag() as (db, _, ids):
        _extra_meisjes(db, 4)
        a = db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG))
        b = db.ploeg_opslaan(Ploeg("U16 B", BESTAND, "U16-V", "wedstrijd_1", DAG))
        # anna staat nu in B; A kiest eerst en mag haar pakken
        db.ploeg_opstelling_opslaan(b.id, [PloegLid(ids["anna"])], [Inzet(ids["anna"], "80m")])
        dag = paginas.dagpagina(db, DAG)
        assert [r.ploeg.naam for r in dag.regels] == ["U16 A", "U16 B"]
        keuzes = paginas.lees_dagformulier({}, dag)
        assert keuzes == [(a.id, "max_punten"), (b.id, "max_punten")]
        uit = paginas.dag_optimaliseren(db, keuzes)
        in_a = {lid.atleet_id for lid in db.ploeg_leden(a.id)}
        in_b = {lid.atleet_id for lid in db.ploeg_leden(b.id)}
        assert in_a and in_b and not in_a & in_b                      # 10.10
        assert ids["anna"] in in_a
        assert uit[0].na >= uit[1].na
        assert not any(o.code == "twee_ploegen" for x in uit for o in x.pagina.fouten)
        # volgorde omdraaien en een ploeg overslaan
        keuzes = paginas.lees_dagformulier({f"volgorde-{a.id}": "2", f"volgorde-{b.id}": "1",
                                            f"strategie-{a.id}": "overslaan"}, dag)
        assert keuzes == [(b.id, "max_punten")]
        _verwacht(paginas.InvoerFout, lambda: paginas.lees_dagformulier({f"volgorde-{a.id}": "eerst"}, dag))
        _verwacht(paginas.InvoerFout, lambda: paginas.lees_dagformulier({f"strategie-{a.id}": "x"}, dag))


def test_dagpagina_in_de_ui():
    with opslag() as (db, tmp, ids):
        a = db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG))
        b = db.ploeg_opslaan(Ploeg("U14 A", BESTAND, "U14-V", "wedstrijd_1", DAG))
        db.sluit()
        c = app_client(tmp)
        html = c.get("/ploegen").get_data(as_text=True)
        assert f"/ploegen/dag/{DAG.isoformat()}" in html and "2 ploegen samen" in html
        html = c.get(f"/ploeg/{a.id}").get_data(as_text=True)
        assert "Alle opstellingen van deze dag maken" in html
        html = c.get(f"/ploegen/dag/{DAG.isoformat()}").get_data(as_text=True)
        assert "U14 A" in html and "U16 A" in html and 'name="strategie-' in html
        r = c.post(f"/ploegen/dag/{DAG.isoformat()}", data={f"strategie-{a.id}": "max_punten",
                                                            f"strategie-{b.id}": "max_punten"})
        assert r.status_code == 200 and "Klaar." in r.get_data(as_text=True)
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db2:
            cato_in = [q.naam for q in (a, b) if ids["cato"] in {lid.atleet_id for lid in db2.ploeg_leden(q.id)}]
            assert len(cato_in) <= 1
        assert c.post(f"/ploegen/dag/{DAG.isoformat()}", data={f"volgorde-{a.id}": "x"}).status_code == 400
        assert c.get("/ploegen/dag/geen-datum").status_code == 404


# ------------------------------------------------------------
# Masters: age grading
# ------------------------------------------------------------
def test_leeftijdsfactoren_lezen():
    lf = punten.Leeftijdsfactoren.uit_dict({"factoren": {"V": {"100m": {35: 0.99, 45: 0.90}}, "M": {}}})
    assert not lf.leeg
    assert lf.factor("V", "100m", 47) == 0.90 and lf.factor("V", "100m", 44) == 0.99
    assert lf.factor("V", "100m", 34) is None and lf.factor("M", "100m", 50) is None
    assert lf.factor("V", "200m", 50) is None and lf.factor(None, "100m", 50) is None
    for fout in ({"factoren": {"X": {}}}, {"factoren": {"V": {"100m": {"oud": 1.0}}}},
                 {"factoren": {"V": {"100m": {40: 99}}}}, {"tabel": 1}, []):
        _verwacht(punten.PuntenFout, lambda f=fout: punten.Leeftijdsfactoren.uit_dict(f))
    # het meegeleverde bestand en het mastersbestand: zie test_masters_agegrading.py


def test_masters_punten_met_leeftijdsfactor():
    rs = regels.laad("masters_2026-2027")
    lf = punten.Leeftijdsfactoren.uit_dict({"factoren": {"V": {"100m": {45: 0.90}}}})
    oud = punten.leeftijdsfactoren
    punten.leeftijdsfactoren = lambda naam, map=None: lf
    try:
        with opslag() as (db, tmp, _):
            o = db.onderdeel_opslaan(Onderdeel("100 meter", "tijd", True))
            hoog = db.onderdeel_opslaan(Onderdeel("Hoogspringen", "hoogte", False))
            v = beheer.nieuwe_atleet(db, "Vera", "Proef", geslacht="V", geboortedatum=f"{JAAR - 47}-01-01")
            db.prestatie_opslaan(Prestatie("100 meter", date(JAAR, 4, 20), 14.00, atleet_id=v.master_id,
                                           onderdeel_id=o.id, wind=0.0))
            db.prestatie_opslaan(Prestatie("Hoogspringen", date(JAAR, 4, 20), 1.40, atleet_id=v.master_id,
                                           onderdeel_id=hoog.id))
            m = vergelijk.matrix(db, rs, "MAS-V", "wedstrijd_1", DAG, [db.atleet(v.master_id)])
            c = m.cel(v.master_id, "100m")
            assert c.leeftijdsfactor == 0.90 and c.waarde == 14.00
            assert c.punten == punten.punten("au_senioren", "100m", "V", 14.00 * 0.90)
            assert c.punten > punten.punten("au_senioren", "100m", "V", 14.00)
            h = m.cel(v.master_id, "hoogspringen")
            assert h.leeftijdsfactor is None and h.punten == punten.punten("au_senioren", "hoogspringen", "V", 1.40)
            p = db.ploeg_opslaan(Ploeg("Masters V", "masters_2026-2027", "MAS-V", "wedstrijd_1", DAG))
            pg = paginas.ploegpagina(db, p.id)
            zonder = [c for r in pg.matrix.rijen for c in r.cellen.values()
                      if c.punten is not None and c.leeftijdsfactor is None]
            assert pg.zonder_leeftijdsfactor == len(zonder) >= 1 and h in zonder        # o.a. het hoogspringen
            db.sluit()
            app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
            app.config["TESTING"] = True
            assert "ontbreekt een leeftijdsfactor" in app.test_client().get(f"/ploeg/{p.id}").get_data(as_text=True)
    finally:
        punten.leeftijdsfactoren = oud
