"""Tests voor het exporteren van een training als markdown (.md) of PDF (ui.export,
route /training/<id>/export.<md|pdf>). Namen bij afwijkende trainingen alleen met ?namen=1.

Alleen nepgegevens en een vaste testsleutel. De PDF-test wordt overgeslagen als fpdf2
niet is geïnstalleerd. Werkt met pytest en los: `python tests/test_training_export.py`.
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_trainingen_inhoud import TESTSLEUTEL, _basis, opslag  # noqa: E402

from groepen import trainingen as trainingsbeheer  # noqa: E402
from ui import export  # noqa: E402

HEEFT_FPDF = importlib.util.find_spec("fpdf") is not None


def _met_variant(db):
    anna, bas, cor, buiten, g, t = _basis(db)
    db.groep_trainingsdagen_opslaan(g.id, {"dinsdag": "18:30"})
    trainingsbeheer.variant_toevoegen(db, t.id, {"onderwerp": "Revalidatie", "kern_a": "30 min fietsen"},
                                      [anna.master_id])
    return anna, g, t


def test_markdown():
    with opslag() as (db, _):
        anna, g, t = _met_variant(db)
        tp = trainingsbeheer.trainingpagina(db, t.id)
        e = export.trainingsexport(tp)
        assert e.bestandsnaam == "training-2026-10-20-sprintgroep"
        md = export.naar_markdown(e)
        assert md.startswith("# Starts\n") and "**Sprintgroep · dinsdag 20 oktober 2026 · 18:30**" in md
        for kop in ("## Warming-up", "## Kern A", "## Kern B", "## Cooling-down", "## Notities"):
            assert kop in md, kop
        assert "### Starts" in md                                   # kopje in de tekst zakt onder 'Kern A'
        assert "## Afwijkende training: Revalidatie" in md and "### Kern A\n\n30 min fietsen" in md
        assert "*Voor 1 atleet*" in md and "Anna" not in md          # standaard geen namen
        md = export.naar_markdown(export.trainingsexport(tp, namen=True))
        assert "*Voor Anna Aalbers*" in md


def test_pdf():
    if not HEEFT_FPDF:
        print("overgeslagen: fpdf2 niet geïnstalleerd")
        return
    with opslag() as (db, _):
        _, _, t = _met_variant(db)
        tp = trainingsbeheer.trainingpagina(db, t.id)
        tp.training.notities = "Pionnen – 10 stuks… 🏃 en ‘aanhalingstekens’"     # buiten Windows-1252 valt weg
        pdf = export.naar_pdf(export.trainingsexport(tp, namen=True))
        assert pdf.startswith(b"%PDF") and len(pdf) > 1000


def test_routes():
    from ui.app import maak_app
    with opslag() as (db, tmp):
        anna, g, t = _met_variant(db)
        app = maak_app(map=tmp, hoofd=TESTSLEUTEL)
        app.config["TESTING"] = True
        c = app.test_client()
        html = c.get(f"/training/{t.id}").get_data(as_text=True)
        assert f'/training/{t.id}/export.md' in html and f'/training/{t.id}/export.pdf' in html
        assert 'name="namen"' in html

        r = c.get(f"/training/{t.id}/export.md")
        assert r.status_code == 200 and r.mimetype == "text/markdown"
        assert r.headers["Content-Disposition"] == 'attachment; filename="training-2026-10-20-sprintgroep.md"'
        assert "Anna" not in r.get_data(as_text=True)
        assert "Anna Aalbers" in c.get(f"/training/{t.id}/export.md?namen=1").get_data(as_text=True)
        if HEEFT_FPDF:
            r = c.get(f"/training/{t.id}/export.pdf")
            assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
        assert c.get(f"/training/{t.id}/export.docx").status_code == 404
        assert c.get("/training/9999/export.md").status_code == 404

        # Zonder afwijkende trainingen geen keuze voor namen.
        db.training_verwijderen(db.varianten(t.id)[0].id)
        assert 'name="namen"' not in c.get(f"/training/{t.id}").get_data(as_text=True)


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("ok ", naam)
