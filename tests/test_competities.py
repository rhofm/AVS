"""Tests voor de regelbestanden van U18/U20, masters, senioren (1e, 2e, 3e divisie)
en NK Teams, en wat daarvoor in ploeg/regels.py en ploeg/vergelijk.py nodig is:
gemengde ploegen (onderdelen met een geslacht), 'alleen' (steeple U18),
materiaal van de eigen categorie (U16 als U18), masters per leeftijdsklasse.

Verwachte programma's uit de Wedstrijdbepalingen Competitie 2026-2027
(bepalingen 30, 40, 50, 52, 60, 62). Alleen nep-atleten.

"""

from datetime import date

from atleten import beheer
from models import Inzet, Onderdeel, PloegLid, Prestatie
from ploeg import regels, vergelijk
from ploeg.regels import masters_code
from hulp import lege_opslag

E1, E2, E3 = (f"senioren_{d}_divisie_2026-2027" for d in ("1e", "2e", "3e"))
NK, U18U20, MASTERS = "nk_teams_2026-2027", "u18_u20_2026-2027", "masters_2026-2027"
A, B, C, D = (c * 32 for c in "abcd")


def prog(bestand, ploeg, programma) -> dict[str, int]:
    return {r.sleutel: r.max_atleten for r in regels.laad(bestand).programma(ploeg, programma)}


def test_alle_bestanden_laden():
    alle = regels.bestanden()
    for b in (E1, E2, E3, NK, U18U20, MASTERS, "u14_u16_2026-2027"):
        assert b in alle, b
        rs = regels.laad(b)
        for p in rs.ploegen:
            for pr in rs.programmas(p):
                assert rs.programma(p, pr), (b, p, pr)


# ------------------------------------------------------------
# Senioren
# ------------------------------------------------------------
def test_senioren_programmas():
    # 1e divisie, 1e wedstrijd (bepaling 40)
    w1 = prog(E1, "SEN", "wedstrijd_1")
    assert len(w1) == 28
    assert w1["1500m-V"] == 2 and w1["3000mSC-M"] == 1 and w1["4x100m-V"] == 1
    assert "3000m-V" not in w1 and "4x400m-gemengd" not in w1
    assert prog(E1, "SEN", "wedstrijd_2")["4x400m-gemengd"] == 1
    # 2e divisie, 2e wedstrijd; 3e divisie, hoogspringen maar 1 atleet
    w2 = prog(E2, "SEN", "wedstrijd_2")
    assert w2["3000mSC-V"] == 1 and w2["kogelslingeren-V"] == 2 and "800m-M" not in w2
    assert prog(E3, "SEN", "wedstrijd_1")["hoogspringen-V"] == 1
    assert prog(E3, "SEN", "wedstrijd_1")["3000m-V"] == 2
    # NK Teams: één atleet per onderdeel, 18 per geslacht + gemengde estafette
    nk = prog(NK, "SEN", "nk_teams")
    assert len(nk) == 37 and set(nk.values()) == {1} and "5000m-M" in nk and "100mH-V" in nk


def test_senioren_promotie_degradatie():
    # 42.4/42.5: in 2026 het programma van de 3e wedstrijd, in 2027 dat van de 2e
    assert prog(E1, "SEN", "pd_2e_divisie_2026") == prog(E1, "SEN", "wedstrijd_3")
    assert prog(E2, "SEN", "pd_1e_divisie_2027") == prog(E1, "SEN", "wedstrijd_2")
    assert prog(E3, "SEN", "pd_2e_divisie_2026") == prog(E2, "SEN", "wedstrijd_3")
    assert prog(E1, "SEN", "pd_nk_teams") == prog(NK, "SEN", "nk_teams")          # 42.3
    rs = regels.laad(E2)
    assert rs.programma_naam("pd_3e_divisie_2027").startswith("Promotie/degradatie met de 3e divisie 2027")
    assert rs.programma_naam("wedstrijd_1") == "Wedstrijd 1"
    assert regels.laad(E1).puntentoekenning == "plaats" and rs.puntentoekenning == "prestatie"


