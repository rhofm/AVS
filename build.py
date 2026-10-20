"""Bouw AVS als één .exe, met één opdracht (vanuit de root van de repo, in de conda-omgeving):

    python build.py                 tests, bouwen, zelftest van de .exe
    python build.py --onedir        een map met AVS.exe + losse bestanden (start sneller)
    python build.py --zonder-tests  de tests overslaan (alleen voor een snelle proefbuild)

Stappen:
  1. controleren: Python 3.13, PyInstaller aanwezig, alle bronbestanden er;
  2. de tests draaien (pytest); bij een fout wordt er niet gebouwd;
  3. de lijst met eigen modules schrijven (zelftest.schrijf_modulelijst) en PyInstaller
     draaien; elke module gaat er als --hidden-import in, zodat PyInstaller er geen mist;
  4. de inhoud van de .exe nalopen: er mag niets in dat op gegevens lijkt (privacy);
  5. de gebouwde .exe draaien met --zelftest; mislukt die, dan is de build mislukt;
  6. naast de .exe de exacte pakketversies schrijven (AVS-pakketten.txt), zodat een
     volgende build met precies dezelfde set kan (pip install -r dist/AVS-pakketten.txt).

Uitkomst: dist/AVS.exe (of dist/AVS/AVS.exe met --onedir). build/ en dist/ staan in .gitignore.

Privacy: er gaat NOOIT iets uit data/ of tests/ in de .exe; alleen de code, de
templates, de SQL-bestanden en config/. bronnen() is de volledige lijst; een controle
weigert te bouwen als daar ooit een map data/ of tests/ in zou staan, en na het bouwen
controleert controleer_inhoud() de .exe zelf (geen .db, .csv, .xlsx, instellingen.json, data/, tests/).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAAM = "AVS"
ICOON = ROOT / "assets" / "avs.ico"            # optioneel: wordt gebruikt als het bestaat
ZELFTEST_TIJD = 300                             # seconden

PYTHON_VERSIE = (3, 13)

#: Pakketten die andere pakketten optioneel importeren, maar die AVS niet gebruikt.
NIET_MEENEMEN = ("pytest", "_pytest", "tkinter", "IPython", "matplotlib", "pandas")

#: Wat nooit in de .exe mag: lijkt op (echte) gegevens.
VERBODEN_EXTENSIES = (".db", ".db-journal", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".csv", ".xlsx")
VERBODEN_NAMEN = ("instellingen.json",)
VERBODEN_MAPPEN = ("data", "tests")


class BouwFout(RuntimeError):
    """Iets waardoor er (nog) niet gebouwd kan worden; de melding zegt wat te doen."""


# ============================================================
# Wat er in de .exe gaat
# ============================================================
def bronnen() -> list[tuple[Path, str]]:
    """(bron, doel in de .exe) voor --add-data. Bron mag een glob zijn (alleen in de bestandsnaam)."""
    return [
        (SRC / "ui" / "templates", "ui/templates"),
        (SRC / "ui" / "static", "ui/static"),
        (SRC / "db" / "schema_*.sql", "db"),            # niet *.sql: het oude schema.sql hoort er niet bij
        (SRC / "db" / "migrations", "db/migrations"),
        (ROOT / "config", "config"),
    ]


def _controleer_bronnen(lijst: list[tuple[Path, str]]) -> None:
    for bron, _ in lijst:
        deel = bron.relative_to(ROOT).parts
        if deel and deel[0] in ("data", "tests"):
            raise BouwFout(f"{bron} mag nooit in de .exe (persoonsgegevens / testbestanden).")
        if "*" in bron.name:
            if not list(bron.parent.glob(bron.name)):
                raise BouwFout(f"Geen bestanden gevonden voor {bron.relative_to(ROOT)}.")
        elif not bron.exists():
            raise BouwFout(f"{bron.relative_to(ROOT)} ontbreekt.")


def eigen_modules() -> list[str]:
    sys.path.insert(0, str(SRC))
    try:
        import zelftest
        return zelftest.eigen_modules(SRC)
    finally:
        sys.path.remove(str(SRC))


def pyinstaller_argumenten(werkmap: Path, modulelijst: Path, onedir: bool = False) -> list[str]:
    """De volledige argumentenlijst voor PyInstaller."""
    sep = os.pathsep                                   # ';' op Windows, ':' elders
    lijst = bronnen()
    _controleer_bronnen(lijst)
    args = [
        str(SRC / "__main__.py"),
        "--name", NAAM,
        "--onedir" if onedir else "--onefile",
        "--console",                                   # het venster is (nog) de manier om AVS te stoppen
        "--noconfirm", "--clean",
        "--log-level", "WARN",
        "--distpath", str(DIST),
        "--workpath", str(werkmap),
        "--specpath", str(werkmap),
        "--paths", str(SRC),
    ]
    for bron, doel in lijst:
        args += ["--add-data", f"{bron}{sep}{doel}"]
    args += ["--add-data", f"{modulelijst}{sep}."]
    args += ["--hidden-import", "keyring.backends.Windows"]
    for module in modulelijst.read_text(encoding="utf-8").split():
        args += ["--hidden-import", module]
    args += ["--collect-all", "curl_cffi",             # de meegeleverde libcurl (DLL)
             "--collect-binaries", "sqlcipher3"]
    for module in NIET_MEENEMEN:
        args += ["--exclude-module", module]
    if ICOON.is_file():
        args += ["--icon", str(ICOON)]
    return args


def verboden_inhoud(namen: list[str]) -> list[str]:
    """De namen (paden in de .exe) die er niet in mogen."""
    fout = []
    for naam in namen:
        delen = naam.replace("\\", "/").split("/")
        laatste = delen[-1].lower()
        if (laatste.endswith(VERBODEN_EXTENSIES) or laatste in VERBODEN_NAMEN
                or delen[0].lower() in VERBODEN_MAPPEN):
            fout.append(naam)
    return fout


def inhoud(exe: Path, onedir: bool = False) -> list[str]:
    """Alle bestanden in de build: de inhoudsopgave van de .exe, en bij --onedir ook de map."""
    from PyInstaller.archive.readers import CArchiveReader
    namen = list(CArchiveReader(str(exe)).toc)
    if onedir:
        namen += [f.relative_to(exe.parent).as_posix() for f in exe.parent.rglob("*") if f.is_file()]
    return namen


def controleer_inhoud(exe: Path, onedir: bool = False) -> int:
    _kop("Privacy: inhoud van de build")
    namen = inhoud(exe, onedir)
    fout = verboden_inhoud(namen)
    if fout:
        raise BouwFout("In de build zit iets dat op gegevens lijkt; niet verspreiden: " + ", ".join(fout[:10]))
    print(f"{len(namen)} onderdelen, geen gegevens.")
    return len(namen)


def exe_pad(onedir: bool = False) -> Path:
    bestand = f"{NAAM}.exe" if sys.platform == "win32" else NAAM
    return DIST / NAAM / bestand if onedir else DIST / bestand


# ============================================================
# De stappen
# ============================================================
def controleer_omgeving() -> None:
    if sys.version_info[:2] != PYTHON_VERSIE:
        raise BouwFout(f"Bouw met Python {PYTHON_VERSIE[0]}.{PYTHON_VERSIE[1]} (de conda-omgeving); "
                       f"dit is Python {sys.version.split()[0]}.")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise BouwFout("PyInstaller ontbreekt. Installeer alles met: pip install -e .[dev]") from None


def tests_draaien() -> None:
    _kop("Tests")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT)
    if r.returncode != 0:
        raise BouwFout("De tests slagen niet; er is niets gebouwd. Los de fouten op, of bouw "
                       "alleen voor een proef met --zonder-tests.")


def opruimen() -> None:
    """build/ en dist/ leeg, vóór alles: na een mislukte build staat er nooit een oude .exe."""
    for map_ in (BUILD, DIST):
        shutil.rmtree(map_, ignore_errors=True)


def bouwen(onedir: bool = False) -> Path:
    _kop("Bouwen met PyInstaller")
    opruimen()
    BUILD.mkdir()
    sys.path.insert(0, str(SRC))
    try:
        import zelftest
        modulelijst = zelftest.schrijf_modulelijst(BUILD / zelftest.MODULELIJST, SRC)
    finally:
        sys.path.remove(str(SRC))
    args = pyinstaller_argumenten(BUILD / "pyinstaller", modulelijst, onedir)
    import PyInstaller.__main__
    PyInstaller.__main__.run(args)
    exe = exe_pad(onedir)
    if not exe.is_file():
        raise BouwFout(f"PyInstaller is klaar, maar {exe.relative_to(ROOT)} bestaat niet.")
    return exe


def zelftest_draaien(exe: Path) -> None:
    _kop(f"Zelftest van {exe.relative_to(ROOT)}")
    try:
        r = subprocess.run([str(exe), "--zelftest", "--details"], timeout=ZELFTEST_TIJD)
    except subprocess.TimeoutExpired:
        raise BouwFout(f"De zelftest duurde langer dan {ZELFTEST_TIJD} seconden.") from None
    if r.returncode != 0:
        waarschuwing = build_waarschuwingen()
        raise BouwFout("De gebouwde AVS slaagt niet voor de zelftest (zie hierboven)."
                       + (f" Kijk ook in {waarschuwing.relative_to(ROOT)}." if waarschuwing else ""))


def build_waarschuwingen() -> Path | None:
    """PyInstallers lijst met modules die het niet kon vinden (handig bij een mislukte zelftest)."""
    gevonden = sorted((BUILD / "pyinstaller").glob(f"**/warn-{NAAM}.txt"))
    return gevonden[0] if gevonden else None


def pakketlijst(doel: Path) -> Path:
    """De exacte versies waarmee gebouwd is (pip freeze, zonder AVS zelf)."""
    r = subprocess.run([sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
                       capture_output=True, text=True, check=True)
    regels = [x for x in r.stdout.splitlines() if x and not x.startswith("-e ")]
    kop = (f"# Pakketten waarmee {NAAM} is gebouwd op {time.strftime('%Y-%m-%d %H:%M')} "
           f"(Python {sys.version.split()[0]}).\n"
           f"# Opnieuw bouwen met precies deze set: pip install -r {doel.name}\n")
    doel.write_text(kop + "\n".join(regels) + "\n", encoding="utf-8")
    return doel


def _kop(tekst: str) -> None:
    print(f"\n=== {tekst} ===", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bouw AVS als .exe (zie de uitleg bovenin build.py).")
    parser.add_argument("--onedir", action="store_true", help="een map in plaats van één bestand")
    parser.add_argument("--zonder-tests", action="store_true", help="de tests overslaan (alleen voor een proef)")
    args = parser.parse_args(argv)

    begin = time.monotonic()
    try:
        controleer_omgeving()
        opruimen()
        _controleer_bronnen(bronnen())
        if args.zonder_tests:
            print("LET OP: tests overgeslagen (--zonder-tests). Niet gebruiken voor een echte versie.")
        else:
            tests_draaien()
        exe = bouwen(args.onedir)
        controleer_inhoud(exe, args.onedir)
        zelftest_draaien(exe)
        versies = pakketlijst(DIST / f"{NAAM}-pakketten.txt")
    except BouwFout as e:
        print(f"\nBOUWEN MISLUKT: {e}", file=sys.stderr)
        return 1

    grootte = sum(f.stat().st_size for f in (exe.parent.rglob("*") if args.onedir else [exe]) if f.is_file())
    _kop("Klaar")
    print(f"{exe.relative_to(ROOT)}  ({grootte / 1_000_000:.0f} MB, {time.monotonic() - begin:.0f} s)")
    print(f"Pakketversies: {versies.relative_to(ROOT)}")
    if args.zonder_tests:
        print("Tests zijn overgeslagen: alleen voor een proef.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
