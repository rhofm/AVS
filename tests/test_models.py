"""Tests voor de dataclasses in src/models/.

Werkt met pytest (`pytest tests/test_models.py`) en ook zonder:
`python tests/test_models.py`. Alleen nepgegevens.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from models import (  # noqa: E402
    Absentie, Atleet, Groep, Leerlijn, LeerlijnStap, LeerlijnVoortgang,
    Onderdeel, Periodeplan, Prestatie, heeft_windmeting,
)

NEP_ID = "a" * 32


def _verwacht_fout(fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("ValueError verwacht")


def test_atleet_repr_bevat_geen_persoonsgegevens():
    a = Atleet("Anna", "Voorbeeld", geslacht="V", geboortedatum="2010-05-01", atletieknu_id="123456")
    tekst = repr(a)
    for geheim in ("Anna", "Voorbeeld", "2010", "123456"):
        assert geheim not in tekst
    assert a.naam == "Anna Voorbeeld"


def test_atleet_leeftijd():
    a = Atleet("Anna", "Voorbeeld", geboortedatum="2010-05-01")
    assert a.leeftijd_op(date(2026, 4, 30)) == 15
    assert a.leeftijd_op(date(2026, 5, 1)) == 16
    alleen_jaar = Atleet("Tim", "Proefmans", geboortedatum="2010")
    assert alleen_jaar.geboortejaar == 2010
    assert alleen_jaar.leeftijd_op(date(2026, 1, 1)) == 16
    assert Atleet("X", "Y").leeftijd_op(date(2026, 1, 1)) is None


def test_atleet_controles():
    _verwacht_fout(lambda: Atleet("A", "B", geslacht="Q"))
    _verwacht_fout(lambda: Atleet("A", "B", master_id="kort"))
    _verwacht_fout(lambda: Atleet("A", "B", geboortedatum="01-05-2010"))


def test_onderdeel_beter_en_beste():
    sprint = Onderdeel("100m", "tijd", lager_is_beter=True)
    ver = Onderdeel("Verspringen", "afstand", lager_is_beter=False)
    assert sprint.is_beter(12.9, 13.2) and not sprint.is_beter(13.2, 12.9)
    assert ver.is_beter(4.8, 4.5)
    assert sprint.beste([13.2, 12.9, 13.0]) == 12.9
    assert ver.beste([4.5, 4.8]) == 4.8
    assert sprint.beste([]) is None
    _verwacht_fout(lambda: Onderdeel("x", "kilo", True))


def test_windmeting_en_windlegaal():
    for naam in ("60m", "100m", "150 m", "200 meter", "Verspringen", "Hinkstapspringen"):
        assert heeft_windmeting(naam), naam
    for naam in ("300m", "400m", "80m horden", "4x100m", "1 mijl", "Hoogspringen", "Kogelstoten"):
        assert not heeft_windmeting(naam), naam
    sprint = Onderdeel("100m", "tijd", True)
    assert sprint.windmeting
    assert sprint.windlegaal(2.0) and sprint.windlegaal(-1.5)
    assert not sprint.windlegaal(2.1) and not sprint.windlegaal(None)
    acht = Onderdeel("800m", "tijd", True)
    assert acht.windlegaal(None) and acht.windlegaal(5.0)
    assert Onderdeel("100m horden", "tijd", True, windmeting=True).windmeting  # handmatig te overrulen


def test_prestatie_koppelen_wist_brongegevens():
    p = Prestatie("100m", date(2026, 6, 1), 12.9, bron="atletieknu",
                  bron_naam="Anna Voorbeeld", bron_atletieknu_id="123456")
    assert not p.is_gekoppeld
    assert "Anna" not in repr(p)
    k = p.gekoppeld(NEP_ID)
    assert k.is_gekoppeld and k.atleet_id == NEP_ID
    assert k.bron_naam is None and k.bron_atletieknu_id is None
    assert p.bron_naam == "Anna Voorbeeld"  # origineel ongewijzigd
    assert Prestatie("100m", date(2026, 6, 1), 12.9, ronde=None).ronde == ""
    _verwacht_fout(lambda: Prestatie("100m", date(2026, 6, 1), 12.9, bron="website"))


def test_groep_leden():
    g = Groep("Pupillen", "2026-2027")
    g.voeg_toe(NEP_ID)
    g.voeg_toe(NEP_ID)
    assert g.leden == [NEP_ID]
    g.verwijder(NEP_ID)
    assert g.leden == []
    assert Groep("A").leden is not Groep("B").leden


def test_periodeplan():
    p = Periodeplan("AV", date(2026, 10, 1), date(2026, 10, 28))
    assert p.bevat(date(2026, 10, 15)) and not p.bevat(date(2026, 11, 1))
    assert p.aantal_weken == 4
    _verwacht_fout(lambda: Periodeplan("x", date(2026, 2, 1), date(2026, 1, 1)))


def test_absentie():
    assert Absentie(1, NEP_ID, "aanwezig").aanwezig
    _verwacht_fout(lambda: Absentie(1, NEP_ID, "ziek"))


def test_leerlijn():
    lijn = Leerlijn("Sprint", stappen=[
        LeerlijnStap(2, "Startpositie", id=12),
        LeerlijnStap(1, "Armactie", id=11),
        LeerlijnStap(3, "Blokstart", id=13),
    ])
    assert [s.volgorde for s in lijn.stappen] == [1, 2, 3]
    assert lijn.stap(2).naam == "Startpositie"
    assert lijn.volgende_stap({11}).id == 12
    assert lijn.volgende_stap({11, 12, 13}) is None
    assert not LeerlijnVoortgang(NEP_ID, 11).behaald
    assert LeerlijnVoortgang(NEP_ID, 11, date(2026, 9, 1)).behaald


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
