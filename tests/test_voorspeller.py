"""Tests voor stap 6: de voorspeller (ploeg/voorspeller.py) en estafettes
(ploeg/estafettes.py), en hoe die meetellen in de stand, de optimalisatie, de
pagina en de csv.

Alleen nepgegevens.
"""

import copy
import dataclasses
import itertools
import random
from datetime import date

import yaml
from test_ploegen import BESTAND, DAG, JAAR, opslag

from atleten import beheer
from models import Atleet, Inzet, Ploeg, PloegLid, Prestatie
from ploeg import estafettes, opstelling, punten, regels, strategieen, vergelijk
from ploeg.config import config_map
from ploeg.optimaliseer import optimaliseer
from ploeg.vergelijk import Cel, Matrix, Rij
from ploeg.voorspeller import Beentijd
from hulp import app_client, verwacht as _verwacht

RS = regels.laad(BESTAND)
PT = punten.puntentelling(RS.puntentelling)


def _p(onderdeel: str, waarde: float, geslacht: str = "V") -> int:
    return PT.punten(RS.puntentabel, onderdeel, geslacht, waarde)


def _ruw(bestand: str = BESTAND) -> dict:
    return yaml.safe_load((config_map() / "ploeg_regels" / f"{bestand}.yaml").read_text(encoding="utf-8"))


# ------------------------------------------------------------
# Voorspeller
# ------------------------------------------------------------
def _matrix(db, ids, wie=("anna", "bo", "cato"), rs=RS, programma="wedstrijd_1"):
    return vergelijk.matrix(db, rs, "U16-V", programma, DAG, [db.atleet(ids[k]) for k in wie])


def test_voorspelling_uit_buuronderdeel():
    """Anna heeft 80 m (10,60) maar geen 150 m: punten x 0.95 -> de zwakste 150 m-tijd met die punten."""
    with opslag() as (db, _, ids):
        m = _matrix(db, ids, programma="wedstrijd_2")          # 150m, 1500m, 80mH, ...
        c = m.cel(ids["anna"], "150m")
        verwacht = int(_p("80m", 10.60) * 0.95)
        assert c.voorspeld and c.datum is None
        assert c.punten == _p("150m", c.waarde) >= verwacht
        assert c.waarde == PT.prestatie_voor(RS.puntentabel, "150m", "V", verwacht)
        assert c.bron == "voorspeld uit 80 meter: 10,60"
        # een echte prestatie gaat altijd voor: Anna's 80 m in wedstrijd_1 is niet voorspeld
        assert not _matrix(db, ids).cel(ids["anna"], "80m").voorspeld


def test_beste_bron_telt_en_handtijd():
    """Cato heeft alleen een handtijd op de 80 m: de voorspelling rekent met de correctie."""
    with opslag() as (db, _, ids):
        c = _matrix(db, ids, programma="wedstrijd_2").cel(ids["cato"], "150m")
        bron = PT.punten(RS.puntentabel, "80m", "V", 10.80, handtijd=True)
        assert c.voorspeld and c.punten >= int(bron * 0.95) and "(hand)" in c.bron


def test_voorspelling_ander_materiaal():
    with opslag() as (db, _, ids):
        c = _matrix(db, ids).cel(ids["cato"], "kogelstoten")     # 2 kg 9,80 -> 3 kg
        omgerekend = 9.80 * 0.87 / 1.0
        assert c.voorspeld and c.punten >= int(_p("kogelstoten", omgerekend) * 0.95)
        assert c.waarde < omgerekend


def test_geen_voorspelling_met_factor_nul_of_zonder_bron():
    rs0 = dataclasses.replace(RS, voorspelling_factor=0)
    with opslag() as (db, _, ids):
        m = _matrix(db, ids, rs=rs0)
        assert not any(c.voorspeld for r in m.rijen for c in r.cellen.values())
        assert m.cel(ids["cato"], "kogelstoten").hint == "2kg: 9,80 m"       # de hint blijft
        # hoogspringen heeft geen buren: niemand krijgt een voorspelling
        assert not _matrix(db, ids).cel(ids["anna"], "hoogspringen").voorspeld


def test_waarschuwing_voorspeld():
    with opslag() as (db, _, ids):
        m = _matrix(db, ids)
        p = db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG))
        inzet = [Inzet(ids["cato"], "kogelstoten")]
        uit = opstelling.controleer(db, RS, p, [PloegLid(ids["cato"])], inzet, m)
        assert any(o.code == "voorspeld" and o.ernst == "waarschuwing" for o in uit)
        assert not any(o.code == "geen_prestatie" for o in uit)


