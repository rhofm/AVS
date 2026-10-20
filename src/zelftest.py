"""Zelftest: werkt deze AVS (vooral: de gebouwde .exe) volledig?

Gebruik:
    python src --zelftest        vanuit de broncode
    AVS.exe --zelftest           de gebouwde .exe (build.py doet dit na elke build)

Controleert alles wat in een .exe kan ontbreken, zonder de echte gegevens of de
sleutelkluis aan te raken: alles gebeurt in een tijdelijke map met een testsleutel
(die nergens wordt bewaard). Er wordt niets via internet opgehaald.

Elke controle staat los, zodat je in één keer ziet wat er allemaal mis is.
Uitkomst: 0 als alles goed is, anders 1.

De lijst met eigen modules komt vanuit de broncode uit src/ zelf. In de .exe staat
die lijst in `zelftest_modules.txt` (build.py schrijft hem met schrijf_modulelijst()),
want daar is src/ niet meer te doorzoeken; zo valt een module op die PyInstaller
niet heeft meegenomen.
"""

from __future__ import annotations

import contextlib
import io
import secrets
import sys
import tempfile
import traceback
from importlib import import_module
from pathlib import Path
from typing import Callable

SRC = Path(__file__).resolve().parent
MODULELIJST = "zelftest_modules.txt"

#: Pakketten van buiten AVS die in de .exe moeten zitten (importnaam).
EXTERNE_MODULES = (
    "flask", "jinja2", "markupsafe", "sqlcipher3", "keyring", "requests", "curl_cffi",
    "bs4", "yaml", "numpy", "scipy.optimize", "fpdf",
)


# ============================================================
# Eigen modules
# ============================================================
def eigen_modules(src: Path = SRC) -> list[str]:
    """Alle eigen modules (bijv. 'ploeg.regels') uit de bronmap, op naam gesorteerd."""
    uit = []
    for pad in sorted(src.rglob("*.py")):
        deel = pad.relative_to(src)
        if "__pycache__" in deel.parts or deel.name == "__main__.py" or len(deel.parts) == 1:
            continue                                  # losse bestanden in src/ zelf (__main__, zelftest)
        onderdelen = list(deel.with_suffix("").parts)
        if onderdelen[-1] == "__init__":
            onderdelen.pop()
        uit.append(".".join(onderdelen))
    return sorted(set(uit))


def schrijf_modulelijst(doel: Path, src: Path = SRC) -> Path:
    """Voor build.py: de lijst met eigen modules, om mee te bouwen in de .exe."""
    doel = Path(doel)
    doel.write_text("\n".join(eigen_modules(src)) + "\n", encoding="utf-8")
    return doel


def _te_importeren_modules() -> list[str]:
    if getattr(sys, "frozen", False):
        lijst = Path(getattr(sys, "_MEIPASS", "")) / MODULELIJST
        if not lijst.is_file():
            raise RuntimeError(f"{MODULELIJST} ontbreekt in de .exe (build.py schrijft hem).")
        return [r.strip() for r in lijst.read_text(encoding="utf-8").splitlines() if r.strip()]
    return eigen_modules()


# ============================================================
# De controles (elk: geeft een korte uitleg terug of gooit een fout)
# ============================================================
def _modules() -> str:
    namen = _te_importeren_modules()
    mislukt = []
    for naam in namen:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                import_module(naam)
        except Exception as e:                        # noqa: BLE001 - alles melden
            mislukt.append(f"{naam} ({type(e).__name__}: {e})")
    if mislukt:
        raise RuntimeError("niet te importeren: " + "; ".join(mislukt))
    return f"{len(namen)} eigen modules"


def _externe_modules() -> str:
    mislukt = []
    for naam in EXTERNE_MODULES:
        try:
            import_module(naam)
        except Exception as e:                        # noqa: BLE001
            mislukt.append(f"{naam} ({type(e).__name__}: {e})")
    if mislukt:
        raise RuntimeError("ontbreekt: " + "; ".join(mislukt))
    return f"{len(EXTERNE_MODULES)} pakketten"


def _sql_bestanden() -> str:
    from db import init_db
    init_db.controleer_sql_bestanden()
    aantal = sum(len(init_db._migraties(d)) for d in init_db.DATABASES)
    return f"{len(init_db.DATABASES)} schema's, {aantal} migraties ({init_db.SQL_DIR})"


def _databases(tmp: Path) -> str:
    from db.init_db import DATABASES, db_pad, init_db
    from db.queries import Opslag
    sleutel = secrets.token_hex(32)                   # wegwerpsleutel, alleen voor deze test
    with contextlib.redirect_stdout(io.StringIO()):
        init_db(tmp, hoofd=sleutel)
    with Opslag(map=tmp, hoofd=sleutel) as db:
        db.atleten()
    if db_pad("personen", tmp).read_bytes()[:16] == b"SQLite format 3\x00":
        raise RuntimeError("personen.db is NIET versleuteld")
    return f"{len(DATABASES)} versleutelde databases aangemaakt en geopend"


