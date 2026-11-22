"""Gedeelde hulpjes voor de tests: één testsleutel, tijdelijke databases en foutcontroles.

Nieuwe, lege databases voor een test: lege_map() / lege_opslag() / opslag(), niet zelf init_db()
(die alleen in tests van init_db zelf). Ze zijn een kopie van één keer init_db() per testrun.

Alleen nepgegevens in een tijdelijke map; de echte sleutelkluis en data/ worden nooit geraakt.
pytest zet zowel src/ (pyproject.toml) als tests/ (deze map) op het pad, dus overal werkt
`from hulp import ...`.

Nepgegevens die meerdere testbestanden gebruiken staan in tests/voorbeeld_*.py (atleet, groep,
ploeg, wedstrijd, training). Een testbestand importeert nooit uit een ander testbestand
(test_testopzet.py controleert dat): zo breekt het wijzigen van de ene test geen andere.
"""

import atexit
import contextlib
import functools
import importlib
import io
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

from db.init_db import init_db, verbind
from db.queries import Opslag, OpslagFout

TESTSLEUTEL = "22" * 32
SRC = Path(__file__).resolve().parents[1] / "src"
TEMPLATES = SRC / "ui" / "templates"
VANDAAG = date(2026, 10, 16)       # een vrijdag: de vaste 'vandaag' van de voorbeelden


@functools.cache
def _sjabloon() -> Path:
    """Eén keer per testrun: een map met nieuwe, lege databases (echte init_db, testsleutel)."""
    map = Path(tempfile.mkdtemp(prefix="avs-test-sjabloon-"))
    atexit.register(shutil.rmtree, map, ignore_errors=True)
    with contextlib.redirect_stdout(io.StringIO()):         # init_db print meldingen
        init_db(map, hoofd=TESTSLEUTEL)
    return map


def lege_databases(map: Path) -> Path:
    """Zet nieuwe, lege databases (testsleutel) in `map`, zoals init_db() dat doet maar veel
    sneller: een kopie van één keer init_db() per testrun. Geeft de map terug."""
    for bestand in _sjabloon().glob("*.db"):
        shutil.copyfile(bestand, Path(map) / bestand.name)
    return Path(map)


@contextlib.contextmanager
def lege_map():
    """Een tijdelijke map met nieuwe, lege databases (zie lege_databases)."""
    with tempfile.TemporaryDirectory() as tmp:
        yield lege_databases(Path(tmp))


@contextlib.contextmanager
def lege_opslag():
    """(Opslag, map) met nieuwe, lege versleutelde databases in een tijdelijke map."""
    with lege_map() as map, Opslag(map=map, hoofd=TESTSLEUTEL) as db:
        yield db, map


@contextlib.contextmanager
def opslag():
    """Alleen de Opslag van lege_opslag(), voor tests die de map niet nodig hebben."""
    with lege_opslag() as (db, _):
        yield db


def verwacht(fout, fn, *args):
    """Roept fn(*args) aan en geeft de fout terug; faalt als die fout er niet komt."""
    try:
        fn(*args)
    except fout as e:
        return e
    raise AssertionError(f"{fout.__name__} verwacht")


def foutmelding(fn, soort=OpslagFout) -> str:
    """De tekst van de fout (standaard OpslagFout) die fn() geeft."""
    return str(verwacht(soort, fn))


def tekst(r) -> str:
    """De tekst van een Flask-antwoord."""
    return r.get_data(as_text=True)


def zet_versie(map: Path, database: str, versie: int) -> None:
    """Doe alsof een database op een andere versie staat (alleen schema_version)."""
    with contextlib.closing(verbind(database, map, TESTSLEUTEL)) as c, c:
        c.execute("DELETE FROM schema_version")
        c.execute("INSERT INTO schema_version (versie) VALUES (?)", (versie,))


def sjabloonformulier(naam="Sprongkracht", rijen=(), totaal=None, totaal_getoond=None, **extra):
    """Een testsjabloonformulier zoals de browser het stuurt. rij = (naam, soort, formule, [parameters])."""
    d = {"naam": naam}
    if totaal is not None:
        d["totaal"] = "1" if totaal else ""
    if totaal_getoond:
        d["totaal_getoond"] = "1"
    for i, (n, soort, formule, pars) in enumerate(rijen):
        d[f"onderdeel-naam-{i}"], d[f"onderdeel-soort-{i}"] = n, soort
        d[f"onderdeel-formule-{i}"], d[f"onderdeel-aantal-{i}"] = formule, str(len(pars))
        for j, p in enumerate(pars):
            d[f"onderdeel-par-{i}-{j}"] = p
    d.update(extra)
    return d


# ---------------- sleutel herstellen (fixtures kluis en data: conftest.py) ----------------
SLEUTEL = "5a" * 32               # de 'opgeschreven' herstelsleutel van de databases in `data`


def app_zonder_sleutel(map: Path):
    """Zoals start() het doet als de sleutel ontbreekt: databases bestaan, kluis is leeg."""
    import pytest
    from db.init_db import SleutelFout
    from ui.app import maak_app
    with pytest.raises(SleutelFout) as e:
        init_db(map)
    app = maak_app(map=map, startfout=str(e.value))
    app.config["TESTING"] = True
    return app.test_client()


def app_client(map: Path):
    """Een Flask-testclient van AVS op de databases in `map` (met de testsleutel)."""
    from ui.app import maak_app
    app = maak_app(map=Path(map), hoofd=TESTSLEUTEL)
    app.config["TESTING"] = True
    return app.test_client()


class _IsEenDatum(type(date)):         # type(date) is gewoon type; zie tests/tijdreis/
    """Metaklasse: isinstance(x, date) blijft werken als `date` de nepklasse is."""
    def __instancecheck__(cls, obj):
        return isinstance(obj, date)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, date)


def vaste_vandaag(monkeypatch, dag: date) -> None:
    """Laat date.today() in alle AVS-modules (src/) `dag` geven, alleen voor deze test.

    Voor tests met vaste datums (bijv. VANDAAG) waarin de code zelf de datum van vandaag
    pakt (`peildatum or date.today()`, een pagina zonder peildatum). Zonder dit gaan zulke
    tests stuk zodra de echte datum voorbij hun vaste datums is.
    Een datum maken geeft gewoon een echte `date` (geen nep-objecten in de database),
    en isinstance(x, date) blijft kloppen.
    """
    class VasteDatum(date, metaclass=_IsEenDatum):
        def __new__(cls, *args, **kwargs):
            return date(*args, **kwargs)

        @classmethod
        def today(cls):
            return dag

    _laad_alle_modules()                    # anders houdt een module die de test later laadt de echte datum
    src = os.path.normcase(str(SRC)) + os.sep          # Windows: 'c:' en 'C:' zijn dezelfde schijf
    for module in list(sys.modules.values()):
        bestand = os.path.normcase(getattr(module, "__file__", None) or "")
        if bestand.startswith(src) and getattr(module, "date", None) is date:
            monkeypatch.setattr(module, "date", VasteDatum)


@functools.cache
def _laad_alle_modules() -> None:
    """Laad alle AVS-modules één keer, zodat vaste_vandaag ze allemaal vastzet, ook een module
    (bijv. ui.app) die een test pas halverwege importeert. Anders hangt het af van de volgorde
    van de tests of zo'n module de vaste of de echte datum ziet."""
    import zelftest
    for naam in zelftest.eigen_modules():
        importlib.import_module(naam)
