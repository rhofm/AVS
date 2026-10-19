"""Tests voor stap 5: optimaliseren (ploeg/optimaliseer.py) met de strategieën in
ploeg/strategieen/. Een kleine matrix wordt ook met brute kracht doorgerekend om
te zien dat de solver echt het beste vindt.

Alleen nepgegevens. Werkt met pytest en los: `python tests/test_optimaliseer.py`.
"""

import itertools
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_landingspagina import TESTSLEUTEL  # noqa: E402
from test_ploegen import BESTAND, opslag  # noqa: E402

from db.queries import Opslag  # noqa: E402
from models import Atleet, Inzet, Ploeg, PloegLid  # noqa: E402
from ploeg import opstelling, paginas, regels, strategieen  # noqa: E402
from ploeg.optimaliseer import OptimalisatieFout, optimaliseer  # noqa: E402
from ploeg.vergelijk import Cel, Matrix, Rij  # noqa: E402
from ui.app import maak_app  # noqa: E402

DAG = date(2027, 5, 15)
RS = regels.laad(BESTAND)
REGELS = RS.programma("U16-V", "wedstrijd_1")          # 80m, 800m, 80mH, 4x80m, hoog, ver, kogel, discus
INDIVIDUEEL = [r.sleutel for r in REGELS if r.soort != "estafette"]


def nep_matrix(n: int, zaad: int = 1, leeg: float = 0.15) -> tuple[Matrix, list[str]]:
    """Matrix met n atleten en willekeurige punten (soms geen prestatie)."""
    rnd = random.Random(zaad)
    ids = [f"{i:x}" * 32 for i in range(1, n + 1)]
    rijen = []
    for k, mid in enumerate(ids):
        rij = Rij(Atleet(f"A{k}", "Nep", geslacht="V", master_id=mid[:32]), "U16-V", True)
        for r in REGELS:
            c = Cel(r.sleutel, r.naam)
            if r.soort != "estafette" and rnd.random() > leeg:
                c.waarde, c.punten = 1.0, rnd.randint(200, 900)
            rij.cellen[r.sleutel] = c
        rijen.append(rij)
    return Matrix(RS, "U16-V", "wedstrijd_1", DAG, "seizoen", REGELS, rijen), [r.master_id for r in rijen]


def strat(naam):
    return strategieen.strategie(naam)


def geldig(m: Matrix, r) -> None:
    """Geen fouten volgens de regels."""
    fouten = [o for o in RS.controleer("U16-V", "wedstrijd_1", r.leden, r.inzet, m.categorieen) if o.ernst == "fout"]
    assert not fouten, fouten


def brute_kracht(m: Matrix, ids: list[str], min_per_atleet: int = 0) -> int:
    """Beste totaal door alle combinaties (max 3 onderdelen per atleet) te proberen."""
    keuzes = [()] + [c for k in (1, 2, 3) for c in itertools.combinations(INDIVIDUEEL, k)]
    if min_per_atleet:
        keuzes = [k for k in keuzes if not k or len(k) >= min_per_atleet]
    regels_ = {r.sleutel: r for r in REGELS}
    beste = 0
    for combinatie in itertools.product(keuzes, repeat=len(ids)):
        per = {}
        for mid, ond in zip(ids, combinatie):
            for o in ond:
                per.setdefault(o, []).append(m.punten(mid, o))
        if any(len(v) > regels_[o].max_atleten for o, v in per.items()):
            continue
        totaal = sum(sum(sorted(v, reverse=True)[:regels_[o].tellend]) for o, v in per.items())
        beste = max(beste, totaal)
    return beste


# ------------------------------------------------------------
# De strategieën
# ------------------------------------------------------------
def test_max_punten_vindt_het_optimum():
    for zaad in (1, 2):
        m, ids = nep_matrix(3, zaad)
        r = optimaliseer(m, RS, strat("max_punten"), ids, [], [], False)
        geldig(m, r)
        assert opstelling.stand(m, r.inzet).totaal == brute_kracht(m, ids), zaad
        assert r.strategie == "max_punten"
        # geen overbodige inschrijvingen: iedereen die ergens staat, telt daar mee
        s = opstelling.stand(m, r.inzet)
        assert all(i.atleet_id in s.onderdelen[i.onderdeel].tellend for i in r.inzet)


def test_minimaal_twee():
    for zaad in (4,):
        m, ids = nep_matrix(3, zaad)
        r = optimaliseer(m, RS, strat("minimaal_twee"), ids, [], [], False)
        geldig(m, r)
        per = {}
        for i in r.inzet:
            per[i.atleet_id] = per.get(i.atleet_id, 0) + 1
        assert all(n >= 2 for n in per.values())
        assert opstelling.stand(m, r.inzet).totaal == brute_kracht(m, ids, min_per_atleet=2), zaad


