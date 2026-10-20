"""Tests voor de opstellingsregels: ploeg/regels.py, models/ploeg.py en
config/ploeg_regels/u14_u16_2026-2027.yaml.

Verwachte programma's komen uit de Wedstrijdbepalingen Competitie 2026-2027,
bepalingen 70 en 72. Alleen nep-master_ids, geen namen.
Werkt met pytest en los: `python tests/test_regels.py`.
"""

import copy
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from models import Inzet, PloegLid  # noqa: E402
from ploeg import regels  # noqa: E402
from ploeg.regels import RegelFout, Regelset, categorie_code, controleer_dag  # noqa: E402

BESTAND = "u14_u16_2026-2027"
A, B, C, D, E, F = (c * 32 for c in "abcdef")


def _verwacht(fout, fn) -> None:
    try:
        fn()
    except fout as e:
        return e
    raise AssertionError(f"{fout.__name__} verwacht")


def rs() -> Regelset:
    return regels.laad(BESTAND)


def _ruw() -> dict:
    pad = Path(__file__).resolve().parents[1] / "config" / "ploeg_regels" / f"{BESTAND}.yaml"
    return yaml.safe_load(pad.read_text(encoding="utf-8"))


def codes(overtredingen) -> list[str]:
    return sorted(o.code for o in overtredingen)


# ------------------------------------------------------------
# Het regelbestand U14/U16
# ------------------------------------------------------------
def test_bestand_laadt_met_alle_ploegen_en_programmas():
    r = rs()
    assert r.bestand == BESTAND
    assert r.puntentabel == "au_u14_u16" and r.puntentoekenning == "prestatie"
    assert set(r.ploegen) == {"U14-V", "U14-M", "U16-V", "U16-M"}
    for p in r.ploegen:
        assert r.programmas(p) == ["wedstrijd_1", "wedstrijd_2", "wedstrijd_3", "finale_2026", "finale_2027"]
    assert BESTAND in regels.bestanden()


def test_programmas_volgens_bepaling_70_en_72():
    def prog(p, w):
        return {r.sleutel: r.max_atleten for r in rs().programma(p, w)}

    assert prog("U14-V", "wedstrijd_2") == {"60m": 3, "600m": 3, "60mH": 3, "4x60m": 1, "hoogspringen": 2,
                                            "verspringen": 2, "kogelstoten": 2, "speerwerpen": 2}
    assert prog("U14-M", "wedstrijd_1") == {"80m": 3, "1000m": 3, "80mH": 3, "4x80m": 1, "hoogspringen": 2,
                                            "verspringen": 2, "kogelstoten": 2, "speerwerpen": 2}
    assert "discuswerpen" in prog("U14-M", "wedstrijd_2") and "speerwerpen" not in prog("U14-M", "wedstrijd_2")
    assert "300mH" in prog("U16-V", "wedstrijd_3") and "80mH" not in prog("U16-V", "wedstrijd_3")
    assert set(prog("U16-M", "wedstrijd_2")) == {"150m", "1500m", "100mH", "4x100m", "hoogspringen",
                                                 "verspringen", "kogelstoten", "speerwerpen"}
    assert set(prog("U16-M", "finale_2027")) == {"150m", "800m", "300mH", "4x100m", "hoogspringen",
                                                 "verspringen", "kogelstoten", "speerwerpen"}
    assert set(prog("U14-V", "finale_2026")) == {"60m", "1000m", "60mH", "4x60m", "hoogspringen",
                                                 "verspringen", "kogelstoten", "discuswerpen"}


def test_soort_en_tellend():
    r = {x.sleutel: x for x in rs().programma("U16-V", "wedstrijd_2")}
    assert (r["150m"].soort, r["150m"].tellend) == ("loop", 2)          # lopen: beste twee tellen
    assert (r["80mH"].soort, r["80mH"].tellend) == ("loop", 2)
    assert (r["verspringen"].soort, r["verspringen"].tellend) == ("technisch", 1)
    assert (r["4x80m"].soort, r["4x80m"].tellend, r["4x80m"].onderdeel.lopers) == ("estafette", 1, 4)