def test_senioren_gemengde_ploeg():
    rs = regels.laad(E3)
    sen = rs.ploeg("SEN")
    assert sen.geslacht == "gemengd"
    assert rs.mag_meedoen("SEN", "U18-V") and rs.mag_meedoen("SEN", "SEN-M") and not rs.mag_meedoen("SEN", "U16-M")
    r = {x.sleutel: x for x in rs.programma("SEN", "wedstrijd_1")}
    assert r["100m-V"].kop == "100 meter (V)" and r["100m-V"].tellend == 1
    assert rs.onderdeel_naam("SEN", "kogelstoten-M", "U20-M") == "Kogelstoten 7,26kg"       # seniorenmateriaal
    leden = [PloegLid(x) for x in (A, B)]
    cat = {A: "SEN-V", B: "SEN-M"}
    uit = rs.controleer("SEN", "wedstrijd_1", leden, [Inzet(A, "100m-V"), Inzet(B, "100m-V")], cat)
    assert [(o.code, o.atleet_id) for o in uit] == [("past_niet", B)] and "vrouwen" in uit[0].tekst


def test_gemengde_estafette_2_mannen_2_vrouwen():
    rs = regels.laad(E3)
    leden = [PloegLid(x) for x in (A, B, C, D)]
    inzet = [Inzet(x, "4x400m-gemengd") for x in (A, B, C, D)]
    goed = {A: "SEN-V", B: "U20-V", C: "SEN-M", D: "U18-M"}
    assert rs.controleer("SEN", "wedstrijd_3", leden, inzet, goed) == []
    fout = {**goed, D: "SEN-V"}
    assert [o.code for o in rs.controleer("SEN", "wedstrijd_3", leden, inzet, fout)] == ["samenstelling"]


# ------------------------------------------------------------
# U18/U20
# ------------------------------------------------------------
def test_u18_u20_programma_en_materiaal():
    w2 = prog(U18U20, "U18U20-V", "wedstrijd_2")
    assert w2["2000mSC"] == 2 and w2["zweedse"] == 1 and "3000m" not in w2
    assert set(prog(U18U20, "U18U20-M", "finale_2027")) == {
        "100m", "200m", "800m", "3000m", "400mH", "4x400m", "hoogspringen", "polsstokhoogspringen",
        "verspringen", "kogelstoten", "speerwerpen"}
    rs = regels.laad(U18U20)
    assert rs.mag_meedoen("U18U20-V", "U16-V") and not rs.mag_meedoen("U18U20-V", "U14-V")
    assert rs.onderdeel_naam("U18U20-V", "kogelstoten", "U16-V") == "Kogelstoten 3kg"     # U16 = U18
    assert rs.onderdeel_naam("U18U20-V", "kogelstoten", "U20-V") == "Kogelstoten 4kg"
    assert rs.onderdeel_naam("U18U20-M", "110mH", "U18-M") == "110 meter horden 91,4cm"


def test_steeple_alleen_u18():
    rs = regels.laad(U18U20)
    leden = [PloegLid(A), PloegLid(B), PloegLid(C)]
    cat = {A: "U18-V", B: "U20-V", C: "U16-V"}
    inzet = [Inzet(x, "2000mSC") for x in (A, B)]
    uit = rs.controleer("U18U20-V", "wedstrijd_2", leden, inzet, cat)
    assert [(o.code, o.atleet_id) for o in uit] == [("past_niet", B)]
    assert rs.controleer("U18U20-V", "wedstrijd_2", leden, [Inzet(C, "2000mSC")], cat) == []   # U16 als U18


# ------------------------------------------------------------
# Masters
# ------------------------------------------------------------
def test_masters():
    assert masters_code("V", 47) == "V45" and masters_code("M", 35) == "M35" and masters_code("M", 34) is None
    assert masters_code("V", 101) == "V95" and masters_code(None, 50) is None
    rs = regels.laad(MASTERS)
    assert rs.leeftijdsklassen == "masters"
    assert rs.mag_meedoen("MAS-V", "V35") and rs.mag_meedoen("MAS-V", "V70")
    assert not rs.mag_meedoen("MAS-V", "M40") and not rs.mag_meedoen("MAS-V", "SEN-V")
    assert rs.onderdeel_naam("MAS-V", "kogelstoten", "V45") == "Kogelstoten 4kg"
    assert rs.onderdeel_naam("MAS-V", "kogelstoten", "V55") == "Kogelstoten 3kg"          # vanaf V50
    assert rs.onderdeel_naam("MAS-V", "kogelstoten", "V80") == "Kogelstoten 2kg"
    assert rs.onderdeel_naam("MAS-M", "speerwerpen", "M65") == "Speerwerpen 600g"
    assert set(prog(MASTERS, "MAS-M", "finale")) >= {"5000m", "4x200m", "kogelslingeren"}
    assert prog(MASTERS, "MAS-V", "wedstrijd_2")["kogelslingeren"] == 2


