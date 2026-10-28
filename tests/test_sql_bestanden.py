"""Tests voor de controle op schema's en migraties (db/init_db.py) en InstallatieFout in de app.

Een .exe zonder (alle) SQL-bestanden mag niet crashen of stil migraties overslaan, en een
oudere AVS mag niet doorstarten op databases die hij niet kent. Alleen nepgegevens in een
tijdelijke map, vaste testsleutel. Werkt met pytest.
"""

import contextlib
import io
import shutil
import sys
from pathlib import Path

import pytest

from db import init_db as db_init
from db.init_db import DATABASES, InstallatieFout, controleer_sql_bestanden, init_db, verbind
from ui.app import maak_app
from hulp import TESTSLEUTEL


@pytest.fixture
def sql_kopie(tmp_path, monkeypatch):
    """Een kopie van de SQL-bestanden, zoals ze in de .exe staan (…/db); de module wijst ernaar."""
    kopie = tmp_path / "meegebouwd" / "db"
    kopie.mkdir(parents=True)
    for f in db_init.DB_DIR.glob("schema_*.sql"):
        shutil.copy(f, kopie / f.name)
    shutil.copytree(db_init.DB_DIR / "migrations", kopie / "migrations")
    monkeypatch.setattr(db_init, "SQL_DIR", kopie)
    monkeypatch.setattr(db_init, "MIGRATIONS_DIR", kopie / "migrations")
    return kopie


def _stil(f, *args, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*args, **kw)


def _versie(map: Path, database: str) -> int:
    with contextlib.closing(verbind(database, map, TESTSLEUTEL)) as c:
        return c.execute("SELECT MAX(versie) FROM schema_version").fetchone()[0]


def test_repo_is_compleet():
    controleer_sql_bestanden()                      # de echte bestanden in src/db


def test_kopie_werkt(sql_kopie, tmp_path):
    data = tmp_path / "data"
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    assert all((data / f"{d}.db").exists() for d in DATABASES)


@pytest.mark.parametrize("weg, melding", [
    ("schema_notities.sql", "schema_notities.sql ontbreekt"),
    ("migrations", "de map migrations/ ontbreekt"),
])
def test_ontbrekend_bestand(sql_kopie, tmp_path, weg, melding):
    pad = sql_kopie / weg
    shutil.rmtree(pad) if pad.is_dir() else pad.unlink()
    with pytest.raises(InstallatieFout, match=melding) as e:
        controleer_sql_bestanden()
    assert "Installeer AVS opnieuw" in str(e.value)

    data = tmp_path / "data"
    with pytest.raises(InstallatieFout):
        _stil(init_db, data, hoofd=TESTSLEUTEL)
    assert not data.exists() or not list(data.glob("*.db"))     # niets aangemaakt


def test_lege_of_dubbele_migratie(sql_kopie):
    (sql_kopie / "migrations" / "testen").mkdir(exist_ok=True)
    (sql_kopie / "migrations" / "testen" / "003_leeg.sql").write_text("  \n")
    with pytest.raises(InstallatieFout, match="003_leeg.sql is leeg"):
        controleer_sql_bestanden()
    (sql_kopie / "migrations" / "testen" / "003_leeg.sql").write_text("SELECT 1;")
    (sql_kopie / "migrations" / "testen" / "003_ook.sql").write_text("SELECT 1;")
    with pytest.raises(InstallatieFout, match="hetzelfde nummer"):
        controleer_sql_bestanden()


def test_database_nieuwer_dan_avs(sql_kopie, tmp_path):
    """Oudere AVS op nieuwere databases: weigeren vóór er iets wordt bijgewerkt."""
    data = tmp_path / "data"
    prestaties = sql_kopie / "migrations" / "prestaties"
    laatste = max(prestaties.glob("*.sql"))
    apart = tmp_path / laatste.name
    shutil.move(laatste, apart)                     # prestaties.db blijft één versie achter
    _stil(init_db, data, hoofd=TESTSLEUTEL)
    prestaties_voor = _versie(data, "prestaties")
    personen_voor = _versie(data, "personen")

    shutil.move(apart, laatste)                     # prestaties-migratie weer beschikbaar, maar
    for f in (sql_kopie / "migrations" / "personen").glob("*.sql"):     # personen kent er minder
        if int(f.name[:3]) == personen_voor:
            f.unlink()
    with pytest.raises(InstallatieFout, match=f"personen.db is versie {personen_voor}"):
        _stil(init_db, data, hoofd=TESTSLEUTEL)
    assert _versie(data, "prestaties") == prestaties_voor           # niet half bijgewerkt


def test_sql_map_in_de_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert db_init._sql_map() == tmp_path / "db"
    monkeypatch.delattr(sys, "frozen")
    assert db_init._sql_map() == db_init.DB_DIR


def test_app_bij_installatiefout():
    app = maak_app(startfout="AVS is niet volledig geïnstalleerd: de map migrations/ ontbreekt.",
                   sleutelfout=False)
    c = app.test_client()
    r = c.get("/atleten")
    html = r.get_data(as_text=True)
    assert r.status_code == 500 and "niet volledig geïnstalleerd" in html
    assert "Sleutel herstellen" not in html and "Naar atleten" in html
    html = c.get("/instellingen").get_data(as_text=True)
    assert "niet volledig geïnstalleerd" in html
    assert '<details class="sleutel__herstellen">' in html          # dicht: sleutel is het probleem niet


def test_start_bij_installatiefout(monkeypatch, tmp_path):
    from ui import app as app_mod
    gezien = {}

    def nep_init_db(map=None, hoofd=None):
        raise InstallatieFout("AVS is niet volledig geïnstalleerd: test.")

    def nep_maak_app(map=None, hoofd=None, startfout=None, sleutelfout=True):
        gezien.update(startfout=startfout, sleutelfout=sleutelfout)
        raise SystemExit                            # geen echte server starten

    monkeypatch.setattr(app_mod, "init_db", nep_init_db)
    monkeypatch.setattr(app_mod, "maak_app", nep_maak_app)
    with pytest.raises(SystemExit):
        _stil(app_mod.start, map=tmp_path, browser=False)
    assert gezien == {"startfout": "AVS is niet volledig geïnstalleerd: test.", "sleutelfout": False}