def test_regelbestand_controleert_voorspelling_en_estafettes():
    def fout(aanpassen, tekst):
        ruw = _ruw()
        aanpassen(ruw)
        try:
            regels.Regelset.uit_dict(ruw)
        except regels.RegelFout as e:
            assert tekst in str(e), e
        else:
            raise AssertionError(f"RegelFout verwacht ({tekst})")

    fout(lambda r: r["onderdelen"]["80m"].update(buren=["200m"]), "staat niet onder 'onderdelen'")
    fout(lambda r: r["onderdelen"]["80m"].update(buren=["4x80m"]), "geen estafette")
    fout(lambda r: r["onderdelen"]["4x80m"].update(benen=["80m", "80m"]), "één onderdeel per loper")
    fout(lambda r: r["onderdelen"]["80m"].update(correctie_s=-1), "horen bij een estafette")
    fout(lambda r: r["onderdelen"]["4x80m"].update(correctie_s="snel"), "aantal seconden")
    fout(lambda r: r["onderdelen"]["kogelstoten"].update(verhouding={"2kg": 0}), "boven 0")
    fout(lambda r: r["algemeen"].update(voorspelling_factor=1.5), "voorspelling_factor")
    fout(lambda r: r["onderdelen"].update(x={"naam": "X", "benen": ["80m"]}), "horen bij een estafette")
    # gemengde estafette: benen met geslacht moeten bij de samenstelling passen
    sen = _ruw("senioren_1e_divisie_2026-2027")
    sen["onderdelen"]["4x400m-gemengd"]["benen"] = ["400m-M", "400m-M", "400m-M", "400m-V"]
    _verwacht(regels.RegelFout, lambda: regels.Regelset.uit_dict(sen))
    # alle meegeleverde bestanden laden
    for b in regels.bestanden():
        regels.laad(b)


# ------------------------------------------------------------
# Estafettes
# ------------------------------------------------------------
REGELS = RS.programma("U16-V", "wedstrijd_1")


def nep_matrix(tijden: dict[str, dict[str, float]], regels_=REGELS, rs=RS, ploeg="U16-V",
               programma="wedstrijd_1", categorie="U16-V") -> Matrix:
    rijen, been = [], {}
    for mid, t in tijden.items():
        cat = categorie(mid) if callable(categorie) else categorie
        rij = Rij(Atleet(mid[:4], "Nep", geslacht=cat[-1], master_id=mid), cat, True)
        for r in regels_:
            rij.cellen[r.sleutel] = Cel(r.sleutel, r.naam)
        rijen.append(rij)
        been[mid] = {b: Beentijd(v) for b, v in t.items()}
    return Matrix(rs, ploeg, programma, DAG, "seizoen", regels_, rijen, been)


def _id(i: int) -> str:
    return f"{i:x}" * 32


def test_schatting_4x80():
    tijden = {_id(i): {"80m": 10.0 + i / 10} for i in range(1, 6)}
    m = nep_matrix(tijden)
    lopers = [_id(i) for i in (1, 2, 3, 4)]
    s = estafettes.schat(m, "4x80m", lopers)
    tijd = round(10.1 + 10.2 + 10.3 + 10.4 - 1.0, 2)                  # correctie_s: -1.0
    assert s.tijd == tijd and s.punten == _p("4x80m", tijd) and not s.voorspeld
    assert estafettes.schat(m, "4x80m", lopers[:3]) is None             # te weinig lopers
    assert estafettes.schat(m, "80m", lopers) is None                   # geen estafette
    m.beentijden[_id(4)] = {"80m": Beentijd(10.4, voorspeld=True)}
    assert estafettes.schat(m, "4x80m", lopers).voorspeld


def test_opties_beste_eerst():
    tijden = {_id(i): {"80m": 10.0 + i / 10} for i in range(1, 7)}
    m = nep_matrix(tijden)
    m.rijen[5].cellen["4x80m"].nvt = True                               # mag niet: valt af
    o = estafettes.opties(m, "4x80m", tijden)
    assert len(o) == 5                                                   # C(5, 4)
    assert set(o[0].lopers) == {_id(i) for i in (1, 2, 3, 4)}
    assert [s.punten for s in o] == sorted((s.punten for s in o), reverse=True)