def test_wie_mag_meedoen():
    r = rs()
    assert r.mag_meedoen("U16-V", "U14-V") and r.mag_meedoen("U16-V", "U16-V")
    assert not r.mag_meedoen("U14-V", "U16-V")              # ouder mag niet naar beneden
    assert not r.mag_meedoen("U16-V", "U16-M")              # jongens niet in de meisjesploeg
    assert not r.mag_meedoen("U16-V", None)
    assert not r.mag_meedoen("U14-V", "U12-V") and not r.mag_meedoen("U14-M", "U12-M")   # U12 mag niet


def test_onderdeelnaam_met_materiaal_van_de_ploeg():
    r = rs()
    assert r.onderdeel_naam("U16-V", "kogelstoten", "U14-V") == "Kogelstoten 3kg"   # U14 in U16-ploeg
    assert r.onderdeel_naam("U14-V", "kogelstoten", "U14-V") == "Kogelstoten 2kg"
    assert r.onderdeel_naam("U16-M", "100mH", "U16-M") == "100 meter horden 83,8cm"
    assert r.onderdeel_naam("U14-M", "discuswerpen", "U14-M") == "Discuswerpen 1kg"
    assert r.onderdeel_naam("U14-V", "discuswerpen", "U14-V") == "Discuswerpen 0,75kg"
    assert r.onderdeel_naam("U14-V", "60mH", "U14-V") == "60 meter horden 76,2cm"
    assert r.onderdeel_naam("U14-V", "verspringen", "U14-V") == "Verspringen"


def test_categorie_code():
    assert categorie_code("U14", "V") == "U14-V"
    assert categorie_code("Senior", "M") == "SEN-M"
    assert categorie_code("U16", None) is None
    assert categorie_code("U16", "X") is None
    assert categorie_code(None, "V") is None


def test_onbekende_ploeg_of_wedstrijd():
    _verwacht(RegelFout, lambda: rs().ploeg("U18-V"))
    _verwacht(RegelFout, lambda: rs().programma("U16-V", "wedstrijd_9"))
    _verwacht(RegelFout, lambda: rs().onderdeel_naam("U16-V", "hamer", "U16-V"))


# ------------------------------------------------------------
# Een opstelling controleren
# ------------------------------------------------------------
CAT = {A: "U16-V", B: "U16-V", C: "U14-V", D: "U16-V", E: "U16-V", F: "U16-V"}


def _goede_opstelling():
    leden = [PloegLid(x) for x in (A, B, C, D)] + [PloegLid(E, "reserve")]
    inzet = [Inzet(A, "80m"), Inzet(B, "80m"), Inzet(C, "80m"),
             Inzet(A, "4x80m"), Inzet(B, "4x80m"), Inzet(C, "4x80m"), Inzet(D, "4x80m"),
             Inzet(A, "verspringen", groep=1), Inzet(D, "verspringen", groep=2),
             Inzet(C, "kogelstoten")]
    return leden, inzet


def controleer(leden, inzet, cat=CAT, prog="wedstrijd_1"):
    return rs().controleer("U16-V", prog, leden, inzet, cat)


def test_goede_opstelling_heeft_geen_overtredingen():
    leden, inzet = _goede_opstelling()
    assert controleer(leden, inzet) == []


def test_te_veel_op_een_onderdeel():
    leden, inzet = _goede_opstelling()
    inzet.append(Inzet(D, "80m"))                                  # 4e op de 80 m, max 3
    uit = controleer(leden, inzet)
    assert codes(uit) == ["te_veel_op_onderdeel"]
    assert uit[0].onderdeel == "80m" and "maximaal 3" in uit[0].tekst


def test_drie_onderdelen_estafette_telt_mee():
    leden, inzet = _goede_opstelling()
    inzet.append(Inzet(A, "kogelstoten"))                          # A: 80m, 4x80m, ver, kogel = 4
    uit = controleer(leden, inzet)
    assert codes(uit) == ["te_veel_onderdelen"] and uit[0].atleet_id == A


