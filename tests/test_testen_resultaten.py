"""Tests voor src/testen/resultaten.py en de testtabellen in db/queries.py (testen.db).

Alleen nepgegevens en een vaste testsleutel (de nepgroep uit test_groep_landingspagina).

"""

from datetime import date

import pytest
from test_groep_landingspagina import opslag, voorbeeldgroep

from db.queries import OpslagFout
from models import Test, Testresultaat
from testen import resultaten as res
from testen import sjabloon as sj
from testen.sjabloon import Onderdeel, Sjabloon, SjabloonFout

DAG = date(2026, 10, 20)


def sprong(totaal=True) -> Sjabloon:
    return Sjabloon("Sprongkracht", [
        Onderdeel("Hoogspringen staand", "lengte", "C1 * L", [100]),
        Onderdeel("30 m sprint", "tijd", "C1 / T", [150]),
        Onderdeel("Kogel", "gewicht"),
    ], totaal)


def bewaar(db, tmp, s):
    return res.sjabloon_opslaan(db, s, tmp)


def tabelrijen(db, tabel):
    return db.testen_db.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]


def test_meerdere_onderdelen_met_totaal():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        s = bewaar(db, tmp, sprong())
        r = res.resultaat_vastleggen(db, anna, s, DAG, ["0,5", "4", "7,5"], "  prima  ")
        assert (r.waarde, r.score, r.notities) == (87.5, 87.5, "prima")
        test = db.test_op_sjabloon("sprongkracht")
        assert (test.naam, test.eenheid, test.lager_is_beter) == ("Sprongkracht", "punten", False)
        terug = db.testresultaten(anna)[0]
        assert [(d.deel, d.waarde, d.score) for d in terug.delen] == [(0, 0.5, 50.0), (1, 4.0, 37.5), (2, 7.5, None)]
        assert terug.score == 87.5 and terug.datum == DAG and terug.id == r.id


def test_zonder_totaal_is_hoofdwaarde_de_eerste_meting():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        s = bewaar(db, tmp, sprong(totaal=False))
        r = res.resultaat_vastleggen(db, anna, s, DAG, ["0,5", "4", ""])      # laatste onderdeel niet gedaan
        assert (r.waarde, r.score) == (0.5, None) and [d.deel for d in r.delen] == [0, 1]
        assert [d.score for d in r.delen] == [50.0, 37.5]                      # de scores per onderdeel staan er wel
        test = db.test_op_sjabloon("sprongkracht")
        assert (test.eenheid, test.lager_is_beter) == ("m", False)
        r2 = res.resultaat_vastleggen(db, anna, s, DAG, ["", "4", ""])         # eerste leeg: eerste die er is
        assert r2.waarde == 4.0


def test_een_onderdeel_zonder_en_met_formule():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        kaal = bewaar(db, tmp, Sjabloon("Eigen sprinttijd", [Onderdeel("Tijd", "tijd")]))
        r = res.resultaat_vastleggen(db, anna, kaal, DAG, ["4,25"])
        assert (r.waarde, r.score) == (4.25, None) and len(r.delen) == 1
        t = db.test_op_sjabloon(kaal.slug)
        assert (t.eenheid, t.lager_is_beter) == ("s", True)
        met = bewaar(db, tmp, Sjabloon("Staand hoog", [Onderdeel("Hoogte", "lengte", "C1 * L", [100])]))
        r = res.resultaat_vastleggen(db, anna, met, DAG, ["0,55"])
        assert r.waarde == 0.55 and r.score == pytest.approx(55.0)                            # hoofdwaarde: de meting; score apart


def test_foute_invoer_slaat_niets_op():
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        anna = ids["anna"]
        s = bewaar(db, tmp, sprong())
        voor = tabelrijen(db, "testresultaat"), tabelrijen(db, "testresultaat_deel")
        gevallen = [
            (["", "", ""], "minstens één"),
            (["0,5", "4"], "Verwacht 3"),
            (["abc", "4", "7"], "geen geldig getal"),
            (["-1", "4", "7"], "geen geldig getal"),
            (["nan", "4", "7"], "geen geldig getal"),
            (["inf", "4", "7"], "geen geldig getal"),
            (["0,5", "", "7"], "nog leeg: 30 m sprint"),        # totaal: alle formule-onderdelen verplicht
            (["0,5", "0", "7"], "Delen door nul"),                # 150 / 0
        ]
        for invoer, fragment in gevallen:
            with pytest.raises(OpslagFout, match=fragment):
                res.resultaat_vastleggen(db, anna, s, DAG, invoer)
        with pytest.raises(OpslagFout, match="toekomst"):
            res.resultaat_vastleggen(db, anna, s, date(2999, 1, 1), ["1", "1", "1"])
        with pytest.raises(OpslagFout, match="Onbekende atleet"):
            res.resultaat_vastleggen(db, "0" * 32, s, DAG, ["1", "1", "1"])
        assert (tabelrijen(db, "testresultaat"), tabelrijen(db, "testresultaat_deel")) == voor


