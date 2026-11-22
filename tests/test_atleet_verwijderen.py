"""Een atleet verwijderen (AVG): niets mag achterblijven, ook niet in een tabel die later bijkomt,
en een verwijdering die halverwege mislukt moet met nog een keer verwijderen af te maken zijn.

Zie Opslag.atleet_verwijderen en ATLEET_TABELLEN. Alleen nepgegevens en een vaste testsleutel.
"""

from datetime import date

import pytest
import sqlcipher3

from db.init_db import DATABASES, GEPSEUDONIMISEERD
from db.queries import ATLEET_TABELLEN, OnvolledigVerwijderd
from models import Absentie, Groep, Notitie, Prestatie, Test, Testresultaat, Trainingsschema, Training
from voorbeeld_atleet import basis_atleten, client
from hulp import opslag, tekst

#: Kolommen die een persoon aanwijzen en daarom alleen in personen.db mogen staan.
PERSOONSKOLOMMEN = {"master_id", "atleet_id", "voornaam", "achternaam", "geboortedatum",
                    "atletieknu_id", "au_licentienummer"}


def _tabellen(conn) -> dict[str, set[str]]:
    """{tabel: kolommen} van alle echte tabellen (geen views) in een database."""
    namen = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")} for t in namen}


# ---------------- vangnet: elke tabel met een atleet hoort erbij ----------------
def test_atleet_tabellen_kloppen_met_de_schemas():
    """Komt er (via een migratie) een tabel met atleet_ref bij, dan moet hij in ATLEET_TABELLEN,
    anders blijft er na een AVG-verzoek iets van de atleet achter."""
    assert set(ATLEET_TABELLEN) == set(GEPSEUDONIMISEERD)
    with opslag() as db:
        for database in GEPSEUDONIMISEERD:
            met_ref = {t for t, kolommen in _tabellen(db._db(database)).items() if "atleet_ref" in kolommen}
            assert met_ref == set(ATLEET_TABELLEN[database]), (
                f"{database}.db: tabellen met atleet_ref {sorted(met_ref)}, "
                f"maar ATLEET_TABELLEN noemt {sorted(ATLEET_TABELLEN[database])}")


def test_persoonsgegevens_alleen_in_personen():
    with opslag() as db:
        for database in DATABASES:
            if database == "personen":
                continue
            for tabel, kolommen in _tabellen(db._db(database)).items():
                assert not kolommen & PERSOONSKOLOMMEN, f"{database}.{tabel}: {kolommen & PERSOONSKOLOMMEN}"


def test_personen_alles_gaat_mee_met_de_atleet():
    """In personen.db moet elke tabel met een atleet_id meegaan als de atleet weg is (CASCADE)."""
    with opslag() as db:
        for tabel, kolommen in _tabellen(db.personen).items():
            if "atleet_id" not in kolommen:
                continue
            fks = db.personen.execute(f"PRAGMA foreign_key_list({tabel})").fetchall()
            assert any(fk["from"] == "atleet_id" and fk["on_delete"] == "CASCADE" for fk in fks), tabel


# ---------------- halverwege mislukt: nog een keer maakt het af ----------------
class _Kapot:
    """Verbinding waarop elke DELETE mislukt, zoals bij een volle schijf; de rest werkt gewoon."""

    def __init__(self, echt):
        self._echt = echt

    def execute(self, sql, *args):
        if sql.lstrip().upper().startswith("DELETE"):
            raise sqlcipher3.OperationalError("disk I/O error")
        return self._echt.execute(sql, *args)

    def __enter__(self):
        return self._echt.__enter__()

    def __exit__(self, *args):
        return self._echt.__exit__(*args)

    def __getattr__(self, naam):
        return getattr(self._echt, naam)


def _vul(db):
    anna, tim, *_ = basis_atleten(db)
    db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 12.9, wind=0.5).gekoppeld(anna.master_id))
    t = db.test_opslaan(Test("30m vliegend", "s", True))
    db.testresultaat_opslaan(Testresultaat(anna.master_id, t.id, date(2026, 10, 1), 3.9))
    g = db.groep_opslaan(Groep("C", leden=[anna.master_id, tim.master_id]))
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["dinsdag"]))
    tr = db.training_opslaan(Training(g.id, date(2026, 10, 13)))
    db.absenties_opslaan([Absentie(tr.id, anna.master_id, "aanwezig")])
    db.notitie_opslaan(Notitie(anna.master_id, date(2026, 10, 13), "Notitie over Anna"))
    return anna, tim


@pytest.mark.parametrize("kapot", [*GEPSEUDONIMISEERD, "personen"])
def test_halverwege_mislukt_en_opnieuw_afgemaakt(kapot):
    with opslag() as db:
        anna, tim = _vul(db)
        echt = db._db(kapot)
        attribuut = "personen" if kapot == "personen" else f"{kapot}_db"
        setattr(db, attribuut, _Kapot(echt))
        with pytest.raises(OnvolledigVerwijderd) as fout:
            db.atleet_verwijderen(anna.master_id)
        setattr(db, attribuut, echt)

        assert fout.value.database == kapot and f"{kapot}.db" in str(fout.value)
        assert db.atleet(anna.master_id) is not None          # staat er nog: opnieuw verwijderen kan

        db.atleet_verwijderen(anna.master_id)                  # tweede keer: af
        assert db.atleet(anna.master_id) is None
        for database, tabellen in ATLEET_TABELLEN.items():
            ref = db._ref(anna.master_id, database)
            for tabel in tabellen:
                n = db._db(database).execute(f"SELECT count(*) FROM {tabel} WHERE atleet_ref = ?", (ref,)).fetchone()[0]
                assert n == 0, f"{database}.{tabel}"
        assert db.atleet(tim.master_id) is not None and len(db.notities()) == 0   # Tim blijft


def test_pagina_meldt_halverwege_mislukt(monkeypatch):
    from db.queries import Opslag

    def mislukt(self, master_id):
        raise OnvolledigVerwijderd("testen", sqlcipher3.OperationalError("disk I/O error"))

    with client() as (c, mid, _tmp):
        monkeypatch.setattr(Opslag, "atleet_verwijderen", mislukt)
        r = c.post(f"/atleet/{mid}/verwijderen", data={"bevestiging": "Anna Voorbeeld"})
        assert r.status_code == 500
        assert "niet helemaal gelukt" in tekst(r) and "nog een keer op Verwijderen" in tekst(r)
        monkeypatch.undo()
        r = c.post(f"/atleet/{mid}/verwijderen", data={"bevestiging": "Anna Voorbeeld"}, follow_redirects=True)
        assert "Anna Voorbeeld en alle gegevens zijn verwijderd." in tekst(r)