def test_niet_toegestane_en_onbekende_categorie():
    leden, inzet = _goede_opstelling()
    uit = controleer(leden, inzet, cat={**CAT, B: "U16-M", D: None})
    assert codes(uit) == ["categorie_onbekend", "niet_toegestaan"]
    assert {o.ernst for o in uit} == {"fout", "waarschuwing"}
    assert next(o for o in uit if o.code == "niet_toegestaan").atleet_id == B


def test_reserves():
    leden, inzet = _goede_opstelling()
    leden += [PloegLid(x, "reserve") for x in ("1" * 32, "2" * 32, "3" * 32, "4" * 32)]   # 5 reserves
    cat = {**CAT, **{x * 32: "U16-V" for x in "1234"}}
    assert codes(controleer(leden, inzet, cat)) == ["te_veel_reserves"]
    inzet.append(Inzet(E, "800m"))                                 # E is reserve
    assert "reserve_met_onderdeel" in codes(controleer(leden, inzet, cat))


def test_inzet_buiten_ploeg_programma_en_dubbel():
    leden, inzet = _goede_opstelling()
    uit = controleer(leden, inzet + [Inzet(F, "800m")])
    assert codes(uit) == ["geen_lid"]
    uit = controleer(leden, inzet + [Inzet(D, "speerwerpen")])     # geen speer op wedstrijd 1
    assert codes(uit) == ["niet_op_programma"] and "Speerwerpen" in uit[0].tekst
    uit = controleer(leden, inzet + [Inzet(C, "kogelstoten")])
    assert codes(uit) == ["dubbel"]
    uit = controleer(leden + [PloegLid(A)], inzet)
    assert codes(uit) == ["dubbel_lid"]


def test_estafette():
    leden, inzet = _goede_opstelling()
    zonder_d = [i for i in inzet if not (i.atleet_id == D and i.onderdeel == "4x80m")]
    uit = controleer(leden, zonder_d)
    assert codes(uit) == ["estafette_onvolledig"] and uit[0].ernst == "waarschuwing"
    leden.append(PloegLid(F))
    uit = controleer(leden, inzet + [Inzet(F, "4x80m")])           # 5 lopers, één estafetteploeg
    assert codes(uit) == ["te_veel_lopers"]


def test_een_atleet_per_groep():
    leden, inzet = _goede_opstelling()
    inzet = [Inzet(i.atleet_id, i.onderdeel, 1) if i.onderdeel == "verspringen" else i for i in inzet]
    uit = controleer(leden, inzet)
    assert codes(uit) == ["zelfde_groep"] and "groep 1" in uit[0].tekst


def test_een_ploeg_per_dag():
    a = [PloegLid(A), PloegLid(B)]
    b = [PloegLid(C), PloegLid(B, "reserve")]                      # ook als reserve niet
    uit = controleer_dag({"U16-V A": a, "U16-V B": b})
    assert codes(uit) == ["twee_ploegen"] and uit[0].atleet_id == B
    assert controleer_dag({"U16-V A": a, "U14-V": [PloegLid(C)]}) == []


def test_gemengde_estafette_samenstelling():
    ruw = {
        "naam": "Test gemengd", "puntentelling": "au_2025", "puntentabel": "au_senioren",
        "ploegen": {"SEN-V": {"toegestaan": ["SEN-V", "SEN-M"],
                              "programma": {"w1": {"4x400m-gemengd": 1}}}},
        "onderdelen": {"4x400m-gemengd": {"naam": "4 x 400 meter gemengd", "lopers": 4,
                                          "samenstelling": {"M": 2, "V": 2}}},
    }
    r = Regelset.uit_dict(ruw, "test")
    leden = [PloegLid(x) for x in (A, B, C, D)]
    inzet = [Inzet(x, "4x400m-gemengd") for x in (A, B, C, D)]
    goed = {A: "SEN-M", B: "SEN-M", C: "SEN-V", D: "SEN-V"}
    assert r.controleer("SEN-V", "w1", leden, inzet, goed) == []
    fout = {**goed, B: "SEN-V"}
    assert codes(r.controleer("SEN-V", "w1", leden, inzet, fout)) == ["samenstelling"]


