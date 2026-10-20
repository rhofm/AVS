"""Tests voor ploeg/config.py: per bestand gaat config/ naast de .exe voor de meegebouwde kopie.

Nagebootste .exe in een tijdelijke map:
    <tmp>/AVS.exe                 sys.executable
    <tmp>/config/...              wat de ploegleider zelf heeft neergezet (extern)
    <tmp>/_intern/config/...      de kopie in de .exe (sys._MEIPASS), = config/ uit de repo
Werkt met pytest.
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ploeg import config, punten, regels  # noqa: E402

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
EIGEN_PUNTEN = "tabellen:\n  t:\n    alle:\n      100m: {formule: au_loop, A: 1000, B: 0}\n"


@pytest.fixture
def exe(tmp_path, monkeypatch):
    """(externe config-map, meegebouwde config-map) van een nagebootste .exe."""
    meegebouwd = tmp_path / "_intern" / "config"
    shutil.copytree(REPO_CONFIG, meegebouwd)
    extern = tmp_path / "config"
    (extern / "ploeg_regels").mkdir(parents=True)
    (extern / "puntentelling").mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "AVS.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_intern"), raising=False)
    return extern, meegebouwd


def _eigen_kopie(bron: Path, doel: Path, naam: str) -> None:
    """Kopie van een regelbestand met een andere 'naam:' (zo zie je welke geladen is)."""
    tekst = bron.read_text(encoding="utf-8")
    regels_ = tekst.splitlines(keepends=True)
    i = next(i for i, r in enumerate(regels_) if r.startswith("naam:"))
    regels_[i] = f"naam: {naam}\n"
    doel.write_text("".join(regels_), encoding="utf-8")


def _gevuld_regelbestand(map_: Path) -> str:
    return next(n for n in regels.bestanden(map_) if n)


def test_vanuit_de_broncode():
    assert config.config_mappen() == [REPO_CONFIG]
    assert config.config_bestand("puntentelling", "au_2025.yaml") == REPO_CONFIG / "puntentelling" / "au_2025.yaml"
    assert config.config_bestand("puntentelling", "bestaat_niet.yaml") is None


def test_volgorde_in_de_exe(exe, tmp_path):
    extern, meegebouwd = exe
    assert config.config_mappen() == [extern, meegebouwd]
    shutil.rmtree(extern)
    assert config.config_mappen() == [meegebouwd]                 # geen eigen map: alleen de meegebouwde


def test_eigen_regelbestand_gaat_voor(exe):
    extern, meegebouwd = exe
    naam = _gevuld_regelbestand(meegebouwd / "ploeg_regels")
    origineel = regels.laad(naam).naam
    _eigen_kopie(meegebouwd / "ploeg_regels" / f"{naam}.yaml", extern / "ploeg_regels" / f"{naam}.yaml",
                 "Aangepast door de ploegleider")
    assert regels.laad(naam).naam == "Aangepast door de ploegleider" != origineel

    # alle andere (nieuwe) bestanden uit de .exe blijven zichtbaar, zonder dubbele namen
    alle = regels.bestanden()
    assert alle == regels.bestanden(meegebouwd / "ploeg_regels") and len(alle) == len(set(alle))


def test_nieuw_eigen_regelbestand_met_meegebouwde_puntentelling(exe):
    extern, meegebouwd = exe
    naam = _gevuld_regelbestand(meegebouwd / "ploeg_regels")
    _eigen_kopie(meegebouwd / "ploeg_regels" / f"{naam}.yaml", extern / "ploeg_regels" / "onze_competitie.yaml",
                 "Onze eigen competitie")
    assert not list((extern / "puntentelling").iterdir())          # puntentelling staat alleen in de .exe
    assert "onze_competitie" in regels.bestanden()
    assert regels.laad("onze_competitie").naam == "Onze eigen competitie"


def test_leeg_eigen_bestand_verbergt_niets(exe):
    extern, meegebouwd = exe
    naam = _gevuld_regelbestand(meegebouwd / "ploeg_regels")
    (extern / "ploeg_regels" / f"{naam}.yaml").write_text("#This is an empty temporary file\n\n", encoding="utf-8")
    assert config.config_bestand("ploeg_regels", f"{naam}.yaml") == meegebouwd / "ploeg_regels" / f"{naam}.yaml"
    assert naam in regels.bestanden()
    regels.laad(naam)                                              # het meegebouwde bestand, zonder fout


def test_alleen_leeg_telt_niet_mee(exe):
    extern, _ = exe
    (extern / "ploeg_regels" / "leeg.yaml").write_text("# nog invullen\n", encoding="utf-8")
    assert config.config_bestand("ploeg_regels", "leeg.yaml") == extern / "ploeg_regels" / "leeg.yaml"
    assert "leeg" not in regels.bestanden()


def test_eigen_puntentelling_gaat_voor_en_wordt_opnieuw_gelezen(exe):
    extern, _ = exe
    assert "t" not in punten.puntentelling("au_2025").tabellen
    eigen = extern / "puntentelling" / "au_2025.yaml"
    eigen.write_text(EIGEN_PUNTEN, encoding="utf-8")
    assert set(punten.puntentelling("au_2025").tabellen) == {"t"}
    assert punten.puntentelling("au_2025").punten("t", "100m", "V", 10.0) == 100

    eigen.write_text(EIGEN_PUNTEN.replace("A: 1000", "A: 2000"), encoding="utf-8")
    stat = eigen.stat()
    os.utime(eigen, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))    # zeker een nieuwere tijd
    assert punten.puntentelling("au_2025").punten("t", "100m", "V", 10.0) == 200   # zonder herstart

    eigen.unlink()                                                 # weg: weer de meegebouwde
    assert "t" not in punten.puntentelling("au_2025").tabellen


def test_niet_gevonden_noemt_beide_mappen(exe):
    extern, meegebouwd = exe
    with pytest.raises(regels.RegelFout) as e:
        regels.laad("bestaat_niet")
    assert str(extern / "ploeg_regels") in str(e.value) and str(meegebouwd / "ploeg_regels") in str(e.value)
    with pytest.raises(punten.PuntenFout, match="niet gevonden in"):
        punten.puntentelling("bestaat_niet")
    with pytest.raises(punten.PuntenFout, match="niet gevonden in"):
        punten.leeftijdsfactoren("bestaat_niet")


def test_geen_paden_als_naam():
    for naam in ("../geheim", "map/bestand", ".verborgen", ""):
        with pytest.raises(punten.PuntenFout, match="Ongeldige naam"):
            punten.puntentelling(naam)
