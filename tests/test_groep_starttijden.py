"""Tests voor de trainingstijden van groepen (tabel groep_trainingstijden in personen.db).

Eén rij per groep: groep_id + per weekdag een begintijd 'HH:MM' of leeg (= geen
training). Leden staan in groep_lid (lang formaat); een atleet kan in meerdere
groepen zitten. Ook: de controle op dubbele migratienummers.

Alleen nepgegevens en een vaste testsleutel.
"""

import tempfile
from datetime import date
from pathlib import Path

from atleten import trainingsschema as schema_pagina
from db import init_db as init_module
from db.queries import OpslagFout
from groepen import groep as groepsbeheer
from models import Atleet, Trainingsschema, normaliseer_tijd
from hulp import opslag, verwacht as _verwacht


def _basis(db):
    anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
    bas = db.atleet_opslaan(Atleet("Bas", "Bakker"))
    sprint = groepsbeheer.groep_aanmaken(db, "Sprintgroep", "2026-2027", [], {"dinsdag": "18:30", "donderdag": "18:30"})
    junioren = groepsbeheer.groep_aanmaken(db, "Junioren C", "2026-2027", [], {"donderdag": "19:30", "zaterdag": "9:00"})
    return anna, bas, sprint, junioren


def test_tijden_normaliseren():
    assert normaliseer_tijd("9:00") == "09:00" and normaliseer_tijd(" 18.30 ") == "18:30"
    assert normaliseer_tijd("") is None and normaliseer_tijd(None) is None
    for fout in ("24:00", "18:60", "half zeven", "1830"):
        _verwacht(ValueError, lambda f=fout: normaliseer_tijd(f))


def test_tabel_een_rij_per_groep():
    with opslag() as db:
        anna, bas, sprint, junioren = _basis(db)
        assert db.groep(sprint.id).trainingsdagen == {"dinsdag": "18:30", "donderdag": "18:30"}
        assert db.groep(junioren.id).starttijd("Zaterdag") == "09:00"
        r = db.personen.execute("SELECT * FROM groep_trainingstijden WHERE groep_id = ?", (junioren.id,)).fetchone()
        assert [r[d] for d in ("maandag", "donderdag", "zaterdag")] == [None, "19:30", "09:00"]
        assert db.personen.execute("SELECT count(*) FROM groep_trainingstijden").fetchone()[0] == 2

        # Opslaan direct via Opslag: dag zonder tijd, onbekende dag of tijd -> fout, niets gewijzigd.
        for fout in ({"dinsdag": None}, {"feestdag": "18:00"}, {"dinsdag": "25:00"}):
            _verwacht(OpslagFout, lambda f=fout: db.groep_trainingsdagen_opslaan(sprint.id, f))
        _verwacht(OpslagFout, lambda: db.groep_trainingsdagen_opslaan(999, {"dinsdag": "18:00"}))
        assert db.groep(sprint.id).trainingsdagen == {"dinsdag": "18:30", "donderdag": "18:30"}

        # Leden opslaan laat de tijden staan; {} haalt de rij weg.
        db.groep_opslaan(db.groep(sprint.id))
        assert db.groep(sprint.id).trainingsdagen == {"dinsdag": "18:30", "donderdag": "18:30"}
        db.groep_trainingsdagen_opslaan(sprint.id, {})
        assert db.groep(sprint.id).trainingsdagen == {}
        assert db.personen.execute("SELECT count(*) FROM groep_trainingstijden").fetchone()[0] == 1


def test_meerdere_groepen_en_trainingsschema():
    with opslag() as db:
        anna, bas, sprint, junioren = _basis(db)
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["maandag"]))   # eigen dag blijft
        w = groepsbeheer.leden_opslaan(db, sprint.id, [anna.master_id])
        assert [a.naam for a in w.schema_aangevuld] == ["Anna Aalbers"]
        assert db.trainingsschema(anna.master_id).dagen == ["maandag", "dinsdag", "donderdag"]

        groepsbeheer.leden_opslaan(db, junioren.id, [anna.master_id, bas.master_id])
        assert sorted(g.naam for g in db.groepen_van_atleet(anna.master_id)) == ["Junioren C", "Sprintgroep"]
        assert db.personen.execute("SELECT count(*) FROM groep_lid").fetchone()[0] == 3     # lang: rij per lid
        assert db.trainingsschema(anna.master_id).dagen == ["maandag", "dinsdag", "donderdag", "zaterdag"]
        assert db.trainingsschema(bas.master_id).dagen == ["donderdag", "zaterdag"]

        # Groep krijgt een dag erbij: alle leden krijgen die dag; er gaat niets uit het schema.
        w = groepsbeheer.leden_opslaan(db, junioren.id, [anna.master_id, bas.master_id],
                                       {"woensdag": "17:00", "zaterdag": "09:00"})
        assert w.dagen == {"woensdag": "17:00", "zaterdag": "09:00"} and len(w.schema_aangevuld) == 2
        assert db.trainingsschema(bas.master_id).dagen == ["woensdag", "donderdag", "zaterdag"]   # donderdag blijft

        # Uit de groep: schema blijft staan.
        groepsbeheer.leden_opslaan(db, junioren.id, [bas.master_id])
        assert "zaterdag" in db.trainingsschema(anna.master_id).dagen


def test_rooster_en_schemapagina():
    with opslag() as db:
        anna, _, sprint, junioren = _basis(db)
        groepsbeheer.leden_opslaan(db, sprint.id, [anna.master_id])
        groepsbeheer.leden_opslaan(db, junioren.id, [anna.master_id])
        assert [(r.dag, r.tijd, r.groep) for r in groepsbeheer.rooster(db, anna.master_id)] == [
            ("dinsdag", "18:30", "Sprintgroep"),
            ("donderdag", "18:30", "Sprintgroep"),
            ("donderdag", "19:30", "Junioren C"),
            ("zaterdag", "09:00", "Junioren C"),
        ]
        # Groepen met een vaste tijd zijn op de schemapagina een keuze (op tijd), geen losse tekst meer.
        opties = schema_pagina.opties(db, anna.master_id)
        assert opties["donderdag"] == [(sprint.id, "Sprintgroep", "18:30"), (junioren.id, "Junioren C", "19:30")]
        assert opties["maandag"] == []
        per_dag = schema_pagina.groepsdagen(db, anna.master_id, date(2026, 10, 16))
        assert per_dag["donderdag"] == [] and per_dag["maandag"] == []


def test_dubbele_migratienummers_worden_geweigerd():
    with tempfile.TemporaryDirectory() as tmp:
        map_dir = Path(tmp) / "personen"
        map_dir.mkdir()
        (map_dir / "003_a.sql").write_text("SELECT 1;")
        (map_dir / "003_b.sql").write_text("SELECT 1;")
        oud = init_module.MIGRATIONS_DIR
        init_module.MIGRATIONS_DIR = Path(tmp)
        try:
            _verwacht(RuntimeError, lambda: init_module._migraties("personen"))
        finally:
            init_module.MIGRATIONS_DIR = oud