def test_oude_test_met_dezelfde_naam_wordt_gekoppeld():
    """Een test van vóór de sjablonen (zonder sjabloon) houdt zijn resultaten als er een sjabloon met die naam komt."""
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        oud = db.test_opslaan(Test("30m vliegend", "s", True))
        db.testresultaat_opslaan(Testresultaat(anna, oud.id, date(2026, 9, 1), 4.4))
        s = bewaar(db, tmp, Sjabloon("30m vliegend", [Onderdeel("Tijd", "tijd")]))
        r = res.resultaat_vastleggen(db, anna, s, DAG, ["4,1"])
        assert r.test_id == oud.id and len(db.testen()) == 1
        assert db.testen()[0].sjabloon == s.slug
        assert [x.waarde for x in db.testresultaten(anna, oud.id)] == [4.4, 4.1]
        assert db.testresultaten(anna, oud.id)[0].delen == []                  # het oude resultaat heeft geen onderdelen
        # test_opslaan zonder sjabloon (oude manier) haalt het sjabloon niet weg
        db.test_opslaan(Test("30m vliegend", "s", True))
        assert db.testen()[0].sjabloon == s.slug


def test_naam_van_andere_test_geweigerd():
    with opslag() as (db, tmp):
        voorbeeldgroep(db)
        a = bewaar(db, tmp, Sjabloon("Een", [Onderdeel("x", "tijd")]))
        b = bewaar(db, tmp, Sjabloon("Twee", [Onderdeel("x", "tijd")]))
        anna = db.atleten()[0].master_id if hasattr(db, "atleten") else None
        for s in (a, b):
            res.test_voor_sjabloon(db, s)
        # Hernoemen van het sjabloon 'Twee' naar 'Een' wordt al door het sjabloon zelf geweigerd.
        with pytest.raises(SjabloonFout, match="al een test met de naam"):
            res.sjabloon_opslaan(db, Sjabloon("Een", b.onderdelen, True, b.slug), tmp)
        # En de database weigert het ook als een test al zo heet.
        t = db.test_op_sjabloon(b.slug)
        t.naam = "Een"
        with pytest.raises(OpslagFout, match="al een test"):
            db.test_opslaan(t)
        assert anna is None or anna


def test_wijzigen_met_resultaten():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        s = bewaar(db, tmp, sprong())
        # Zonder resultaten mag alles.
        bewaar(db, tmp, Sjabloon("Sprongkracht", [Onderdeel("Hoog", "lengte", "C1 * L", [100])], True, s.slug))
        s = bewaar(db, tmp, Sjabloon("Sprongkracht", sprong().onderdelen, True, s.slug))
        res.resultaat_vastleggen(db, anna, s, DAG, ["0,5", "4", "7"])
        oud_score = db.testresultaten(anna)[0].score

        def probeer(onderdelen, totaal=True):
            return res.sjabloon_opslaan(db, Sjabloon("Sprongkracht", onderdelen, totaal, s.slug), tmp)

        g = sprong().onderdelen
        with pytest.raises(SjabloonFout, match="aantal onderdelen"):
            probeer(g[:2])                                                     # onderdeel erbij of eraf
        with pytest.raises(SjabloonFout, match="aantal onderdelen"):
            probeer([g[1], g[0], g[2]])                                        # andere volgorde/soort
        with pytest.raises(SjabloonFout, match="totaal optellen"):
            probeer(g, totaal=False)                                           # eenheid van de hoofdwaarde zou veranderen
        # Namen en formules mogen wel veranderen; oude scores blijven zoals ze waren.
        nieuw = [Onderdeel("Hoog (nieuw)", "lengte", "C1 * L * 2", [100]), g[1], g[2]]
        probeer(nieuw)
        assert db.testresultaten(anna)[0].score == oud_score
        regel = res.resultaatregels(db, anna, datamap=tmp)[0]
        assert regel.delen[0].naam == "Hoog (nieuw)" and regel.delen[0].score == 50.0
        # Het nieuwe resultaat gebruikt de nieuwe formule.
        r = res.resultaat_vastleggen(db, anna, sj.laad_bibliotheek(tmp).vind(s.slug).sjabloon, DAG, ["0,5", "4", "7"])
        assert r.delen[0].score == 100.0 and r.score == 137.5


