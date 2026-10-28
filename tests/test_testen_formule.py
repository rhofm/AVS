"""Tests voor src/testen/formule.py: de veilige rekenmachine voor scoreformules.

Werkt met pytest en los: `python tests/test_testen_formule.py`.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from testen.formule import MAX_LENGTE, Formule, FormuleFout  # noqa: E402


def rek(tekst, x=0.0, par=(), var="L"):
    return Formule(tekst, len(par), var).bereken(x, par)


def test_bewerkingen_en_volgorde():
    assert rek("L + 2 * 3", 1) == 7                  # maal gaat voor plus
    assert rek("(L + 2) * 3", 1) == 9
    assert rek("L - 2 - 3", 10) == 5                 # links naar rechts
    assert rek("L / 2 / 5", 20) == 2
    assert rek("2 ^ 3 ^ 2 + L", 0) == 512            # macht is rechts-associatief: 2^(3^2)
    assert rek("-L ^ 2", 3) == -9                    # min na de macht: -(3^2)
    assert rek("2 * -L", 3) == -6
    assert rek("--L", 3) == 3
    assert rek("+L", 3) == 3
    assert rek("L ^ 0.5", 16) == 4
    assert rek("sqrt(L) + sqrt(9)", 16) == 7
    assert rek("SQRT(L)", 16) == 4                   # hoofdletters mogen ook
    assert rek("sqrt(sqrt(L))", 16) == 2


def test_getallen_met_komma_en_punt():
    assert rek("1,5 * L", 2) == 3
    assert rek("1.5*L", 2) == 3
    assert rek(".5 * L", 2) == 1
    assert rek("0,25*L", 8) == 2


def test_resultaat_en_parameters():
    assert rek("C1 * L + C2", 4, [2, 10]) == 18
    assert rek("C1 / T", 4, [100], var="T") == 25
    assert rek("M * c1", 2, [3], var="M") == 6        # kleine letters mogen
    assert rek("C2 - C1 + L", 1, [10, 30]) == 21
    f = Formule("C1 * L", 1, "L")
    assert f.bereken(2, [5, 99]) == 10               # extra parameters worden genegeerd
    with pytest.raises(FormuleFout, match="1 parameters nodig"):
        f.bereken(2, [])


@pytest.mark.parametrize("tekst, aantal, var, fragment", [
    ("", 0, "L", "leeg"),
    ("   ", 0, "L", "leeg"),
    ("L +", 0, "L", "niet af"),
    ("(L", 0, "L", "haakje"),
    ("L)", 0, "L", "Onverwacht"),
    ("L L", 0, "L", "Onverwacht"),
    ("* L", 0, "L", "Onverwacht"),
    ("L $ 2", 0, "L", "Onbekend teken"),
    ("L; 2", 0, "L", "Onbekend teken"),
    ("sqrt L", 0, "L", "haakje"),
    ("foo * L", 0, "L", "Onbekende naam"),
    ("sin(L)", 0, "L", "Onbekende naam"),
    ("T * 2", 0, "L", "heet L, niet T"),          # in een lengte-onderdeel heet het resultaat L
    ("M", 0, "T", "heet T, niet M"),
    ("C1 * L", 0, "L", "geen parameters"),
    ("C3 * L", 2, "L", "C3 bestaat niet"),
    ("C0 * L", 2, "L", "C0 bestaat niet"),
    ("5 + 5", 0, "L", "gebruikt het resultaat"),
    ("C1", 1, "L", "gebruikt het resultaat"),
    ("L" + " + 1" * MAX_LENGTE, 0, "L", "te lang"),
    ("(" * 60 + "L" + ")" * 60, 0, "L", "Te veel haakjes"),
])
def test_ongeldige_formules(tekst, aantal, var, fragment):
    with pytest.raises(FormuleFout, match=fragment):
        Formule(tekst, aantal, var)


@pytest.mark.parametrize("tekst, x, fragment", [
    ("1 / (L - 2)", 2, "Delen door nul"),
    ("sqrt(L - 5)", 1, "negatief"),
    ("(0 - 8) ^ 0.5 + L", 1, "geen gewoon getal"),     # python geeft hier een complex getal
    ("0 ^ (0 - 1) + L", 1, "Delen door nul"),
    ("10 ^ 1000 + L", 1, "te groot"),
    ("L ^ L ^ L ^ L", 9, "te groot"),
])
def test_onmogelijke_berekening(tekst, x, fragment):
    f = Formule(tekst, 0, "L")
    with pytest.raises(FormuleFout, match=fragment):
        f.bereken(x)


def test_geen_eval():
    """Python-code in de formule wordt nooit uitgevoerd: het is gewoon een fout."""
    for tekst in ("__import__('os').system('echo hoi')", "L.real", "L if 1 else 2", "[L]", "L ** 2", "lambda: L",
                  "L // 2", "L % 2", "L == 2"):
        with pytest.raises(FormuleFout):
            Formule(tekst, 0, "L")


def test_uitkomst_is_float():
    uit = rek("L", 3)
    assert isinstance(uit, float) and uit == 3.0 and math.isfinite(uit)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
