"""Tests voor het AU-licentienummer (licentienummer van de Atletiekunie) van een atleet:
model, opslag in personen.db (migratie 009), de formulieren 'Nieuwe atleet' en 'Aanpassen',
en de landingspagina.

Alleen nepgegevens en een vaste testsleutel. Werkt met pytest en los:
`python tests/test_au_licentienummer.py`.
"""

import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_app import TESTSLEUTEL, client, tekst  # noqa: E402
from test_landingspagina import opslag, voorbeeld  # noqa: E402

from atleten import aanpassen, beheer, nieuw  # noqa: E402
from db.init_db import init_db  # noqa: E402
from db.queries import Opslag  # noqa: E402
from models import Atleet  # noqa: E402


def _verwacht(fout, fn):
    try:
        fn()
    except fout as e:
        return e
    raise AssertionError(f"{fout.__name__} verwacht")


def _form(db, mid, **wijzig) -> dict:
    form = aanpassen.ingevuld_uit(db, db.atleet(mid))
    form["actief"] = "1" if db.atleet(mid).actief else ""
    form.update(wijzig)
    return form


def test_model():
    assert Atleet("Anna", "Proef", au_licentienummer=" 12 34 567 ").au_licentienummer == "1234567"
    assert Atleet("Anna", "Proef", au_licentienummer="  ").au_licentienummer is None
    assert Atleet("Anna", "Proef").au_licentienummer is None
    _verwacht(ValueError, lambda: Atleet("Anna", "Proef", au_licentienummer="AU-123"))
    assert "1234567" not in repr(Atleet("Anna", "Proef", au_licentienummer="1234567"))   # niet in logs


def test_opslaan_en_zoeken():
    with opslag() as db:
        anna = beheer.nieuwe_atleet(db, "Anna", "Proef", au_licentienummer="1234567")
        assert db.atleet(anna.master_id).au_licentienummer == "1234567"
        assert db.atleet_op_au_licentienummer("1234567").master_id == anna.master_id
        assert db.atleet_op_au_licentienummer("123 4567").master_id == anna.master_id
        assert db.atleet_op_au_licentienummer("7654321") is None
        bas = beheer.nieuwe_atleet(db, "Bas", "Proef")                      # zonder nummer: mag vaker
        beheer.nieuwe_atleet(db, "Cas", "Proef")
        assert db.atleet(bas.master_id).au_licentienummer is None
        # Uniek in de database, ook als de controle in het formulier wordt overgeslagen.
        bas.au_licentienummer = "1234567"
        _verwacht(Exception, lambda: db.atleet_opslaan(bas))
        assert db.atleet(bas.master_id).au_licentienummer is None
        # Andere gegevens bijwerken laat het nummer staan; leegmaken kan.
        anna = db.atleet(anna.master_id)
        anna.specialisatie = "Horden"
        db.atleet_opslaan(anna)
        assert db.atleet(anna.master_id).au_licentienummer == "1234567"
        anna.au_licentienummer = None
        db.atleet_opslaan(anna)
        assert db.atleet_op_au_licentienummer("1234567") is None


def test_migratie_op_bestaande_database():
    """personen.db op versie 8 krijgt de kolom bij de volgende init_db(); de atleten blijven staan."""
    import db.init_db as init_mod
    with tempfile.TemporaryDirectory() as tmp:
        echte_map = init_mod.MIGRATIONS_DIR
        oud = Path(tmp) / "migraties_tot_008"
        shutil.copytree(echte_map, oud)
        for later in (oud / "personen").glob("*.sql"):          # 009 en alles wat daarna kwam
            if int(later.name[:3]) >= 9:
                later.unlink()
        nieuwste = max(int(f.name[:3]) for f in (echte_map / "personen").glob("*.sql"))
        data = Path(tmp) / "data"
        data.mkdir()
        try:
            init_mod.MIGRATIONS_DIR = oud
            with contextlib.redirect_stdout(io.StringIO()):
                init_db(data, hoofd=TESTSLEUTEL)
        finally:
            init_mod.MIGRATIONS_DIR = echte_map
        with Opslag(map=data, hoofd=TESTSLEUTEL) as db:
            assert db.personen.execute("SELECT MAX(versie) FROM schema_version").fetchone()[0] == 8
            kolommen = [r[1] for r in db.personen.execute("PRAGMA table_info(atleet)")]
            assert "au_licentienummer" not in kolommen
            with db.personen:
                db.personen.execute("INSERT INTO atleet (master_id, voornaam, achternaam) VALUES (?, 'Anna', 'Proef')",
                                    ("a" * 32,))
        uitvoer = io.StringIO()
        with contextlib.redirect_stdout(uitvoer):
            init_db(data, hoofd=TESTSLEUTEL)
        assert "009_au_licentienummer.sql" in uitvoer.getvalue()
        with Opslag(map=data, hoofd=TESTSLEUTEL) as db:
            assert db.personen.execute("SELECT MAX(versie) FROM schema_version").fetchone()[0] == nieuwste
            anna = db.atleet("a" * 32)
            assert anna.naam == "Anna Proef" and anna.au_licentienummer is None
            anna.au_licentienummer = "1234567"
            db.atleet_opslaan(anna)
            assert db.atleet_op_au_licentienummer("1234567").naam == "Anna Proef"


