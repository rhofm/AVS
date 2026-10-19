"""Tests voor de puntentelling: ploeg/punten.py en config/puntentelling/au_2025.yaml.

De verwachte waarden komen uit "Formules & Constanten" (december 2025) en de
Mastersploeg-spreadsheet van de Atletiekunie, niet uit de code zelf.
Werkt met pytest en los: `python tests/test_punten.py`.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ploeg import config, punten  # noqa: E402
from ploeg.punten import PuntenFout, Puntentelling, handtijd_correctie  # noqa: E402

P = punten.punten
PV = punten.prestatie_voor


def _verwacht(fout, fn) -> None:
    try:
        fn()
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


# ------------------------------------------------------------
# Voorbeelden uit de documenten
# ------------------------------------------------------------
def test_au_senioren_spreadsheet():
    # Mastersploeg-spreadsheet, M35 (leeftijdsfactor 1): zelfde punten als de AU-formule.
    assert P("au_senioren", "100m", "M", 11.5) == 688
    assert P("au_senioren", "4x100m", "M", 46.0) == 688
    assert P("au_senioren", "zweedse", "M", 2 * 60 + 12) == 751
    assert P("au_senioren", "kogelslingeren", "M", 55.15) == 873


def test_wa_meerkamp_voorbeelden_masters():
    # Voorbeelden 'Puntenwaardering van de meerkamp voor masters' (al gecorrigeerde prestaties).
    assert P("wa_meerkamp", "100m", "M", 11.85) == 681                 # M50, 13.12 * 0.9031
    assert P("wa_meerkamp", "400m", "M", 50.44) == 794                 # M55, (58.4 + 0.14) * 0.8616
    assert P("wa_meerkamp", "speerwerpen", "V", 35.81) == 587          # V65, 20.26 * 1.7680


def test_afkappen_niet_afronden():
    # 19933 / 11.2 - 1193 = 586.7 -> 586
    assert P("au_u14_u16", "80m", "V", 11.2) == 586
    # 1094.4 * sqrt(6.00) - 2075.3 = 605.43 -> 605
    assert P("au_senioren", "verspringen", "M", 6.00) == 605


def test_u14_u16_zelfde_voor_jongens_en_meisjes():
    for o, w in (("80m", 11.0), ("hoogspringen", 1.50), ("kogelstoten", 10.0)):
        assert P("au_u14_u16", o, "M", w) == P("au_u14_u16", o, "V", w)


# ------------------------------------------------------------
# Knikken in de formules
# ------------------------------------------------------------
def test_knik_hoogspringen_u14_u16():
    # t/m 1,35 m: INT((d - 0.67) * 733.33333 + 0.7); daarboven 1977.53 * sqrt(d) - 1798.5
    assert P("au_u14_u16", "hoogspringen", "V", 1.35) == 499
    assert P("au_u14_u16", "hoogspringen", "V", 1.36) == 507
    assert P("au_u14_u16", "hoogspringen", "V", 1.00) == 242
    assert P("au_u14_u16", "hoogspringen", "V", 0.60) == 0


def test_knik_verspringen_u14_u16():
    # t/m 4,41 m: INT((d - 1.91) * 200 + 0.5); daarboven 887.99 * sqrt(d) - 1364.5
    assert P("au_u14_u16", "verspringen", "M", 4.41) == 500
    assert P("au_u14_u16", "verspringen", "M", 4.42) == 502
    assert P("au_u14_u16", "verspringen", "M", 3.00) == 218


def test_knik_hoogspringen_vrouwen():
    # <= 1,40 m: 3039.8 / 2981.5; > 1,40 m: 2635.6 / 2501.5
    assert P("au_senioren", "hoogspringen", "V", 1.40) == 615
    assert P("au_senioren", "hoogspringen", "V", 1.41) == 628
    # mannen hebben geen knik
    assert P("au_senioren", "hoogspringen", "M", 1.40) == 293


def test_u12_klassiek_100_punten_hoger_bij_knik():
    assert P("au_u12_klassiek", "hoogspringen", "M", 1.00) == 342      # 242 + 100
    assert P("au_u12_klassiek", "verspringen", "M", 3.00) == 318      # 218 + 100


# ------------------------------------------------------------
# Handtijden, nul en grenzen
# ------------------------------------------------------------
def test_handtijd_correctie():
    for o in ("60m", "100m", "200m", "300m", "80mH", "110mH", "300mH", "60mH-84", "4x40m", "4x80m"):
        assert handtijd_correctie(o) == 0.24, o
    for o in ("400m", "400mH", "4x100m"):
        assert handtijd_correctie(o) == 0.14, o
    for o in ("800m", "1500m", "2000mSC", "4x400m", "4x400m-gemengd", "zweedse", "verspringen"):
        assert handtijd_correctie(o) == 0.0, o


def test_handtijd_wordt_opgeteld():
    # 11.2 hand op de 100 m = 11.44 elektronisch
    assert P("au_senioren", "100m", "M", 11.2, handtijd=True) == P("au_senioren", "100m", "M", 11.44) == 701
    # bij technische onderdelen doet handtijd niets
    assert P("au_senioren", "verspringen", "M", 6.0, handtijd=True) == 605


def test_geen_of_zwakke_prestatie_is_nul():
    assert P("au_senioren", "100m", "M", 0) == 0
    assert P("au_senioren", "100m", "M", -1) == 0
    assert P("au_senioren", "100m", "M", None) == 0
    assert P("au_senioren", "100m", "M", 30.0) == 0                    # heel langzaam: negatief -> 0
    assert P("au_senioren", "kogelstoten", "M", 3.0) == 0
    assert P("wa_meerkamp", "100m", "M", 19.0) == 0                    # voorbij B
    assert P("wa_meerkamp", "verspringen", "M", 2.0) == 0


# ------------------------------------------------------------
# Omgekeerd: prestatie voor een aantal punten
# ------------------------------------------------------------
def test_prestatie_voor_voorbeelden():
    assert PV("au_senioren", "100m", "M", 688) == 11.5
    assert PV("au_u14_u16", "verspringen", "M", 500) == 4.41
    assert PV("au_u14_u16", "hoogspringen", "V", 499) == 1.35
    # 616 punten bestaat niet bij vrouwen hoog (1,40 = 615, 1,41 = 628): 1,41 is de zwakste
    assert PV("au_senioren", "hoogspringen", "V", 616) == 1.41
    _verwacht(ValueError, lambda: PV("au_senioren", "100m", "M", 0))


def test_prestatie_voor_is_de_zwakste_prestatie():
    """Voor elk onderdeel in elke tabel: de gevonden prestatie haalt de punten,
    een honderdste/centimeter zwakker niet meer."""
    pt = punten.puntentelling()
    gecontroleerd = 0
    for tabel, geslachten in pt.tabellen.items():
        for g in ("M", "V"):
            for o in pt.onderdelen(tabel, g):
                f = pt.formule(tabel, o, g)
                for doel in (1, 50, 100, 250, 400, 500, 616, 750, 900, 1000, 1100):
                    w = f.prestatie_voor(doel)
                    zwakker = round(w + 0.01, 2) if f.lager_is_beter else round(w - 0.01, 2)
                    assert f.punten(w) >= doel, (tabel, g, o, doel, w)
                    assert f.punten(zwakker) < doel, (tabel, g, o, doel, w)
                    gecontroleerd += 1
    assert gecontroleerd > 1000


def test_prestatie_voor_zonder_afronden_is_de_formulegrens():
    w = PV("au_senioren", "100m", "M", 688, afronden=False)
    assert abs(w - 29550.0 / (688 + 1881.5)) < 1e-12


# ------------------------------------------------------------
# Opvragen en fouten
# ------------------------------------------------------------
def test_geslacht_en_alle():
    pt = punten.puntentelling()
    # gemengde estafette staat onder 'alle' en is voor M en V op te vragen
    assert pt.heeft("au_senioren", "4x400m-gemengd", "M")
    assert pt.heeft("au_senioren", "4x400m-gemengd", "v")              # hoofdletterongevoelig
    assert "100mH" in pt.onderdelen("au_senioren", "V")
    assert "100mH" not in pt.onderdelen("au_senioren", "M")
    assert "110mH" in pt.onderdelen("au_senioren", "M")


def test_onbekend_geeft_puntenfout():
    _verwacht(PuntenFout, lambda: P("bestaat_niet", "100m", "M", 11.0))
    _verwacht(PuntenFout, lambda: P("au_senioren", "100mH", "M", 14.0))   # 100mH is voor vrouwen
    _verwacht(PuntenFout, lambda: P("au_senioren", "100m", "X", 11.0))
    _verwacht(PuntenFout, lambda: punten.puntentelling("au_1999"))
    assert issubclass(PuntenFout, ValueError)


def test_kapotte_yaml_wordt_geweigerd():
    def laad(onderdeel):
        return Puntentelling.uit_dict({"tabellen": {"t": {"M": {"x": onderdeel}}}})

    laad({"formule": "au_loop", "A": 1.0, "B": 2.0})                     # goed
    _verwacht(PuntenFout, lambda: laad({"formule": "magie", "A": 1, "B": 2}))
    _verwacht(PuntenFout, lambda: laad({"formule": "au_loop", "A": 1}))
    _verwacht(PuntenFout, lambda: laad({"formule": "wa_loop", "A": 1, "B": 2}))           # C ontbreekt
    _verwacht(PuntenFout, lambda: laad({"formule": "au_loop", "A": "veel", "B": 2}))
    _verwacht(PuntenFout, lambda: laad([{"formule": "au_techn", "A": 1, "B": 2},          # 'tot' ontbreekt
                                        {"formule": "au_techn", "A": 1, "B": 2}]))
    _verwacht(PuntenFout, lambda: laad([{"tot": 2, "formule": "au_techn", "A": 1, "B": 2},
                                        {"tot": 3, "formule": "au_techn", "A": 1, "B": 2}]))  # laatste met 'tot'
    _verwacht(PuntenFout, lambda: laad([{"tot": 2, "formule": "au_techn", "A": 1, "B": 2},
                                        {"tot": 1, "formule": "au_techn", "A": 1, "B": 2},
                                        {"formule": "au_techn", "A": 1, "B": 2}]))           # niet oplopend
    _verwacht(PuntenFout, lambda: laad([{"tot": 2, "formule": "au_loop", "A": 1, "B": 2},
                                        {"formule": "au_loop", "A": 1, "B": 2}]))            # knik bij lopen
    _verwacht(PuntenFout, lambda: Puntentelling.uit_dict({"tabellen": {"t": {"X": {}}}}))
    _verwacht(PuntenFout, lambda: Puntentelling.uit_dict({"geen": "tabellen"}))


def test_eigen_uitgave_uit_andere_map():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "puntentelling").mkdir()
        (Path(tmp) / "puntentelling" / "test.yaml").write_text(
            "tabellen:\n  t:\n    alle:\n      100m: {formule: au_loop, A: 1000, B: 0}\n", encoding="utf-8")
        pt = punten.puntentelling("test", map=Path(tmp))
        assert pt.punten("t", "100m", "V", 10.0) == 100


def test_config_map():
    assert (config.config_map() / "puntentelling" / "au_2025.yaml").is_file()
    oud_frozen, oud_exe = getattr(sys, "frozen", None), sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        try:
            sys.frozen = True
            sys.executable = str(Path(tmp) / "AVS.exe")
            sys._MEIPASS = str(Path(tmp) / "_intern")
            assert config.config_map() == Path(tmp) / "_intern" / "config"        # geen map naast de .exe
            (Path(tmp) / "config").mkdir()
            assert config.config_map() == Path(tmp).resolve() / "config"          # wel: die gaat voor
        finally:
            sys.executable = oud_exe
            del sys._MEIPASS
            if oud_frozen is None:
                del sys.frozen
            else:
                sys.frozen = oud_frozen


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
