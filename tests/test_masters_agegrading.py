"""Tests voor de age grading van de Mastercompetitie: config/puntentelling/masters_agegrading.yaml.

De voorbeelden (prestatie, leeftijdsklasse -> punten) komen uit de spreadsheet 'Mastersploeg 2023'
(blad mannenploeg/vrouwenploeg, voorbeeldregels): met dezelfde puntenconstanten als de spreadsheet moet AVS
op exact dezelfde punten uitkomen. Alleen nepgegevens.

"""

from datetime import date

import pytest


from test_ploegen import DAG, JAAR, opslag

from atleten import beheer
from models import Onderdeel, Prestatie
from ploeg import punten, regels, vergelijk

# (geslacht, onderdeel, leeftijdsklasse, prestatie in s of m, punten in de spreadsheet)
VOORBEELDEN = [
    ("M", "100m", 35, 11.5, 688), ("M", "200m", 70, 30.0, 710), ("M", "400m", 70, 70.0, 624),
    ("M", "800m", 70, 150.0, 889), ("M", "1500m", 70, 290.0, 1044), ("M", "5000m", 70, 1000.0, 1295),
    ("M", "hoogspringen", 70, 1.5, 992), ("M", "verspringen", 70, 5.0, 998), ("M", "kogelstoten", 70, 12.48, 863),
    ("M", "discuswerpen", 80, 30.0, 787), ("M", "speerwerpen", 70, 40.0, 789), ("M", "kogelslingeren", 35, 55.15, 873),
    ("V", "100m", 70, 17.0, 658), ("V", "200m", 70, 35.0, 716), ("V", "400m", 70, 80.0, 886),
    ("V", "800m", 70, 200.0, 728), ("V", "1500m", 35, 330.0, 540), ("V", "3000m", 70, 1020.0, 456),
    ("V", "hoogspringen", 70, 1.35, 1178), ("V", "verspringen", 70, 3.5, 797), ("V", "kogelstoten", 70, 8.0, 798),
    ("V", "discuswerpen", 70, 22.0, 803), ("V", "speerwerpen", 70, 28.0, 995), ("V", "kogelslingeren", 70, 28.0, 928),
]


def factoren() -> punten.Leeftijdsfactoren:
    return punten.leeftijdsfactoren("masters_agegrading")


@pytest.mark.parametrize("geslacht, onderdeel, klasse, prestatie, verwacht", VOORBEELDEN)
def test_punten_zoals_de_spreadsheet(geslacht, onderdeel, klasse, prestatie, verwacht):
    f = factoren().factor(geslacht, onderdeel, klasse)
    assert f is not None
    w = punten.gecorrigeerd(prestatie, f, onderdeel)
    assert punten.punten("au_senioren", onderdeel, geslacht, w) == verwacht


def test_tabel_is_compleet():
    lf = factoren()
    assert not lf.leeg and lf.naam.startswith("Age grading")
    klassen = list(range(35, 101, 5))
    lopen = ["100m", "200m", "400m", "800m", "1500m"]
    technisch = ["hoogspringen", "verspringen", "kogelstoten", "discuswerpen", "speerwerpen", "kogelslingeren"]
    for g, extra in (("M", "5000m"), ("V", "3000m")):
        assert set(lf.factoren[g]) == set(lopen + [extra] + technisch)
        for tabel in lf.factoren[g].values():
            assert sorted(tabel) == klassen
    # Lopen: de factor daalt met de leeftijd en is nooit groter dan 1; springen en werpen: factor >= 1 (bij 35 jaar).
    for g in "MV":
        for o in lopen:
            rij = [lf.factoren[g][o][k] for k in klassen]
            assert rij == sorted(rij, reverse=True) and rij[0] <= 1.0
        for o in ("hoogspringen", "verspringen"):
            rij = [lf.factoren[g][o][k] for k in klassen]
            assert rij == sorted(rij) and rij[0] >= 1.0


