"""Gedeelde hulpjes voor de tests: één testsleutel, een tijdelijke database en foutcontroles.

Alleen nepgegevens in een tijdelijke map; de echte sleutelkluis en data/ worden nooit geraakt.
pytest zet zowel src/ (pyproject.toml) als tests/ (deze map) op het pad, dus overal werkt
`from hulp import ...`.
"""

import contextlib
import io
import sys
import tempfile
from datetime import date
from pathlib import Path

from db.init_db import init_db
from db.queries import Opslag

TESTSLEUTEL = "22" * 32
SRC = Path(__file__).resolve().parents[1] / "src"


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


class _IsEenDatum(type):
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

    for module in list(sys.modules.values()):
        bestand = getattr(module, "__file__", None) or ""
        if bestand.startswith(str(SRC)) and getattr(module, "date", None) is date:
            monkeypatch.setattr(module, "date", VasteDatum)