def test_formulier_nieuw():
    with opslag() as db:
        beheer.nieuwe_atleet(db, "Bas", "Proef", au_licentienummer="7777777")
        invoer = nieuw.lees_formulier(db, {"voornaam": "Lieke", "achternaam": "Proef", "au_licentienummer": "12 34 567"})
        assert invoer.au_licentienummer == "1234567"
        assert db.atleet(nieuw.aanmaken(db, invoer).master_id).au_licentienummer == "1234567"
        assert nieuw.lees_formulier(db, {"voornaam": "Mo", "achternaam": "Proef"}).au_licentienummer is None
        e = _verwacht(nieuw.InvoerFout, lambda: nieuw.lees_formulier(
            db, {"voornaam": "Mo", "achternaam": "Proef", "au_licentienummer": "AU123"}))
        assert e.fouten == {"au_licentienummer": "Het AU-licentienummer bestaat alleen uit cijfers."}
        e = _verwacht(nieuw.InvoerFout, lambda: nieuw.lees_formulier(
            db, {"voornaam": "Mo", "achternaam": "Proef", "au_licentienummer": "7777777"}))
        assert "Bas Proef" in e.fouten["au_licentienummer"]
        assert "au_licentienummer" in nieuw.formulier(db).waarden


def test_formulier_aanpassen():
    with opslag() as db:
        mid = voorbeeld(db)
        beheer.nieuwe_atleet(db, "Bas", "Proef", au_licentienummer="7777777")
        assert aanpassen.ingevuld_uit(db, db.atleet(mid))["au_licentienummer"] == ""
        w = aanpassen.lees_en_opslaan(db, mid, _form(db, mid, au_licentienummer="1234567"))
        assert w.velden == ["AU-licentienummer"] and db.atleet(mid).au_licentienummer == "1234567"
        assert aanpassen.lees_en_opslaan(db, mid, _form(db, mid)).leeg              # eigen nummer is geen 'dubbel'
        e = _verwacht(nieuw.InvoerFout, lambda: aanpassen.lees_en_opslaan(db, mid, _form(db, mid, au_licentienummer="7777777")))
        assert "Bas Proef" in e.fouten["au_licentienummer"]
        assert db.atleet(mid).au_licentienummer == "1234567"
        aanpassen.lees_en_opslaan(db, mid, _form(db, mid, au_licentienummer=""))   # leegmaken
        assert db.atleet(mid).au_licentienummer is None


def test_paginas():
    with client() as (c, mid, tmp):
        r = c.get("/atleten/nieuw")
        assert 'name="au_licentienummer"' in tekst(r) and "AU-licentienummer" in tekst(r)
        r = c.get(f"/atleet/{mid}/aanpassen")
        assert 'name="au_licentienummer" value=""' in tekst(r)
        assert "licentie " not in tekst(c.get(f"/atleet/{mid}"))
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            form = _form(db, mid, au_licentienummer="1234567")
        r = c.post(f"/atleet/{mid}/aanpassen", data=form, follow_redirects=True)
        assert "Opgeslagen: gewijzigd: AU-licentienummer." in tekst(r) and "licentie 1234567" in tekst(r)
        r = c.post(f"/atleet/{mid}/aanpassen", data={**form, "au_licentienummer": "12a"})
        assert r.status_code == 400 and "Het AU-licentienummer bestaat alleen uit cijfers." in tekst(r)


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