def test_hernoemen_van_het_sjabloon_hernoemt_de_test():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        s = bewaar(db, tmp, Sjabloon("Oude naam", [Onderdeel("x", "tijd")]))
        res.resultaat_vastleggen(db, anna, s, DAG, ["5"])
        bewaar(db, tmp, Sjabloon("Nieuwe naam", [Onderdeel("x", "tijd")], True, s.slug))
        assert [t.naam for t in db.testen()] == ["Nieuwe naam"] and len(db.testresultaten(anna)) == 1


def test_resultaatregels_nieuwste_eerst_en_zonder_sjabloon():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        s = bewaar(db, tmp, sprong())
        res.resultaat_vastleggen(db, anna, s, date(2026, 9, 1), ["0,4", "5", "6"])
        res.resultaat_vastleggen(db, anna, s, date(2026, 10, 1), ["0,5", "4", "7"])
        regels = res.resultaatregels(db, anna, datamap=tmp)
        assert [r.resultaat.datum for r in regels] == [date(2026, 10, 1), date(2026, 9, 1)]
        r = regels[0]
        assert r.is_totaal and [(d.naam, d.eenheid, d.waarde) for d in r.delen] == [
            ("Hoogspringen staand", "m", 0.5), ("30 m sprint", "s", 4.0), ("Kogel", "kg", 7.0)]
        # Het YAML-bestand is weg: de resultaten blijven te lezen.
        (tmp / "testsjablonen" / "sprongkracht.yaml").unlink()
        r = res.resultaatregels(db, anna, datamap=tmp)[0]
        assert r.sjabloon is None and [d.naam for d in r.delen] == ["Onderdeel 1", "Onderdeel 2", "Onderdeel 3"]
        assert not r.is_totaal and r.resultaat.score == 87.5
        # Een test van vóór de sjablonen: geen onderdelen.
        oud = db.test_opslaan(Test("Oud", "s", True))
        db.testresultaat_opslaan(Testresultaat(anna, oud.id, DAG, 9.9))
        assert res.resultaatregels(db, anna, datamap=tmp, test_id=oud.id)[0].delen == []


def test_verwijderen_van_resultaten():
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        s = bewaar(db, tmp, sprong())
        r1 = res.resultaat_vastleggen(db, ids["anna"], s, DAG, ["0,5", "4", "7"])
        r2 = res.resultaat_vastleggen(db, ids["bram"], s, DAG, ["0,5", "4", "7"])
        assert db.testresultaat_verwijderen(ids["bram"], r1.id) is False       # niet van Bram
        assert db.testresultaat_verwijderen(ids["anna"], 9999) is False
        assert db.testresultaat_verwijderen(ids["anna"], r1.id) is True
        assert tabelrijen(db, "testresultaat") == 1 and tabelrijen(db, "testresultaat_deel") == 3   # onderdelen gaan mee
        db.atleet_verwijderen(ids["bram"])                                     # ook bij het verwijderen van de atleet
        assert tabelrijen(db, "testresultaat") == 0 and tabelrijen(db, "testresultaat_deel") == 0
        assert r2.id


def test_sjabloon_verwijderen():
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        s = bewaar(db, tmp, Sjabloon("Los", [Onderdeel("x", "tijd")]))
        res.test_voor_sjabloon(db, s)
        assert res.sjabloon_verwijderen(db, s.slug, tmp) is True               # geen resultaten: weg, met zijn testrij
        assert db.testen() == [] and sj.laad_bibliotheek(tmp).vind(s.slug) is None
        s = bewaar(db, tmp, Sjabloon("Los", [Onderdeel("x", "tijd")]))
        res.resultaat_vastleggen(db, anna, s, DAG, ["5"])
        with pytest.raises(SjabloonFout, match="al resultaten"):
            res.sjabloon_verwijderen(db, s.slug, tmp)
        assert sj.laad_bibliotheek(tmp).vind(s.slug) is not None


def test_verloop_en_beste_werken_met_sjabloontests():
    from atleten import testen as atleet_testen
    with opslag() as (db, tmp):
        anna = voorbeeldgroep(db)["anna"]
        s = bewaar(db, tmp, Sjabloon("30m", [Onderdeel("Tijd", "tijd")]))
        for dag, w in ((date(2026, 9, 1), "4,4"), (date(2026, 10, 1), "4,1"), (date(2026, 10, 8), "4,2")):
            res.resultaat_vastleggen(db, anna, s, dag, [w])
        assert atleet_testen.beste(db, anna, "30m").waarde == 4.1               # lager is beter bij een tijd
        assert atleet_testen.vooruitgang(db, anna, "30m") == 0.2
        assert atleet_testen.laatste_per_test(db, anna)[db.test_op_naam("30m").id].waarde == 4.2
