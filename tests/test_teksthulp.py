"""Tests voor src/teksthulp: plat() en slug(), en dat de bestandsnamen van de exports niet veranderen."""

from datetime import date

from teksthulp import plat, slug


def test_plat():
    assert plat("Zoë  van Dijk") == "zoe van dijk"
    assert plat("  ÉLAN Ç ") == "elan c"
    assert plat("Ærø Ølsen") == "ærø ølsen"            # geen accent-variant: blijft staan
    assert plat(None) == "" and plat("") == ""


def test_slug():
    assert slug("Zoë van Dijk") == "zoe_van_dijk"
    assert slug("U16 selectie (di)", scheiding="-") == "u16-selectie-di"
    assert slug("Ærø Ølsen") == "r_lsen"               # alleen a-z en 0-9
    assert slug("日本語", standaard="groep") == "groep"
    assert slug("-_-", standaard="x") == "x"
    assert slug("a" * 80, max_lengte=60) == "a" * 60
    assert slug(None) == ""


def test_bestandsnamen_van_de_exports():
    from ploeg.export import _bestandsnaam
    from testen.sjabloon import maak_slug
    assert _bestandsnaam("Ploeg 1 – NK Teams!", date(2026, 5, 1)) == "ploeg_ploeg_1_nk_teams_2026-05-01.csv"
    assert _bestandsnaam("日本", date(2026, 5, 1)) == "ploeg_ploeg_2026-05-01.csv"
    assert maak_slug("Hoogspringen staand") == "hoogspringen_staand"
    assert maak_slug("") == "test"