def test_iedereen_meedoen():
    m, ids = nep_matrix(8, 7)
    r_max = optimaliseer(m, RS, strat("max_punten"), ids, [], [], False)
    r_ied = optimaliseer(m, RS, strat("iedereen_meedoen"), ids, [], [], False)
    geldig(m, r_ied)
    meedoen = {i.atleet_id for i in r_ied.inzet}
    assert meedoen == set(ids)                                    # iedereen staat ergens op
    assert len(r_ied.inzet) >= len(r_max.inzet)
    assert opstelling.stand(m, r_ied.inzet).totaal <= opstelling.stand(m, r_max.inzet).totaal


def test_grotere_ploeg_is_snel_en_geldig():
    m, ids = nep_matrix(25, 11)
    for naam in strategieen.STRATEGIEEN:
        r = optimaliseer(m, RS, strat(naam), ids, [], [], False)
        geldig(m, r)


# ------------------------------------------------------------
# Vaste keuzes, reserves, estafettes
# ------------------------------------------------------------
def test_vast_reserve_en_estafette_blijven():
    m, ids = nep_matrix(6, 9)
    a, b, c, d, e, f = ids
    leden = [PloegLid(x) for x in (a, b, c, d, e)] + [PloegLid(f, "reserve")]
    inzet = [Inzet(a, "800m", vast=True), Inzet(b, "kogelstoten")] + [Inzet(x, "4x80m") for x in (a, b, c, d)]
    r = optimaliseer(m, RS, strat("max_punten"), ids, leden, inzet, vastzetten=False)
    geldig(m, r)
    gekozen = {(i.atleet_id, i.onderdeel) for i in r.inzet}
    assert (a, "800m") in gekozen                                      # vast
    assert {(x, "4x80m") for x in (a, b, c, d)} <= gekozen             # estafette blijft
    assert f not in {i.atleet_id for i in r.inzet}                     # reserve doet niets
    assert {lid.atleet_id: lid.rol for lid in r.leden}[f] == "reserve"
    per = {}
    for i in r.inzet:
        per[i.atleet_id] = per.get(i.atleet_id, 0) + 1
    assert max(per.values()) <= 3                                       # estafette telt mee (4.1)

    # met 'vastzetten' blijven ook gewone vinkjes staan
    r2 = optimaliseer(m, RS, strat("max_punten"), ids, leden, inzet, vastzetten=True)
    assert (b, "kogelstoten") in {(i.atleet_id, i.onderdeel) for i in r2.inzet}


def test_tegenstrijdig_vast_geeft_fout():
    m, ids = nep_matrix(2, 3, leeg=0)
    a = ids[0]
    inzet = [Inzet(a, o, vast=True) for o in ("80m", "800m", "80mH", "verspringen")]   # 4 onderdelen vast
    try:
        optimaliseer(m, RS, strat("max_punten"), ids, [PloegLid(a)], inzet, False)
    except OptimalisatieFout as e:
        assert "geen opstelling" in str(e)
    else:
        raise AssertionError("OptimalisatieFout verwacht")


def test_onderdeel_dat_niet_past_wordt_niet_gekozen():
    m, ids = nep_matrix(3, 2, leeg=0)
    m.rijen[0].cellen["kogelstoten"].nvt = True
    m.rijen[0].cellen["kogelstoten"].punten = 5000                     # verleidelijk, maar mag niet
    r = optimaliseer(m, RS, strat("max_punten"), ids, [], [], False)
    assert (ids[0], "kogelstoten") not in {(i.atleet_id, i.onderdeel) for i in r.inzet}


# ------------------------------------------------------------
# Met de database en de pagina
# ------------------------------------------------------------
def test_optimaliseren_via_de_pagina():
    with opslag() as (db, tmp, ids):
        p = db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG, competitie="U14/U16-competitie"))
        db.sluit()
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        html = c.get(f"/ploeg/{p.id}").get_data(as_text=True)
        assert "Opstelling laten maken" in html and 'value="minimaal_twee"' in html
        r = c.post(f"/ploeg/{p.id}/optimaliseren", data={"strategie": "max_punten"})
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "Opstelling gemaakt met &#39;Zoveel mogelijk punten&#39;" in html
        assert "Laatst gemaakt met: Zoveel mogelijk punten." in html
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db2:
            assert db2.ploeg(p.id).strategie == "max_punten"
            inzet = db2.ploeg_inzet(p.id)
            assert inzet and ids["dirk"] not in {i.atleet_id for i in inzet}      # jongen mag niet
            assert (ids["anna"], "80m") in {(i.atleet_id, i.onderdeel) for i in inzet}
        assert c.post(f"/ploeg/{p.id}/optimaliseren", data={"strategie": "bestaat_niet"}).status_code == 400


def test_alleen_aangevinkte_deelnemers():
    with opslag() as (db, _, ids):
        p = db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG))
        db.ploeg_opstelling_opslaan(p.id, [PloegLid(ids["bo"])], [])
        o = paginas.optimaliseren(db, p.id, "max_punten", alleen_aangevinkt=True)
        assert {i.atleet_id for i in db.ploeg_inzet(p.id)} == {ids["bo"]}
        assert o.na >= o.voor
        o = paginas.optimaliseren(db, p.id, "max_punten", alleen_aangevinkt=False)
        assert {i.atleet_id for i in db.ploeg_inzet(p.id)} >= {ids["anna"], ids["bo"]}


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
