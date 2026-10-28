"""Tests voor src/testen/sjabloon.py: sjablonen controleren, scoren, als YAML opslaan en laden.

Werkt met pytest en los: `python tests/test_testen_sjabloon.py`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from testen import sjabloon as sj  # noqa: E402
from testen.formule import FormuleFout  # noqa: E402
from testen.sjabloon import Onderdeel, Sjabloon, SjabloonFout  # noqa: E402


def sprong() -> Sjabloon:
    return Sjabloon("Sprongkracht", [
        Onderdeel("Hoogspringen staand", "lengte", "C1 * L", [100]),
        Onderdeel("30 m sprint", "tijd", "C1 / T", [150]),
        Onderdeel("Kogel", "gewicht"),
    ])


def test_soorten_en_eenheden():
    o = Onderdeel("x", "lengte")
    assert (o.variabele, o.eenheid, o.lager_is_beter) == ("L", "m", False)
    o = Onderdeel("x", "tijd")
    assert (o.variabele, o.eenheid, o.lager_is_beter) == ("T", "s", True)
    o = Onderdeel("x", "gewicht")
    assert (o.variabele, o.eenheid, o.lager_is_beter) == ("M", "kg", False)


def test_totaal_alleen_bij_twee_formules():
    s = sprong()
    assert s.aantal_formules == 2 and s.totaal_mogelijk and s.telt_totaal
    s.totaal_optellen = False
    assert s.totaal_mogelijk and not s.telt_totaal
    een = Sjabloon("Een", [Onderdeel("a", "tijd", "C1 / T", [1]), Onderdeel("b", "tijd")])
    assert not een.totaal_mogelijk and not een.telt_totaal          # één formule: niets om op te tellen


def test_scores_en_totaal():
    s = sprong()
    scores, totaal = s.scores([0.5, 4.0, 7.0])
    assert scores == [50.0, 37.5, None] and totaal == 87.5
    scores, totaal = s.scores([0.5, None, 7.0])
    assert scores == [50.0, None, None] and totaal is None          # onvolledig: geen totaal
    s.totaal_optellen = False
    assert s.scores([0.5, 4.0, 7.0]) == ([50.0, 37.5, None], None)
    with pytest.raises(FormuleFout, match="Delen door nul"):
        sprong().scores([0.5, 0.0, 7.0])


def test_problemen():
    assert sprong().problemen() == []
    s = Sjabloon("", [])
    assert any("naam" in p for p in s.problemen()) and any("minstens één" in p for p in s.problemen())
    s = Sjabloon("T", [Onderdeel("", "tijd"), Onderdeel("A", "snelheid"), Onderdeel("a", "tijd")])
    p = " | ".join(s.problemen())
    assert "Onderdeel 1: geef het een naam" in p and "kies lengte, tijd of gewicht" in p and "twee keer" in p
    s = Sjabloon("T", [Onderdeel("A", "tijd", "C1 * L", [1])])      # L in een tijd-onderdeel
    assert "heet T, niet L" in s.problemen()[0]
    s = Sjabloon("T", [Onderdeel("A", "tijd", "", [1])])
    assert "parameters zonder formule" in s.problemen()[0]
    s = Sjabloon("T" * 100, [Onderdeel("A", "tijd")])
    assert "te lang" in s.problemen()[0]
    with pytest.raises(SjabloonFout) as e:
        Sjabloon("", []).controleer()
    assert len(e.value.problemen) == 2


def test_yaml_rondje():
    s = sprong()
    tekst = s.naar_yaml()
    assert "totaal_optellen: true" in tekst and "parameters: [100]" in tekst
    assert "formule" not in tekst.split("Kogel")[1]                  # onderdeel zonder formule: geen lege velden
    terug = Sjabloon.uit_yaml(tekst, "sprongkracht")
    assert terug.naam == s.naam and terug.onderdelen == s.onderdelen and terug.totaal_optellen
    s.totaal_optellen = False
    assert Sjabloon.uit_yaml(s.naar_yaml()).totaal_optellen is False
    een = Sjabloon("Los", [Onderdeel("a", "tijd")])
    assert "totaal_optellen" not in een.naar_yaml()                  # niets op te tellen: niet in het bestand
    komma = Sjabloon.uit_yaml("naam: X\nonderdelen:\n  - {naam: a, soort: Lengte, formule: 'C1*L', parameters: ['1,5']}\n")
    assert komma.onderdelen[0].soort == "lengte" and komma.onderdelen[0].parameters == [1.5]


@pytest.mark.parametrize("tekst, fragment", [
    ("naam: [", "geen geldige YAML"),
    ("- a\n- b\n", "moet een sjabloon bevatten"),
    ("naam: X\n", "geen 'onderdelen'"),
    ("naam: X\nonderdelen: []\n", "geen 'onderdelen'"),
    ("naam: X\nonderdelen: [a]\n", "Onderdeel 1"),
    ("naam: X\nextra: 1\nonderdelen: [{naam: a}]\n", "Onbekend veld"),
    ("naam: X\nonderdelen: [{naam: a, kleur: rood}]\n", "onbekend veld kleur"),
    ("naam: X\nonderdelen: [{naam: a, formule: L, parameters: 5}]\n", "lijst"),
    ("naam: X\nonderdelen: [{naam: a, soort: lengte, formule: C1*L, parameters: [abc]}]\n", "getallen"),
    ("naam: X\ntotaal_optellen: ja-hoor\nonderdelen: [{naam: a}]\n", "true of false"),
    ("naam: X\nonderdelen: [{naam: a, soort: lengte, formule: 'L +'}]\n", "niet af"),
])
def test_yaml_fouten(tekst, fragment):
    with pytest.raises(SjabloonFout, match=fragment):
        Sjabloon.uit_yaml(tekst)


def test_yaml_sjabloon_zonder_soort_is_tijd():
    s = Sjabloon.uit_yaml("naam: X\nonderdelen:\n  - naam: a\n")
    assert s.onderdelen[0].soort == "tijd"


def test_slug():
    assert sj.maak_slug("Hoogspringen staand") == "hoogspringen_staand"
    assert sj.maak_slug("30 m  sprint (vliegend)!") == "30_m_sprint_vliegend"
    assert sj.maak_slug("Één-benige sprongtest") == "een_benige_sprongtest"
    assert sj.maak_slug("???") == "test"


def test_opslaan_en_laden(tmp_path):
    s = sj.opslaan(sprong(), tmp_path)
    assert s.slug == "sprongkracht"
    bestand = tmp_path / "testsjablonen" / "sprongkracht.yaml"
    assert bestand.is_file() and not list((tmp_path / "testsjablonen").glob("*.tmp"))
    assert "\r" not in bestand.read_text(encoding="utf-8")
    bib = sj.laad_bibliotheek(tmp_path)
    eigen = bib.vind("sprongkracht")
    assert eigen is not None and eigen.eigen and eigen.sjabloon.naam == "Sprongkracht" and eigen.sjabloon.slug == "sprongkracht"
    assert bib.per_naam("SPRONGKRACHT") is eigen
    assert bib.vind("bestaat-niet") is None and bib.vind(None) is None


def test_zelfde_naam_en_bestandsnaam(tmp_path):
    sj.opslaan(sprong(), tmp_path)
    with pytest.raises(SjabloonFout, match="al een test met de naam"):
        sj.opslaan(Sjabloon("sprongKRACHT", [Onderdeel("a", "tijd")]), tmp_path)
    # Een andere naam die dezelfde bestandsnaam geeft, krijgt een eigen bestand.
    tweede = sj.opslaan(Sjabloon("Sprongkracht!", [Onderdeel("a", "tijd")]), tmp_path)
    assert tweede.slug == "sprongkracht_2"
    # Aanpassen onder dezelfde slug mag, ook met een nieuwe naam.
    hernoemd = sj.opslaan(Sjabloon("Sprongkracht totaal", sprong().onderdelen, True, "sprongkracht"), tmp_path)
    assert hernoemd.slug == "sprongkracht"
    assert sj.laad_bibliotheek(tmp_path).vind("sprongkracht").sjabloon.naam == "Sprongkracht totaal"
    with pytest.raises(SjabloonFout):
        sj.opslaan(Sjabloon("", []), tmp_path)                         # ongeldig: niets geschreven


def test_kapotte_en_lege_bestanden(tmp_path):
    map_ = tmp_path / "testsjablonen"
    map_.mkdir()
    (map_ / "goed.yaml").write_text("naam: Goed\nonderdelen:\n  - {naam: a, soort: tijd}\n", encoding="utf-8")
    (map_ / "kapot.yaml").write_text("naam: [", encoding="utf-8")
    (map_ / "formule.yaml").write_text("naam: F\nonderdelen:\n  - {naam: a, soort: tijd, formule: 'L'}\n", encoding="utf-8")
    (map_ / "uitleg.yaml").write_text("# alleen commentaar\n", encoding="utf-8")
    (map_ / "Hoofdletters Bestand.yaml").write_text("naam: H\nonderdelen:\n  - {naam: a}\n", encoding="utf-8")
    (map_ / "zdubbel.yaml").write_text("naam: goed\nonderdelen:\n  - {naam: a}\n", encoding="utf-8")
    bib = sj.laad_bibliotheek(tmp_path)
    namen = [b.sjabloon.naam for b in bib.bronnen if b.eigen]
    assert namen == ["Goed"]                                            # de rest is overgeslagen
    fouten = " | ".join(bib.fouten)
    assert "kapot.yaml" in fouten and "formule.yaml" in fouten and "heet T, niet L" in fouten
    assert "Hoofdletters Bestand.yaml" in fouten and "zdubbel.yaml" in fouten and "uitleg.yaml" not in fouten


def test_eigen_sjabloon_wint_van_meegeleverd(tmp_path):
    meegeleverd = [b for b in sj.laad_bibliotheek(tmp_path).bronnen if not b.eigen]
    assert meegeleverd, "config/testen hoort minstens één sjabloon mee te leveren"
    eerste = meegeleverd[0].sjabloon
    eigen = Sjabloon(eerste.naam, [Onderdeel("Mijn versie", "gewicht")], True, eerste.slug)
    sj.opslaan(eigen, tmp_path)
    b = sj.laad_bibliotheek(tmp_path).vind(eerste.slug)
    assert b.eigen and b.sjabloon.onderdelen[0].naam == "Mijn versie"
    assert not any(not x.eigen and x.sjabloon.slug == eerste.slug for x in sj.laad_bibliotheek(tmp_path).bronnen)


def test_verwijderen(tmp_path):
    sj.opslaan(sprong(), tmp_path)
    assert sj.verwijderen("sprongkracht", tmp_path) is True
    assert sj.laad_bibliotheek(tmp_path).vind("sprongkracht") is None
    assert sj.verwijderen("sprongkracht", tmp_path) is False
    assert sj.verwijderen("../../etc/passwd", tmp_path) is False        # geen paden
    assert sj.verwijderen("", tmp_path) is False


def test_meegeleverde_sjablonen_zijn_geldig(tmp_path):
    bib = sj.laad_bibliotheek(tmp_path)
    assert bib.fouten == []
    assert {"30m_vliegend", "verspringen_vanuit_stand"} <= {b.sjabloon.slug for b in bib.bronnen}
    assert not any("uitleg" in b.sjabloon.slug for b in bib.bronnen)    # voorbeeld_uitleg.yaml is alleen commentaar


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