def test_zweedse_kiest_de_beste_verdeling():
    rs = regels.laad("u18_u20_2026-2027")
    regels_ = rs.programma("U18U20-V", "wedstrijd_2")
    t = {
        _id(1): {"100m": 12.0, "200m": 25.0, "300m": 40.0, "400m": 56.0},   # sprinter
        _id(2): {"100m": 12.5, "200m": 25.5, "300m": 39.0, "400m": 54.0},   # 400m-loopster
        _id(3): {"100m": 12.6, "200m": 25.2, "300m": 41.0, "400m": 58.0},
        _id(4): {"100m": 13.0, "200m": 26.0, "300m": 42.0, "400m": 59.0},
    }
    m = nep_matrix(t, regels_, rs, "U18U20-V", "wedstrijd_2", "U18-V")
    s = estafettes.schat(m, "zweedse", list(t))
    beste = min(sum(t[a][b] for a, b in zip(p, ["100m", "200m", "300m", "400m"]))
                for p in itertools.permutations(t))
    assert s.tijd == round(beste - 1.5, 2)
    assert s.lopers[3] == _id(2)                                         # de 400m-loopster loopt de 400


def test_gemengde_estafette_samenstelling():
    rs = regels.laad("senioren_1e_divisie_2026-2027")
    regels_ = rs.programma("SEN", "wedstrijd_2")
    ids = [_id(i) for i in range(1, 7)]
    geslacht = {ids[0]: "M", ids[1]: "M", ids[2]: "M", ids[3]: "V", ids[4]: "V", ids[5]: "V"}
    t = {a: {f"400m-{g}": 50.0 + i} for i, (a, g) in enumerate(geslacht.items())}
    m = nep_matrix(t, regels_, rs, "SEN", "wedstrijd_2", lambda a: f"SEN-{geslacht[a]}")
    assert estafettes.schat(m, "4x400m-gemengd", ids[:3] + ids[3:4]) is None       # 3 M + 1 V
    s = estafettes.schat(m, "4x400m-gemengd", ids[:2] + ids[3:5])
    assert s.tijd == round(50 + 51 + 53 + 54 - 2.0, 2)
    assert s.punten == PT.punten("au_senioren", "4x400m-gemengd", "M", s.tijd)
    o = estafettes.opties(m, "4x400m-gemengd", ids)
    assert len(o) == 9 and all(sum(geslacht[a] == "M" for a in k.lopers) == 2 for k in o)


def test_stand_telt_estafette():
    tijden = {_id(i): {"80m": 10.0 + i / 10} for i in range(1, 6)}
    m = nep_matrix(tijden)
    inzet = [Inzet(_id(i), "4x80m") for i in (1, 2, 3, 4)]
    s = opstelling.stand(m, inzet)
    est = s.onderdelen["4x80m"]
    assert est.schatting is not None and est.punten == est.schatting.punten > 0
    assert s.totaal == est.punten and not s.estafettes_zonder_punten
    # vijf lopers of een loper zonder tijd: geen punten, wel gemeld
    assert opstelling.stand(m, inzet + [Inzet(_id(5), "4x80m")]).estafettes_zonder_punten
    del m.beentijden[_id(4)]
    assert opstelling.stand(m, inzet).estafettes_zonder_punten


# ------------------------------------------------------------
# Optimaliseren met estafettes
# ------------------------------------------------------------
KLEIN = [r for r in REGELS if r.sleutel in ("80m", "800m", "kogelstoten", "4x80m")]


def _klein(zaad: int) -> tuple[Matrix, list[str]]:
    rnd = random.Random(zaad)
    ids = [_id(i) for i in range(1, 6)]
    m = nep_matrix({a: {"80m": round(rnd.uniform(10.0, 11.5), 2)} for a in ids}, KLEIN)
    for rij in m.rijen:
        for r in KLEIN:
            if r.soort != "estafette":
                rij.cellen[r.sleutel].waarde, rij.cellen[r.sleutel].punten = 1.0, rnd.randint(100, 700)
    return m, ids


def _brute(m: Matrix, ids: list[str]) -> int:
    individueel = [r.sleutel for r in KLEIN if r.soort != "estafette"]
    keuzes = [c for k in range(len(individueel) + 1) for c in itertools.combinations(individueel, k)]
    kwartetten = [None] + [estafettes.schat(m, "4x80m", k) for k in itertools.combinations(ids, 4)]
    regels_ = {r.sleutel: r for r in KLEIN}
    beste = 0
    for kw in kwartetten:
        loopt = set(kw.lopers) if kw else set()
        for combinatie in itertools.product(keuzes, repeat=len(ids)):
            if any(len(c) + (a in loopt) > 3 for a, c in zip(ids, combinatie)):
                continue
            per = {}
            for a, c in zip(ids, combinatie):
                for o in c:
                    per.setdefault(o, []).append(m.punten(a, o))
            if any(len(v) > regels_[o].max_atleten for o, v in per.items()):
                continue
            totaal = sum(sum(sorted(v, reverse=True)[:regels_[o].tellend]) for o, v in per.items())
            beste = max(beste, totaal + (kw.punten if kw else 0))
    return beste


