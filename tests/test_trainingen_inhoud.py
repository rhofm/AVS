"""Tests voor de inhoud van trainingen (personen-migratie 005) en de markdown-weergave.

Training: groep, datum, warming-up, kern A, kern B, cooling-down, notities.
Afwijkende training: variant van de gewone training voor enkele atleten
(training_atleet, lang formaat). Alleen nepgegevens en een vaste testsleutel.
Werkt met pytest en los: `python tests/test_trainingen_inhoud.py`.
"""

import contextlib
import io
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from db.init_db import DB_DIR, init_db, verbind  # noqa: E402
from db.queries import Opslag, OpslagFout  # noqa: E402
from groepen import trainingen as trainingsbeheer  # noqa: E402
from models import Absentie, Atleet, Groep, Training  # noqa: E402
from ui.markdown import naar_html  # noqa: E402

TESTSLEUTEL = "55" * 32
DINSDAG = date(2026, 10, 20)

KERN_A = """# Starts
- 6x **30 m** uit startblok
- *rustig* teruglopen
Herstel 2 min"""


@contextlib.contextmanager
def opslag():
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            yield db, Path(tmp)


def _verwacht(fout, fn) -> None:
    try:
        fn()
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


def _basis(db):
    anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
    bas = db.atleet_opslaan(Atleet("Bas", "Bakker"))
    cor = db.atleet_opslaan(Atleet("Cor", "Claassen"))
    buiten = db.atleet_opslaan(Atleet("Dirk", "Buiten"))
    g = db.groep_opslaan(Groep("Sprintgroep", leden=[anna.master_id, bas.master_id, cor.master_id]))
    t = db.training_opslaan(Training(g.id, DINSDAG, "Starts", "Veld 2 bezet, **binnenbaan**.",
                                     warming_up="10 min inlopen\nABC", kern_a=KERN_A, kern_b="3x 150 m",
                                     cooling_down="Uitlopen"))
    return anna, bas, cor, buiten, g, t


def test_velden_opslaan_en_lezen():
    with opslag() as (db, _):
        _, _, _, _, g, t = _basis(db)
        terug = db.training(t.id)
        assert (terug.warming_up, terug.kern_a, terug.kern_b, terug.cooling_down) == (
            "10 min inlopen\nABC", KERN_A, "3x 150 m", "Uitlopen")
        assert terug.notities == "Veld 2 bezet, **binnenbaan**." and not terug.is_afwijkend
        assert [titel for titel, _ in terug.onderdelen] == ["Warming-up", "Kern A", "Kern B", "Cooling-down"]
        # Lege tekst wordt None; een leeg onderdeel valt weg uit `onderdelen`.
        terug.kern_b = "   "
        db.training_opslaan(Training(**{**{f: getattr(terug, f) for f in terug.__slots__}}))
        assert db.training(t.id).kern_b is None
        assert [titel for titel, _ in db.training(t.id).onderdelen] == ["Warming-up", "Kern A", "Cooling-down"]
        assert len(db.trainingen(g.id)) == 1


def test_afwijkende_training():
    with opslag() as (db, _):
        anna, bas, cor, buiten, g, t = _basis(db)
        v = db.training_opslaan(Training(0, date(2000, 1, 1), "Horden i.p.v. starts",
                                         kern_a="5x horden 76,2 cm", hoofdtraining_id=t.id,
                                         atleten=[bas.master_id, cor.master_id]))
        # Groep en datum komen van de gewone training.
        assert (v.groep_id, v.datum) == (g.id, DINSDAG)
        assert [x.id for x in db.varianten(t.id)] == [v.id]
        assert db.training(v.id).atleten == [bas.master_id, cor.master_id]           # op achternaam
        # De lijst trainingen van de groep (en dus de absentie) ziet alleen de gewone training.
        assert [x.id for x in db.trainingen(g.id)] == [t.id]
        assert db.training_voor_atleet(t.id, bas.master_id).id == v.id
        assert db.training_voor_atleet(t.id, anna.master_id).id == t.id
        assert db.training_voor_atleet(v.id, anna.master_id).id == t.id

        # Regels.
        _verwacht(OpslagFout, lambda: db.training_opslaan(Training(g.id, DINSDAG, atleten=[anna.master_id])))
        _verwacht(OpslagFout, lambda: db.training_opslaan(Training(0, DINSDAG, hoofdtraining_id=t.id)))   # geen atleten
        _verwacht(OpslagFout, lambda: db.training_opslaan(
            Training(0, DINSDAG, hoofdtraining_id=t.id, atleten=[buiten.master_id])))             # niet in groep
        _verwacht(OpslagFout, lambda: db.training_opslaan(
            Training(0, DINSDAG, hoofdtraining_id=t.id, atleten=[bas.master_id])))                # al in een variant
        _verwacht(OpslagFout, lambda: db.training_opslaan(
            Training(0, DINSDAG, hoofdtraining_id=v.id, atleten=[anna.master_id])))               # variant van variant
        _verwacht(OpslagFout, lambda: db.training_opslaan(
            Training(0, DINSDAG, hoofdtraining_id=999, atleten=[anna.master_id])))
        # Aanwezigheid hoort bij de gewone training.
        _verwacht(OpslagFout, lambda: db.absentie_opslaan(Absentie(v.id, bas.master_id, "aanwezig")))
        db.absentie_opslaan(Absentie(t.id, bas.master_id, "aanwezig"))

        # Variant aanpassen: atleten wisselen.
        v.atleten = [cor.master_id]
        db.training_opslaan(v)
        assert db.training(v.id).atleten == [cor.master_id]
        assert db.training_voor_atleet(t.id, bas.master_id).id == t.id

        # Atleet weg -> uit de variant; gewone training weg -> varianten en absentie mee.
        db.atleet_verwijderen(cor.master_id)
        assert db.training(v.id).atleten == []
        db.training_verwijderen(t.id)
        assert db.training(v.id) is None and db.absenties(t.id) == []


