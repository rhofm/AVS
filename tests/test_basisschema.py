"""De basisschema's (src/db/schema_<database>.sql) zijn bevroren.

In oktober 2026 zijn de oude migraties samengevoegd in de basisschema's: een nieuwe
database begint meteen op personen 11, prestaties 4, testen 2, trainingsschema 2
(de rest op 1). tests/fixtures/basisschema.json is de structuur die een database
toen had na versie 1 + alle oude migraties: tabellen, kolommen (volgorde, type,
NOT NULL, standaardwaarde, sleutel), CHECKs, foreign keys, indexen en views. Geen
gegevens, alleen de definities.

Deze test bouwt nieuwe databases uit alleen de basisschema's (zonder migraties) en
vergelijkt ze daarmee. Slaagt hij niet, dan is een basisschema aangepast: zet de
wijziging terug en maak er een migratie van (migrations/<database>/NNN_..., met
een nummer na de basisversie). Bestaande databases krijgen een basisschema nooit
opnieuw, dus een wijziging daarin zou alleen nieuwe installaties raken.

Alleen nepgegevens in een tijdelijke map, vaste testsleutel.
"""

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from db import init_db as db_init
from db.init_db import DATABASES, huidige_versie, init_db, verbind
from hulp import TESTSLEUTEL

FIXTURE = Path(__file__).parent / "fixtures" / "basisschema.json"


def _norm(sql: str | None) -> str | None:
    """SQL zonder commentaar en opmaak, zodat alleen de inhoud telt."""
    if sql is None:
        return None
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"\s+", " ", sql).strip()
    sql = re.sub(r"\s*([(),;])\s*", r"\1", sql)
    return re.sub(r"(?i)^CREATE (TABLE|INDEX|UNIQUE INDEX|VIEW) IF NOT EXISTS ", r"CREATE \1 ", sql)


def structuur(conn) -> dict:
    """Alles wat de vorm van een database bepaalt, per object ('table:atleet', 'index:...')."""
    uit = {}
    for soort, naam, tabel, sql in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"):
        d = {"tbl": tabel, "sql": _norm(sql)}
        if soort in ("table", "view"):
            d["kolommen"] = [tuple(r) for r in conn.execute(f"PRAGMA table_xinfo('{naam}')")]
        if soort == "table":
            d["fk"] = [tuple(r) for r in conn.execute(f"PRAGMA foreign_key_list('{naam}')")]
            d["indexen"] = sorted(tuple(r)[1:] for r in conn.execute(f"PRAGMA index_list('{naam}')"))
        if soort == "index":
            d["xinfo"] = [tuple(r) for r in conn.execute(f"PRAGMA index_xinfo('{naam}')")]
        uit[f"{soort}:{naam}"] = d
    return json.loads(json.dumps(uit))           # tuples -> lijsten, net als in het JSON-bestand


@pytest.fixture(scope="module")
def nieuw(tmp_path_factory):
    """Databases uit alleen de basisschema's: de migratiemap is leeg."""
    tmp = tmp_path_factory.mktemp("basisschema")
    (tmp / "migraties").mkdir()
    echte = db_init.MIGRATIONS_DIR
    db_init.MIGRATIONS_DIR = tmp / "migraties"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(tmp / "data", hoofd=TESTSLEUTEL)
    finally:
        db_init.MIGRATIONS_DIR = echte
    uit = {}
    for d in DATABASES:
        with contextlib.closing(verbind(d, tmp / "data", TESTSLEUTEL)) as c:
            uit[d] = {"versie": huidige_versie(c), "objecten": structuur(c)}
    return uit


@pytest.fixture(scope="module")
def verwacht():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_compleet(verwacht):
    assert set(verwacht) == set(DATABASES)


@pytest.mark.parametrize("database", DATABASES)
def test_basisschema_ongewijzigd(database, nieuw, verwacht):
    oud, nu = verwacht[database], nieuw[database]
    assert nu["versie"] == oud["versie"] == db_init.basisversie(database)
    verschillen = []
    for k in sorted(set(oud["objecten"]) | set(nu["objecten"])):
        a, b = oud["objecten"].get(k), nu["objecten"].get(k)
        if a is None:
            verschillen.append(f"nieuw in schema_{database}.sql: {k}")
        elif b is None:
            verschillen.append(f"weg uit schema_{database}.sql: {k}")
        else:
            verschillen += [f"{k} ({veld}): was {a[veld]!r}, nu {b.get(veld)!r}" for veld in a if a[veld] != b.get(veld)]
    assert not verschillen, (f"schema_{database}.sql is aangepast; maak er een migratie van.\n"
                             + "\n".join(verschillen))


def test_vergelijking_ziet_wijzigingen(verwacht, tmp_path, monkeypatch):
    """De vergelijking zelf: een weggelaten CHECK en een andere kolomvolgorde vallen op."""
    sql = tmp_path / "db"
    sql.mkdir()
    for f in db_init.SQL_DIR.glob("schema_*.sql"):
        sql.joinpath(f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    (sql / "migrations").mkdir()
    schema = sql / "schema_personen.sql"
    tekst = schema.read_text(encoding="utf-8")
    for oud, nieuw_ in [("CHECK (herhalen IN (0, 1))", ""),
                        ("    kern_a           TEXT,\n    kern_b           TEXT,",
                         "    kern_b           TEXT,\n    kern_a           TEXT,")]:
        assert tekst.count(oud) == 1, oud
        tekst = tekst.replace(oud, nieuw_)
    schema.write_text(tekst, encoding="utf-8")
    monkeypatch.setattr(db_init, "SQL_DIR", sql)
    monkeypatch.setattr(db_init, "MIGRATIONS_DIR", sql / "migrations")
    with contextlib.redirect_stdout(io.StringIO()):
        init_db(tmp_path / "data", hoofd=TESTSLEUTEL)
    with contextlib.closing(verbind("personen", tmp_path / "data", TESTSLEUTEL)) as c:
        nu = structuur(c)
    oud = verwacht["personen"]["objecten"]
    anders = {k for k in oud if oud[k] != nu.get(k)}
    assert anders == {"table:groep_rooster", "table:training"}