def test_optimaliseren_kiest_kwartet_zoals_brute_kracht():
    for zaad in (1, 5):
        m, ids = _klein(zaad)
        r = optimaliseer(m, RS, strategieen.strategie("max_punten"), ids, [], [], False)
        s = opstelling.stand(m, r.inzet)
        assert s.onderdelen["4x80m"].schatting is not None
        assert s.totaal == _brute(m, ids), zaad
        assert max(s.per_atleet.values()) <= 3


def test_estafette_blijft_als_vastgezet_of_zonder_tijden():
    m, ids = _klein(2)
    huidig = [Inzet(a, "4x80m") for a in ids[1:]]
    # vastzetten: het kwartet van de trainer blijft
    leden = [PloegLid(a) for a in ids]
    r = optimaliseer(m, RS, strategieen.strategie("max_punten"), ids, leden, huidig, vastzetten=True)
    assert {i.atleet_id for i in r.inzet if i.onderdeel == "4x80m"} == set(ids[1:])
    # zonder vastzetten kiest de optimalisatie zelf het kwartet
    r = optimaliseer(m, RS, strategieen.strategie("max_punten"), ids, leden, huidig, vastzetten=False)
    assert opstelling.stand(m, r.inzet).onderdelen["4x80m"].schatting is not None
    # geen beentijden: niets te kiezen, dus blijft staan (en telt mee voor de 3 onderdelen)
    m2 = copy.copy(m)
    m2.beentijden = {}
    r = optimaliseer(m2, RS, strategieen.strategie("max_punten"), ids, leden, huidig, False)
    assert {i.atleet_id for i in r.inzet if i.onderdeel == "4x80m"} == set(ids[1:])


def test_alle_strategieen_met_estafette():
    m, ids = _klein(3)
    for naam in strategieen.STRATEGIEEN:
        r = optimaliseer(m, RS, strategieen.strategie(naam), ids, [], [], False)
        fouten = [o for o in RS.controleer("U16-V", "wedstrijd_1", r.leden, r.inzet, m.categorieen)
                  if o.ernst == "fout"]
        assert not fouten, (naam, fouten)
    r = optimaliseer(m, RS, strategieen.strategie("minimaal_twee"), ids, [], [], False)
    per = {}
    for i in r.inzet:
        per[i.atleet_id] = per.get(i.atleet_id, 0) + 1
    assert all(n >= 2 for n in per.values())


# ------------------------------------------------------------
# Pagina en csv
# ------------------------------------------------------------
def test_pagina_en_csv_met_voorspelling_en_estafette():
    with opslag() as (db, tmp, ids):
        eva = beheer.nieuwe_atleet(db, "Eva", "Proef", geslacht="V", geboortedatum=f"{JAAR - 15}-01-01").master_id
        o = next(x for x in db.onderdelen() if x.naam == "80 meter")
        db.prestatie_opslaan(Prestatie("80 meter", date(JAAR, 4, 20), 11.20, atleet_id=eva, onderdeel_id=o.id,
                                       wind=0.0))
        p = db.ploeg_opslaan(Ploeg("U16 A", BESTAND, "U16-V", "wedstrijd_1", DAG))
        meisjes = [ids["anna"], ids["bo"], ids["cato"], eva]
        inzet = [Inzet(a, "4x80m") for a in meisjes] + [Inzet(ids["cato"], "kogelstoten")]
        db.ploeg_opstelling_opslaan(p.id, [PloegLid(a) for a in meisjes], inzet)
        db.sluit()
        c = app_client(tmp)
        html = c.get(f"/ploeg/{p.id}").get_data(as_text=True)
        assert "ploegcel--voorspeld" in html and "voorspeld uit Kogelstoten 2kg" in html
        assert "Geschat:" in html and "nog niet mee" not in html            # estafette telt mee
        assert 'title="Tijd op het estafettebeen (≈ = voorspeld)">11,20<' in html   # beentijd in de cel
        csv = c.get(f"/ploeg/{p.id}/atletieknu.csv").get_data().decode("utf-8-sig").splitlines()
        kop = csv[0].split(";")
        cato = next(r.split(";") for r in csv[1:] if r.split(";")[1].startswith("Cato"))
        assert cato[kop.index("Kogelstoten")] == "x"                         # geen echte prestatie: geen waarde
        assert cato[kop.index("4 x 80 meter")] == "x"