def test_fouten_in_nieuwe_velden():
    def laad(ploeg, onderdeel):
        return regels.Regelset.uit_dict({
            "naam": "T", "puntentelling": "au_2025", "puntentabel": "au_senioren",
            "ploegen": {"SEN": {"geslacht": "gemengd", "toegestaan": ["SEN-V"], "programma": {"w": {"x": 1}}, **ploeg}},
            "onderdelen": {"x": {"naam": "100 meter", "punten": "100m", **onderdeel}}}, "test")

    def fout(ploeg, onderdeel):
        try:
            laad(ploeg, onderdeel)
        except regels.RegelFout as e:
            return str(e)
        raise AssertionError("RegelFout verwacht")

    laad({}, {"geslacht": "V"})                                              # goed
    assert "geslacht: M', 'V' of 'gemengd' nodig" in fout({}, {})            # gemengde ploeg zonder geslacht
    assert "geslacht moet" in fout({}, {"geslacht": "X"})
    assert "geen categorie" in fout({}, {"geslacht": "V", "alleen": ["junioren"]})
    assert "materiaal_als" in fout({"materiaal_als": "U18"}, {"geslacht": "V"})
    assert "geen puntentelling" in fout({}, {"geslacht": "V", "punten": "100mH-bestaat-niet"})
    assert "letters, cijfers" in str(_fout_ploegsleutel())


def _fout_ploegsleutel():
    try:
        regels.Regelset.uit_dict({"naam": "T", "puntentelling": "au_2025", "puntentabel": "au_senioren",
                                  "ploegen": {"SEN V": {"geslacht": "V", "programma": {"w": {"x": 1}}}},
                                  "onderdelen": {"x": {"naam": "100 meter", "punten": "100m"}}}, "test")
    except regels.RegelFout as e:
        return e
    raise AssertionError("RegelFout verwacht")


# ------------------------------------------------------------
# Matrix met deze bestanden
# ------------------------------------------------------------
def test_matrix_senioren_en_masters():
    dag = date(2027, 6, 5)
    with lege_opslag() as (db, tmp):
        vrouw = beheer.nieuwe_atleet(db, "Vera", "Proef", geslacht="V", geboortedatum="1979-03-01")   # 48: V45
        man = beheer.nieuwe_atleet(db, "Mark", "Proef", geslacht="M", geboortedatum="2000-01-01")
        o = {n: db.onderdeel_opslaan(Onderdeel(n, e, e == "tijd")) for n, e in (
            ("100 meter", "tijd"), ("Kogelstoten 4kg", "afstand"), ("Kogelstoten 7,26kg", "afstand"))}
        for a, n, w in ((vrouw, "100 meter", 13.5), (man, "100 meter", 11.2), (vrouw, "Kogelstoten 4kg", 11.0),
                        (man, "Kogelstoten 7,26kg", 13.0)):
            db.prestatie_opslaan(Prestatie(n, date(2027, 5, 1), w, atleet_id=a.master_id,
                                           onderdeel_id=o[n].id, wind=0.0))
        rs = regels.laad(E3)
        m = vergelijk.matrix(db, rs, "SEN", "wedstrijd_1", dag, [vrouw, man])
        assert m.cel(vrouw.master_id, "100m-V").punten == int(30672.0 / 13.5 - 1682.5)
        assert m.cel(man.master_id, "100m-M").punten == int(29550.0 / 11.2 - 1881.5)
        assert m.cel(man.master_id, "100m-V").nvt and not m.cel(vrouw.master_id, "100m-V").nvt
        assert m.cel(vrouw.master_id, "kogelstoten-V").waarde == 11.0
        assert m.cel(man.master_id, "kogelstoten-M").waarde == 13.0

        ms = vergelijk.matrix(db, regels.laad(MASTERS), "MAS-V", "wedstrijd_1", dag, [vrouw])
        assert ms.rij(vrouw.master_id).categorie == "V45" and ms.rij(vrouw.master_id).toegestaan
        assert ms.cel(vrouw.master_id, "kogelstoten").waarde == 11.0                     # V45: 4 kg
