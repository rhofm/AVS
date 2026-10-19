"""Tests voor de startpagina (src/ui/startpagina.py en de route /).

Tijdelijke map met versleutelde databases, vaste testsleutel, alleen nepgegevens.
Werkt met pytest en los: `python tests/test_startpagina.py`.
"""

import contextlib
import io
import re
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_landingspagina import TESTSLEUTEL, VANDAAG, voorbeeld  # noqa: E402

from db.init_db import init_db  # noqa: E402
from db.queries import Opslag  # noqa: E402
from models import Onderdeel  # noqa: E402
from ui import startpagina  # noqa: E402
from ui.app import maak_app  # noqa: E402


@contextlib.contextmanager
def opslag(met_voorbeeld: bool = True):
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            if met_voorbeeld:
                db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
                db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
                voorbeeld(db)
            yield db, Path(tmp)


def test_tegels_volgorde_en_cijfers():
    with opslag() as (db, _):
        t = startpagina.tegels(db, VANDAAG)
        assert [x.sleutel for x in t] == ["atleten", "groepen", "ploegen", "wedstrijden"]
        atleten, groepen, ploegen, wedstrijden = t
        assert (atleten.cijfer, atleten.cijfer_label) == ("1", "actieve atleet")
        assert (groepen.cijfer, groepen.cijfer_label) == ("1", "groep")
        assert (ploegen.cijfer, ploegen.cijfer_label) == ("0", "komende ploegen")
        # 'Vorig seizoen' ligt in het verleden en telt niet mee.
        assert (wedstrijden.cijfer, wedstrijden.cijfer_label) == ("2", "komende wedstrijden")
        assert wedstrijden.extra.startswith("Eerstvolgende: Clubkampioenschappen")
        # Na de laatste wedstrijd: niets meer gepland.
        later = startpagina.tegels(db, VANDAAG + timedelta(days=60))[3]
        assert later.cijfer == "0" and later.extra is None


def test_tegels_lege_database():
    with opslag(met_voorbeeld=False) as (db, _):
        t = startpagina.tegels(db, VANDAAG)
        assert [x.cijfer for x in t] == ["0", "0", "0", "0"]
        assert t[0].cijfer_label == "actieve atleten"


def test_startpagina_route():
    with opslag() as (_, tmp):
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        r = c.get("/")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        # Vier grote tegels, elk naar een werkende pagina.
        tegels = re.findall(r'<a class="tegel[^"]*" href="(/[a-z]+)"', html)
        assert tegels == ["/atleten", "/groepen", "/ploegen", "/wedstrijden"]
        for pad in tegels:
            assert c.get(pad).status_code == 200, pad
        # Bovenin alleen Importeren en Instellingen, geen volledig hoofdmenu.
        assert 'href="/importeren"' in html and 'href="/instellingen"' in html
        assert 'aria-label="Hoofdmenu"' not in html
        # Geen namen van atleten op de startpagina.
        assert "Anna" not in html and "Voorbeeld" not in html
        # Andere pagina's houden het volledige menu.
        assert 'aria-label="Hoofdmenu"' in c.get("/atleten").get_data(as_text=True)
        assert 'aria-label="Hoofdmenu"' in c.get("/ploegen").get_data(as_text=True)


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
