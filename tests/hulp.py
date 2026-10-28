"""Gedeelde hulpjes voor de tests: één testsleutel, een tijdelijke database en foutcontroles.

Alleen nepgegevens in een tijdelijke map; de echte sleutelkluis en data/ worden nooit geraakt.
pytest zet zowel src/ (pyproject.toml) als tests/ (deze map) op het pad, dus overal werkt
`from hulp import ...`.
"""

import contextlib
import io
import tempfile
from pathlib import Path

from db.init_db import init_db
from db.queries import Opslag

TESTSLEUTEL = "22" * 32


@contextlib.contextmanager
def lege_opslag():
    """(Opslag, map) met nieuwe, lege versleutelde databases in een tijdelijke map."""
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            yield db, Path(tmp)


@contextlib.contextmanager
def opslag():
    """Alleen de Opslag van lege_opslag(), voor tests die de map niet nodig hebben."""
    with lege_opslag() as (db, _):
        yield db


def verwacht(fout, fn):
    """Roept fn() aan en geeft de fout terug; faalt als die fout er niet komt."""
    try:
        fn()
    except fout as e:
        return e
    raise AssertionError(f"{fout.__name__} verwacht")


def tekst(r) -> str:
    """De tekst van een Flask-antwoord."""
    return r.get_data(as_text=True)


def app_client(map: Path):
    """Een Flask-testclient van AVS op de databases in `map` (met de testsleutel)."""
    from ui.app import maak_app
    app = maak_app(map=Path(map), hoofd=TESTSLEUTEL)
    app.config["TESTING"] = True
    return app.test_client()