# ------------------------------------------------------------
# Fouten in het regelbestand
# ------------------------------------------------------------
def _fout(aanpassen) -> str:
    ruw = copy.deepcopy(_ruw())
    aanpassen(ruw)
    return str(_verwacht(RegelFout, lambda: Regelset.uit_dict(ruw, "kapot")))


def test_fouten_in_het_bestand_worden_uitgelegd():
    assert "tikfout" in _fout(lambda r: r.update(ploegn=1))
    assert "tikfout" in _fout(lambda r: r["algemeen"].update(max_reserve=4))
    assert "tikfout" in _fout(lambda r: r["algemeen"]["tellend"].update(lopen=2))
    assert "staat niet onder 'onderdelen'" in _fout(
        lambda r: r["ploegen"]["U14-V"]["programma"]["wedstrijd_1"].update(hamer=1))
    assert "geen puntentelling" in _fout(lambda r: (
        r["onderdelen"].update(hamer={"naam": "Kogelslingeren"}),
        r["ploegen"]["U14-V"]["programma"]["wedstrijd_1"].update(hamer=1)))
    assert "geen categorie" in _fout(lambda r: r["ploegen"]["U16-V"].update(toegestaan=["meisjes"]))
    assert "heel getal" in _fout(lambda r: r["ploegen"]["U14-V"]["programma"]["wedstrijd_1"].update({"60m": "drie"}))
    assert "heel getal" in _fout(lambda r: r["algemeen"].update(max_onderdelen_per_atleet=0))
    assert "'naam' ontbreekt" in _fout(lambda r: r.pop("naam"))
    assert "puntentabel" in _fout(lambda r: r.update(puntentabel="bestaat_niet"))
    assert "au_1999" in _fout(lambda r: r.update(puntentelling="au_1999"))
    assert "materiaal" in _fout(lambda r: r["algemeen"].update(materiaal="eigen materiaal"))
    assert "naam" in _fout(lambda r: r["onderdelen"].update({"60m": {}}))
    assert "samenstelling" in _fout(lambda r: r["onderdelen"]["4x60m"].update(samenstelling={"M": 2, "V": 1}))
    assert "leeg" in str(_verwacht(RegelFout, lambda: Regelset.uit_dict(None, "leeg")))


def test_laden_uit_een_map_en_opnieuw_inlezen():
    with tempfile.TemporaryDirectory() as tmp:
        map = Path(tmp)
        (map / "leeg.yaml").write_text("#This is an empty temporary file\n", encoding="utf-8")
        pad = map / "test.yaml"
        ruw = _ruw()
        pad.write_text(yaml.safe_dump(ruw, allow_unicode=True), encoding="utf-8")
        assert regels.bestanden(map) == ["test"]                   # leeg voorbeeldbestand telt niet
        assert regels.laad("test.yaml", map).max_reserves == 4

        ruw["algemeen"]["max_reserves"] = 2                        # ploegleider past het bestand aan
        pad.write_text(yaml.safe_dump(ruw, allow_unicode=True), encoding="utf-8")
        later = time.time() + 5
        os.utime(pad, (later, later))
        assert regels.laad("test", map).max_reserves == 2

        pad.write_text("naam: [kapot", encoding="utf-8")
        os.utime(pad, (later + 5, later + 5))
        assert "geen geldige YAML" in str(_verwacht(RegelFout, lambda: regels.laad("test", map)))
        _verwacht(RegelFout, lambda: regels.laad("bestaat_niet", map))
        _verwacht(RegelFout, lambda: regels.laad("../geheim", map))


# ------------------------------------------------------------
# Modellen
# ------------------------------------------------------------
def test_modellen():
    assert PloegLid(A).rol == "deelnemer" and PloegLid(A).beschikbaar == "hele_dag"
    _verwacht(ValueError, lambda: PloegLid("kort"))
    _verwacht(ValueError, lambda: PloegLid(A, "invaller"))
    _verwacht(ValueError, lambda: PloegLid(A, beschikbaar="avond"))
    _verwacht(ValueError, lambda: Inzet(A, ""))
    _verwacht(ValueError, lambda: Inzet(A, "verspringen", groep=0))
    assert Inzet(A, "verspringen", 2).groep == 2


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
