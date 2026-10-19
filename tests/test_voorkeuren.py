"""Tests voor voorkeuren van atleten (ploeg/voorkeuren.py, migratie personen/011):
vaste voorkeuren per atleet, voorkeuren per ploeg, wat de optimalisatie en de
controle ermee doen, en de pagina's.

Alleen nepgegevens. Werkt met pytest en los: `python tests/test_voorkeuren.py`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_landingspagina import TESTSLEUTEL  # noqa: E402
from test_optimaliseer import nep_matrix  # noqa: E402
from test_ploegen import BESTAND, DAG, _verwacht, opslag  # noqa: E402

from db.queries import Opslag, OpslagFout  # noqa: E402
from models import Inzet, Ploeg, PloegLid  # noqa: E402
from ploeg import opstelling, paginas, regels, strategieen, voorkeuren  # noqa: E402
from ploeg.optimaliseer import OptimalisatieFout, optimaliseer  # noqa: E402
from ploeg.voorkeuren import Effectief  # noqa: E402
from ui.app import maak_app  # noqa: E402

RS = regels.laad(BESTAND)


def _ploeg(db) -> Ploeg:
    return db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG))


# ------------------------------------------------------------
# Opslaan
# ------------------------------------------------------------
def test_opslaan_lezen_en_verwijderen():
    with opslag() as (db, tmp, ids):
        anna = ids["anna"]
        db.atleet_voorkeuren_opslaan(anna, {"Kogelstoten": "wil_niet", "  800   meter ": "voorkeur"})
        assert db.atleet_voorkeuren(anna) == {"800 meter": "voorkeur", "Kogelstoten": "wil_niet"}
        db.atleet_voorkeuren_opslaan(anna, {"Hoogspringen": "moet"})                  # vervangt alles
        assert db.atleet_voorkeuren(anna) == {"Hoogspringen": "moet"}
        _verwacht(OpslagFout, lambda: db.atleet_voorkeuren_opslaan(anna, {"Hoogspringen": "misschien"}))
        _verwacht(OpslagFout, lambda: db.atleet_voorkeuren_opslaan("f" * 32, {"Hoogspringen": "moet"}))
        _verwacht(OpslagFout, lambda: db.atleet_voorkeuren_opslaan(anna, {"Hoogspringen": "neutraal"}))

        p = _ploeg(db)
        db.ploeg_voorkeuren_opslaan(p.id, {(anna, "80m"): "moet", (anna, "hoogspringen"): "neutraal"})
        assert db.ploeg_voorkeuren(p.id) == {(anna, "80m"): "moet", (anna, "hoogspringen"): "neutraal"}
        _verwacht(OpslagFout, lambda: db.ploeg_voorkeuren_opslaan(p.id, {(anna, "80m"): "graag"}))
        _verwacht(OpslagFout, lambda: db.ploeg_voorkeuren_opslaan(999, {}))

        db.atleet_verwijderen(anna)                                                 # AVG: alles weg
        assert db.atleet_voorkeuren(anna) == {} and db.ploeg_voorkeuren(p.id) == {}


def test_ploeg_weg_dan_voorkeuren_weg():
    with opslag() as (db, _, ids):
        p = _ploeg(db)
        db.ploeg_voorkeuren_opslaan(p.id, {(ids["bo"], "80m"): "voorkeur"})
        db.ploeg_verwijderen(p.id)
        n = db.personen.execute("SELECT COUNT(*) FROM ploeg_voorkeur").fetchone()[0]
        assert n == 0


# ------------------------------------------------------------
# Wat geldt
# ------------------------------------------------------------
def test_effectief_vast_ploeg_en_neutraal():
    with opslag() as (db, _, ids):
        anna, bo = ids["anna"], ids["bo"]
        db.atleet_voorkeuren_opslaan(anna, {"kogelstoten": "wil_niet", "80 Meter Horden": "voorkeur",
                                            "Hoogspringen": "moet"})
        p = _ploeg(db)
        db.ploeg_voorkeuren_opslaan(p.id, {(anna, "80mH"): "moet", (anna, "hoogspringen"): "neutraal",
                                           (bo, "800m"): "wil_niet"})
        vk = voorkeuren.effectief(db, RS, p, [anna, bo])
        assert vk[(anna, "kogelstoten")] == Effectief("wil_niet", "atleet")     # naam zonder spec, elke case
        assert vk[(anna, "80mH")] == Effectief("moet", "ploeg")                 # ploeg gaat voor
        assert (anna, "hoogspringen") not in vk                                 # neutraal: vaste geldt hier niet
        assert vk[(bo, "800m")].tekst == "Wil niet" and vk[(anna, "kogelstoten")].tekst == "Wil niet (vast)"
        assert len(vk) == 3


def test_onderdeelnamen_per_groep():
    groepen = voorkeuren.onderdeelnamen()
    assert "Kogelstoten" in groepen["Werpen"] and "80 meter horden" in groepen["Horden en steeple"]
    assert "4 x 80 meter" in groepen["Estafettes"] and "Hoogspringen" in groepen["Springen"]
    lopen = groepen["Lopen"]
    assert lopen.index("60 meter") < lopen.index("100 meter") < lopen.index("1500 meter")
    assert len({n.lower() for g in groepen.values() for n in g}) == sum(len(g) for g in groepen.values())


# ------------------------------------------------------------
# Optimaliseren en controleren
# ------------------------------------------------------------
def test_wil_niet_en_moet_in_de_optimalisatie():
    m, ids = nep_matrix(4, 5, leeg=0)
    a = ids[0]
    vrij = optimaliseer(m, RS, strategieen.strategie("max_punten"), ids, [], [], False)
    hare = {i.onderdeel for i in vrij.inzet if i.atleet_id == a}
    assert hare
    niet = sorted(hare)[0]
    moet = next(r.sleutel for r in m.regels if r.soort != "estafette" and r.sleutel not in hare)
    r = optimaliseer(m, RS, strategieen.strategie("max_punten"), ids, [], [], False,
                     voorkeuren={(a, niet): "wil_niet", (a, moet): Effectief("moet", "ploeg")})
    nu = {i.onderdeel for i in r.inzet if i.atleet_id == a}
    assert niet not in nu and moet in nu
    # een 'moet' van iemand die niet meedoet (reserve / niet in de groep) telt niet
    r = optimaliseer(m, RS, strategieen.strategie("max_punten"), ids[1:], [], [], False,
                     voorkeuren={(a, moet): "moet"})
    assert a not in {i.atleet_id for i in r.inzet}
    # te veel 'moet': duidelijke fout
    vier = [x.sleutel for x in m.regels if x.soort != "estafette"][:4]
    try:
        optimaliseer(m, RS, strategieen.strategie("max_punten"), ids, [], [], False,
                     voorkeuren={(a, e): "moet" for e in vier})
    except OptimalisatieFout as e:
        assert "moet" in str(e)
    else:
        raise AssertionError("OptimalisatieFout verwacht")


def test_voorkeur_kost_geen_punten():
    m, ids = nep_matrix(5, 8, leeg=0)
    s = strategieen.strategie("max_punten")
    zonder = optimaliseer(m, RS, s, ids, [], [], False)
    totaal = opstelling.stand(m, zonder.inzet).totaal
    gekozen = {(i.atleet_id, i.onderdeel) for i in zonder.inzet}
    per = {}
    for i in zonder.inzet:
        per[i.atleet_id] = per.get(i.atleet_id, 0) + 1
    # iemand met ruimte een onderdeel geven waar ze nu niet op staat
    a = next(x for x in ids if per.get(x, 0) < 3)
    graag = [(a, r.sleutel) for r in m.regels if r.soort != "estafette" and (a, r.sleutel) not in gekozen]
    met = optimaliseer(m, RS, s, ids, [], [], False, voorkeuren={k: "voorkeur" for k in graag})
    assert opstelling.stand(m, met.inzet).totaal == totaal                          # geen punten kwijt
    assert {(i.atleet_id, i.onderdeel) for i in met.inzet} & set(graag)            # wel een voorkeur gekregen
    for naam in strategieen.STRATEGIEEN:                                             # elke strategie kan ermee
        optimaliseer(m, RS, strategieen.strategie(naam), ids, [], [], False, voorkeuren={k: "voorkeur" for k in graag})


def test_controle_waarschuwt():
    with opslag() as (db, _, ids):
        anna, bo = ids["anna"], ids["bo"]
        p = _ploeg(db)
        pg = paginas.ploegpagina(db, p.id)
        vk = {(anna, "80m"): Effectief("wil_niet", "atleet"), (bo, "verspringen"): Effectief("moet", "ploeg"),
              (anna, "800m"): Effectief("moet", "ploeg")}
        uit = opstelling.controleer(db, RS, p, [PloegLid(anna), PloegLid(bo)], [Inzet(anna, "80m"), Inzet(anna, "800m")],
                                    pg.matrix, voorkeuren=vk)
        codes = {(o.code, o.atleet_id, o.onderdeel): o for o in uit}
        assert ("wil_niet", anna, "80m") in codes and "vaste voorkeur" in codes[("wil_niet", anna, "80m")].tekst
        assert ("moet", bo, "verspringen") in codes                                   # bo staat er niet op
        assert ("moet", anna, "800m") not in codes
        assert all(o.ernst == "waarschuwing" for o in uit if o.code in ("wil_niet", "moet"))


def test_optimaliseren_via_pagina_gebruikt_voorkeuren():
    with opslag() as (db, _, ids):
        anna = ids["anna"]
        db.atleet_voorkeuren_opslaan(anna, {"80 meter": "wil_niet"})
        p = _ploeg(db)
        paginas.optimaliseren(db, p.id, "max_punten", alleen_aangevinkt=False)
        assert (anna, "80m") not in {(i.atleet_id, i.onderdeel) for i in db.ploeg_inzet(p.id)}
        db.ploeg_voorkeuren_opslaan(p.id, {(anna, "80m"): "neutraal"})              # deze keer wel
        paginas.optimaliseren(db, p.id, "max_punten", alleen_aangevinkt=False)
        assert (anna, "80m") in {(i.atleet_id, i.onderdeel) for i in db.ploeg_inzet(p.id)}


# ------------------------------------------------------------
# Pagina's
# ------------------------------------------------------------
def test_paginas():
    with opslag() as (db, tmp, ids):
        anna, bo = ids["anna"], ids["bo"]
        p = _ploeg(db)
        db.ploeg_opstelling_opslaan(p.id, [PloegLid(bo)], [Inzet(bo, "80m")])
        db.sluit()
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()

        assert f"/atleet/{anna}/voorkeuren" in c.get(f"/atleet/{anna}").get_data(as_text=True)
        html = c.get(f"/atleet/{anna}/voorkeuren").get_data(as_text=True)
        assert 'name="vk|Kogelstoten"' in html and "Horden en steeple" in html
        r = c.post(f"/atleet/{anna}/voorkeuren", data={"vk|Kogelstoten": "wil_niet", "vk|80 meter": "voorkeur",
                                                       "vk|Hoogspringen": "onzin", "vk|Bestaat niet": "moet"})
        assert r.status_code == 302
        assert "Voorkeuren voor ploegen opgeslagen (2 ingesteld)." in c.get(r.location).get_data(as_text=True)
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db2:
            assert db2.atleet_voorkeuren(anna) == {"Kogelstoten": "wil_niet", "80 meter": "voorkeur"}
        assert c.get(f"/atleet/{'f' * 32}/voorkeuren").status_code == 404

        html = c.get(f"/ploeg/{p.id}/voorkeuren").get_data(as_text=True)
        assert f'name="vk|{anna}|kogelstoten"' in html and "vast: wil niet" in html
        assert html.index("Bo Proef") < html.index("Anna Proef")                        # leden eerst
        r = c.post(f"/ploeg/{p.id}/voorkeuren", data={f"vk|{anna}|kogelstoten": "neutraal",
                                                      f"vk|{bo}|800m": "moet", f"vk|{bo}|80m": ""})
        assert r.status_code == 302
        html = c.get(f"/ploeg/{p.id}").get_data(as_text=True)
        assert "Voorkeuren voor deze ploeg opgeslagen (2 ingesteld)." in html
        assert 'ploegcel__voorkeur--moet' in html and 'ploegcel__voorkeur--voorkeur' in html    # bo 800m, anna 80m
        assert "Moet 800 meter doen, maar staat er niet op." in html
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db2:
            assert db2.ploeg_voorkeuren(p.id) == {(anna, "kogelstoten"): "neutraal", (bo, "800m"): "moet"}


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