def _sleutelkluis() -> str:
    import keyring
    if sys.platform == "win32":
        import keyring.backends.Windows  # noqa: F401  (build.py: --hidden-import)
    kluis = keyring.get_keyring()
    naam = f"{type(kluis).__module__}.{type(kluis).__name__}"
    if "fail" in naam.lower() and sys.platform == "win32":
        raise RuntimeError(f"geen bruikbare sleutelkluis ({naam})")
    return naam


def _config() -> str:
    from ploeg import config, punten, regels
    bestanden = regels.bestanden()
    if not bestanden:
        raise RuntimeError(f"geen regelbestanden gevonden in {config.gezocht_in('ploeg_regels')}")
    for naam in bestanden:
        regels.laad(naam)                             # elk regelbestand is geldig (ook tegen de puntentelling)
    punten.puntentelling()
    return f"{len(bestanden)} regelbestanden geldig, puntentelling {punten.STANDAARD_UITGAVE}"


def _strategieen() -> str:
    from ploeg.strategieen import STRATEGIEEN
    if not STRATEGIEEN:
        raise RuntimeError("geen strategieën geregistreerd")
    return ", ".join(sorted(STRATEGIEEN))


def _optimaliseren() -> str:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    # max x + y met x + y <= 1.5, x en y geheel tussen 0 en 1 -> optimum 1
    r = milp(c=-np.ones(2), constraints=LinearConstraint(np.ones((1, 2)), ub=1.5),
             integrality=np.ones(2), bounds=Bounds(0, 1))
    if not r.success or round(-r.fun) != 1:
        raise RuntimeError(f"milp gaf een verkeerde uitkomst ({r.message})")
    return "scipy.optimize.milp werkt"


def _pdf() -> str:
    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(text="AVS zelftest")
    inhoud = bytes(pdf.output())
    if not inhoud.startswith(b"%PDF"):
        raise RuntimeError("geen geldige PDF")
    return f"PDF van {len(inhoud)} bytes"


def _importeren_atletieknu() -> str:
    from curl_cffi import requests as curl_requests
    with curl_requests.Session(impersonate="chrome"):  # laadt de meegeleverde libcurl; geen verbinding
        pass
    return "curl_cffi kan Chrome nadoen"


def _webinterface(tmp: Path) -> str:
    from ui.app import maak_app
    app = maak_app(map=tmp, startfout="zelftest", sleutelfout=False)
    namen = [n for n in app.jinja_env.list_templates() if n.endswith(".html")]
    if not namen:
        raise RuntimeError("geen templates gevonden")
    for naam in namen:
        app.jinja_env.get_template(naam)              # elk template is te lezen en klopt
    c = app.test_client()
    for pad in ("/static/avs.css", "/static/filter.js", "/static/sorteer.js", "/instellingen"):
        r = c.get(pad)
        if r.status_code != 200:
            raise RuntimeError(f"{pad} gaf {r.status_code}")
    return f"{len(namen)} templates, statische bestanden en de pagina Instellingen"


# ============================================================
# Uitvoeren
# ============================================================
def controles(tmp: Path) -> list[tuple[str, Callable[[], str]]]:
    return [
        ("eigen modules", _modules),
        ("pakketten", _externe_modules),
        ("SQL-bestanden", _sql_bestanden),
        ("databases", lambda: _databases(tmp / "data")),
        ("sleutelkluis", _sleutelkluis),
        ("config", _config),
        ("strategieën", _strategieen),
        ("optimaliseren", _optimaliseren),
        ("PDF", _pdf),
        ("atletiek.nu", _importeren_atletieknu),
        ("webinterface", lambda: _webinterface(tmp / "web")),
    ]


def zelftest(uitvoer=None, details: bool = False) -> int:
    """Draai alle controles en schrijf per regel 'ok' of 'FOUT'. Geeft 0 (goed) of 1."""
    uitvoer = uitvoer or sys.stdout
    fouten = 0
    print(f"AVS zelftest ({'gebouwde .exe' if getattr(sys, 'frozen', False) else 'broncode'}, "
          f"Python {sys.version.split()[0]})", file=uitvoer)
    with tempfile.TemporaryDirectory(prefix="avs_zelftest_") as t:
        for naam, controle in controles(Path(t)):
            try:
                uitleg = controle()
                print(f"  ok    {naam}: {uitleg}", file=uitvoer)
            except Exception as e:                    # noqa: BLE001 - elke fout melden, dan verder
                fouten += 1
                print(f"  FOUT  {naam}: {type(e).__name__}: {e}", file=uitvoer)
                if details:
                    traceback.print_exc(file=uitvoer)
    print("Alles in orde." if not fouten else f"{fouten} controle(s) mislukt.", file=uitvoer)
    return 1 if fouten else 0