def test_gekozen_waarden():
    lf = factoren()
    assert lf.factor("M", "100m", 35) == 0.9999 and lf.factor("V", "100m", 35) == 1.0
    assert lf.factor("V", "speerwerpen", 100) == 5.5753 and lf.factor("M", "5000m", 100) == 0.3313
    # Een leeftijd tussen twee klassen: de factor van de eigen klasse (ondergrens).
    assert lf.factor("M", "100m", 47) == lf.factor("M", "100m", 45) == 0.9345
    assert lf.factor("M", "100m", 39) == lf.factor("M", "100m", 35)
    assert lf.factor("M", "100m", 34) is None                                  # geen master
    assert lf.factor("M", "100m", 105) == lf.factor("M", "100m", 100)
    assert lf.factor("M", "3000m", 50) is None and lf.factor("V", "5000m", 50) is None   # niet in de competitie
    assert lf.factor("M", "4x100m", 40) is None and lf.factor("M", "zweedse", 40) is None  # estafettes: geen factor


def test_afronden_zoals_de_spreadsheet():
    # tijd: naar boven op 0,01; afstand: naar beneden op 0,01; geen ruis van kommagetallen
    assert punten.gecorrigeerd(14.00, 0.90, "100m") == 12.6
    assert punten.gecorrigeerd(11.5, 0.9999, "100m") == 11.5                  # 11,49885 -> 11,50
    assert punten.gecorrigeerd(11.51, 0.9999, "100m") == 11.51
    assert punten.gecorrigeerd(1.5, 0.9, "hoogspringen") == 1.35
    assert punten.gecorrigeerd(7.0, 1.0385, "verspringen") == 7.26            # 7,2695 -> naar beneden: 7,26
    assert punten.gecorrigeerd(58.4, 0.8616, "400m", handtijd=True) == 50.44  # (58,4 + 0,14) x 0,8616 = 50,4381 -> 50,44


def test_matrix_met_de_echte_tabel():
    """Een vrouw van 47 (klasse 45) en een man van 52 (klasse 50) in de matrix van de Mastercompetitie."""
    rs = regels.laad("masters_2026-2027")
    with opslag() as (db, tmp, _):
        o100 = db.onderdeel_opslaan(Onderdeel("100 meter", "tijd", True))
        kogel = db.onderdeel_opslaan(Onderdeel("Kogelstoten 3kg", "afstand", False))
        v = beheer.nieuwe_atleet(db, "Vera", "Proef", geslacht="V", geboortedatum=f"{JAAR - 47}-01-01")
        m = beheer.nieuwe_atleet(db, "Mark", "Proef", geslacht="M", geboortedatum=f"{JAAR - 52}-01-01")
        db.prestatie_opslaan(Prestatie("100 meter", date(JAAR, 4, 20), 14.00, atleet_id=v.master_id,
                                       onderdeel_id=o100.id, wind=0.0))
        db.prestatie_opslaan(Prestatie("Kogelstoten 3kg", date(JAAR, 4, 20), 9.00, atleet_id=v.master_id,
                                       onderdeel_id=kogel.id))
        mat = vergelijk.matrix(db, rs, "MAS-V", "wedstrijd_1", DAG, [db.atleet(v.master_id)])
        c = mat.cel(v.master_id, "100m")
        assert c.leeftijdsfactor == 0.9441 and c.waarde == 14.00
        assert c.punten == punten.punten("au_senioren", "100m", "V", punten.gecorrigeerd(14.00, 0.9441, "100m"))
        assert c.punten > punten.punten("au_senioren", "100m", "V", 14.00)           # age grading levert punten op
        k = mat.cel(v.master_id, "kogelstoten")
        if k.waarde is not None:                                                     # materiaal van de eigen klasse (3 kg)
            assert k.leeftijdsfactor == 1.2062 and k.punten > punten.punten("au_senioren", "kogelstoten", "V", 9.00)
        # Een voorspelde prestatie (200 m uit de 100 m) wordt ook met de factor van de klasse gecorrigeerd.
        p200 = mat.cel(v.master_id, "200m")
        assert p200.voorspeld and p200.leeftijdsfactor == 0.9411
        # Een man van 52 zonder prestaties: geen cellen met punten, dus ook geen 'ontbreekt een factor'.
        mm = vergelijk.matrix(db, regels.laad("masters_2026-2027"), "MAS-M", "wedstrijd_1", DAG, [db.atleet(m.master_id)])
        assert all(c.punten is None for c in mm.rijen[0].cellen.values())


def test_regelbestand_gebruikt_de_tabel():
    rs = regels.laad("masters_2026-2027")
    assert rs.leeftijdsfactoren == "masters_agegrading"
    assert not punten.leeftijdsfactoren(rs.leeftijdsfactoren).leeg
