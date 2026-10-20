"""Tests voor build.py: de argumenten voor PyInstaller, de privacycontroles en de volgorde
(tests -> bouwen -> inhoud -> zelftest -> pakketlijst; stoppen bij de eerste fout).

PyInstaller zelf draait hier niet (dat duurt minuten); dat doet `python build.py`.
Werkt met pytest.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def build():
    # Laden via het pad: de naam 'build' kan botsen met het pakket 'build' van PyPA.
    spec = importlib.util.spec_from_file_location("avs_build", ROOT / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modulelijst(build, tmp_path):
    pad = tmp_path / "zelftest_modules.txt"
    pad.write_text("db.init_db\nimporters.detect\nploeg.regels\n", encoding="utf-8")
    return pad


def _paren(args: list[str], optie: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == optie]


def test_argumenten(build, modulelijst, tmp_path):
    args = build.pyinstaller_argumenten(tmp_path / "werk", modulelijst)
    assert args[0] == str(ROOT / "src" / "__main__.py")
    assert "--onefile" in args and "--windowed" in args and "--console" not in args and "--onedir" not in args
    assert _paren(args, "--name") == ["AVS"] and _paren(args, "--paths") == [str(ROOT / "src")]

    data = _paren(args, "--add-data")
    sep = os.pathsep
    assert f"{ROOT / 'src' / 'db' / 'schema_*.sql'}{sep}db" in data            # niet *.sql
    assert f"{ROOT / 'src' / 'db' / 'migrations'}{sep}db/migrations" in data
    assert f"{ROOT / 'config'}{sep}config" in data
    assert f"{modulelijst}{sep}." in data
    for bron in (d.split(sep)[0] for d in data):
        deel = Path(bron).relative_to(ROOT).parts if Path(bron).is_relative_to(ROOT) else ()
        assert not deel or deel[0] not in ("data", "tests"), bron

    verborgen = _paren(args, "--hidden-import")
    assert {"keyring.backends.Windows", "db.init_db", "importers.detect", "ploeg.regels"} <= set(verborgen)
    assert {"pytest", "_pytest"} <= set(_paren(args, "--exclude-module"))
    assert _paren(args, "--collect-all") == ["curl_cffi"]

    assert "--onedir" in build.pyinstaller_argumenten(tmp_path / "werk", modulelijst, onedir=True)


def test_echte_modulelijst_compleet(build):
    namen = build.eigen_modules()
    assert "importers.detect" in namen and "ui.app" in namen and len(namen) > 50


def test_nooit_data_of_tests_als_bron(build, monkeypatch):
    for verboden in (ROOT / "data", ROOT / "tests" / "fixtures"):
        monkeypatch.setattr(build, "bronnen", lambda v=verboden: [(v, "x")])
        with pytest.raises(build.BouwFout, match="mag nooit in de .exe"):
            build._controleer_bronnen(build.bronnen())


def test_ontbrekende_bron(build):
    with pytest.raises(build.BouwFout, match="ontbreekt"):
        build._controleer_bronnen([(ROOT / "src" / "bestaat_niet", "x")])
    with pytest.raises(build.BouwFout, match="Geen bestanden"):
        build._controleer_bronnen([(ROOT / "src" / "db" / "niets_*.sql", "db")])
    build._controleer_bronnen(build.bronnen())                         # de echte lijst klopt


def test_verboden_inhoud(build):
    verboden = ["personen.db", "data/prestaties.db", "x/absentie.db-journal", "export.CSV", "lijst.xlsx",
                "instellingen.json", "data/iets.txt", "tests/fixtures/profiel.html", "tests\\conftest.py"]
    toegestaan = ["db/schema_personen.sql", "db/migrations/personen/011_voorkeuren.sql", "ui/templates/atleet.html",
                  "config/ploeg_regels/masters_2026-2027.yaml", "zelftest_modules.txt", "PYZ.pyz",
                  "certifi/cacert.pem", "scipy/data/something.txt", "databases.py"]
    assert build.verboden_inhoud(verboden + toegestaan) == verboden


def test_exe_pad(build, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert build.exe_pad() == ROOT / "dist" / "AVS.exe"
    assert build.exe_pad(onedir=True) == ROOT / "dist" / "AVS" / "AVS.exe"


# ---------------- volgorde en stoppen ----------------
@pytest.fixture
def stappen(build, monkeypatch, tmp_path):
    """Alle stappen vervangen door nepstappen die bijhouden wat er gebeurde."""
    log = []
    exe = tmp_path / "AVS.exe"
    monkeypatch.setattr(build, "controleer_omgeving", lambda: log.append("omgeving"))
    monkeypatch.setattr(build, "_controleer_bronnen", lambda lijst: log.append("bronnen"))
    monkeypatch.setattr(build, "tests_draaien", lambda: log.append("tests"))
    monkeypatch.setattr(build, "bouwen", lambda onedir=False: (log.append("bouwen"), exe.write_bytes(b"x"), exe)[2])
    monkeypatch.setattr(build, "controleer_inhoud", lambda e, onedir=False: log.append("inhoud"))
    monkeypatch.setattr(build, "zelftest_draaien", lambda e: log.append("zelftest"))
    monkeypatch.setattr(build, "pakketlijst", lambda d: (log.append("pakketten"), d)[1])
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build, "BUILD", tmp_path / "build")
    return log


def test_oude_build_weg_ook_bij_fout(build, stappen, monkeypatch, tmp_path):
    oud = tmp_path / "dist" / "AVS.exe"
    oud.parent.mkdir()
    oud.write_bytes(b"oude versie")
    def kapot():
        raise build.BouwFout("tests mislukt")
    monkeypatch.setattr(build, "tests_draaien", kapot)
    assert build.main([]) == 1
    assert not oud.exists()                                            # geen oude .exe die nieuw lijkt


def test_alles_goed(build, stappen, capsys):
    assert build.main([]) == 0
    assert stappen == ["omgeving", "bronnen", "tests", "bouwen", "inhoud", "zelftest", "pakketten"]
    assert "=== Klaar ===" in capsys.readouterr().out


def test_zonder_tests(build, stappen, capsys):
    assert build.main(["--zonder-tests"]) == 0
    assert "tests" not in stappen and "overgeslagen" in capsys.readouterr().out


@pytest.mark.parametrize("stap", ["tests_draaien", "controleer_inhoud", "zelftest_draaien"])
def test_stopt_bij_fout(build, stappen, monkeypatch, capsys, stap):
    def kapot(*a, **kw):
        raise build.BouwFout(f"{stap} mislukt")
    monkeypatch.setattr(build, stap, kapot)
    assert build.main([]) == 1
    assert "pakketten" not in stappen                                   # geen 'klaar' na een fout
    if stap == "tests_draaien":
        assert "bouwen" not in stappen                                  # niets gebouwd
    assert f"BOUWEN MISLUKT: {stap} mislukt" in capsys.readouterr().err


def test_verkeerde_python(build, monkeypatch, capsys):
    monkeypatch.setattr(build, "PYTHON_VERSIE", (3, 99))
    assert build.main([]) == 1
    assert "Bouw met Python 3.99" in capsys.readouterr().err
