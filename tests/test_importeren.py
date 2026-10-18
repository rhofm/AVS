"""Tests voor de importeerpagina (src/ui/importeren.py en de routes /importeren...).

Tijdelijke map met versleutelde databases, vaste testsleutel, alleen nepgegevens.
Werkt met pytest en los: `python tests/test_importeren.py`.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_startpagina import opslag  # noqa: E402
from test_landingspagina import TESTSLEUTEL  # noqa: E402

from ui import importeren  # noqa: E402
from ui.app import maak_app  # noqa: E402


def _client(tmp: Path):
    app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
    app.config["TESTING"] = True
    return app.test_client()


def test_keuzes():
    assert [k.sleutel for k in importeren.KEUZES] == ["atleet", "groep", "wedstrijd"]
    assert set(importeren.PER_SLEUTEL) == {"atleet", "groep", "wedstrijd"}
    for k in importeren.KEUZES:
        assert k.titel and k.uitleg and k.bron and k.nodig


def test_importeerpagina():
    with opslag() as (_, tmp):
        c = _client(tmp)
        r = c.get("/importeren")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "<h1 class=\"startkop__titel\">Importeren</h1>" in html
        # Drie tegels, elk naar een eigen importpagina.
        tegels = re.findall(r'<a class="tegel[^"]*" href="(/importeren/[a-z]+)"', html)
        assert tegels == ["/importeren/atleet", "/importeren/groep", "/importeren/wedstrijd"]
        # 'Importeren' is actief in het hoofdmenu, en er is een weg terug naar Start.
        assert 'href="/importeren" aria-current="page"' in html
        assert "&larr; Start" in html
        # Geen namen van atleten.
        assert "Anna" not in html and "Voorbeeld" not in html


def test_importpaginas_werken_en_gaan_terug_naar_importeren():
    with opslag() as (_, tmp):
        c = _client(tmp)
        for soort, titel in (("atleet", "Atleet importeren"), ("groep", "Groep importeren"),
                             ("wedstrijd", "Wedstrijd importeren")):
            r = c.get(f"/importeren/{soort}")
            html = r.get_data(as_text=True)
            assert r.status_code == 200, soort
            assert titel in html
            assert 'href="/importeren">&larr; Importeren' in html
            assert 'href="/importeren" aria-current="page"' in html
        assert c.get("/importeren/iets-anders").status_code == 404


def test_startpagina_knop_gaat_naar_importeren():
    with opslag() as (_, tmp):
        c = _client(tmp)
        assert 'href="/importeren"' in c.get("/").get_data(as_text=True)
        assert "Deze pagina komt nog" not in c.get("/importeren").get_data(as_text=True)


if __name__ == "__main__":
    for naam, f in list(globals().items()):
        if naam.startswith("test_") and callable(f):
            f()
            print("ok", naam)