def test_trainingpagina_en_html():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        _, bas, _, _, _, t = _basis(db)
        v = db.training_opslaan(Training(0, DINSDAG, "Horden", kern_a="5x horden", hoofdtraining_id=t.id,
                                         atleten=[bas.master_id]))
        tp = trainingsbeheer.trainingpagina(db, v.id, peildatum=DINSDAG)          # variant -> pagina gewone training
        assert tp.training.id == t.id and [(x.id, [a.naam for a in at]) for x, at in tp.varianten] == [
            (v.id, ["Bas Bakker"])]
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        html = app.test_client().get(f"/training/{t.id}").get_data(as_text=True)
        for kop in ("Warming-up", "Kern A", "Kern B", "Cooling-down", "Notities", "Afwijkende training: Horden"):
            assert kop in html, kop
        assert "<strong>30 m</strong>" in html and "<li>" in html and "<strong>binnenbaan</strong>" in html
        assert "Bas Bakker" in html


def test_markdown_veilig_en_beperkt():
    assert naar_html(None) == "" and naar_html("  ") == ""
    html = str(naar_html(KERN_A))
    assert html == ("<h3>Starts</h3>\n<ul>\n<li>6x <strong>30 m</strong> uit startblok</li>\n"
                    "<li><em>rustig</em> teruglopen</li>\n</ul>\n<p>Herstel 2 min</p>")
    assert str(naar_html("1. Inlopen\n2. ABC")) == "<ol>\n<li>Inlopen</li>\n<li>ABC</li>\n</ol>"
    assert str(naar_html("regel 1\nregel 2\n\nalinea 2")) == "<p>regel 1<br>regel 2</p>\n<p>alinea 2</p>"
    # HTML in een notitie wordt nooit uitgevoerd.
    gevaarlijk = str(naar_html('<script>alert(1)</script> **<b>x</b>**'))
    assert "<script>" not in gevaarlijk and "&lt;script&gt;" in gevaarlijk and "<b>" not in gevaarlijk
    # Rekenwerk met sterretjes en namen met underscores blijven zoals ze zijn.
    assert str(naar_html("3 * 4 * 5")) == "<p>3 * 4 * 5</p>"
    assert str(naar_html("bestand_naam_v2")) == "<p>bestand_naam_v2</p>"


def test_oude_inhoud_wordt_notities():
    """Een personen.db van vóór migratie 005: `inhoud` gaat naar `notities`, niets gaat verloren."""
    with tempfile.TemporaryDirectory() as tmp:
        # closing(): `with conn` alleen commit, maar sluit niet; op Windows blijft het bestand
        # dan vergrendeld en kan de tijdelijke map niet worden opgeruimd.
        with contextlib.closing(verbind("personen", Path(tmp), TESTSLEUTEL)) as c:
            c.executescript((DB_DIR / "schema_personen.sql").read_text(encoding="utf-8"))
            c.execute("INSERT INTO groep (id, naam) VALUES (1, 'Oud')")
            c.execute("INSERT INTO training (groep_id, datum, onderwerp, inhoud) "
                      "VALUES (1, '2026-09-01', 'Kracht', 'Squats 3x8\nLunges')")
            c.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            t = db.trainingen(1)[0]
            assert (t.onderwerp, t.notities, t.warming_up) == ("Kracht", "Squats 3x8\nLunges", None)
            kolommen = {r[1] for r in db.personen.execute("PRAGMA table_info(training)")}
            assert "inhoud" not in kolommen and {"warming_up", "kern_a", "kern_b", "cooling_down"} <= kolommen


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
