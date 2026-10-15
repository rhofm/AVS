"""Testresultaten van één atleet: vastleggen en het verloop over tijd."""

from __future__ import annotations

from datetime import date

from db.queries import Opslag, OpslagFout
from models import Test, Testresultaat


def _test(db: Opslag, test: str | int) -> Test:
    for t in db.testen():
        if t.id == test or t.naam == test:
            return t
    raise OpslagFout(f"Onbekende test {test!r}.")


def resultaat_toevoegen(db: Opslag, master_id: str, test: str | int, datum: date,
                        waarde: float, notities: str | None = None) -> Testresultaat:
    """Leg een testresultaat vast. `test` is de naam of het id van een bestaande test."""
    t = _test(db, test)
    if db.atleet(master_id) is None:
        raise OpslagFout("Onbekende atleet.")
    return db.testresultaat_opslaan(Testresultaat(master_id, t.id, datum, waarde, notities))


def verloop(db: Opslag, master_id: str, test: str | int) -> list[Testresultaat]:
    """Alle resultaten op één test, oudste eerst (voor een grafiek)."""
    return db.testresultaten(master_id, _test(db, test).id)


def beste(db: Opslag, master_id: str, test: str | int) -> Testresultaat | None:
    t = _test(db, test)
    resultaten = db.testresultaten(master_id, t.id)
    if not resultaten:
        return None
    return (min if t.lager_is_beter else max)(resultaten, key=lambda r: r.waarde)


def laatste_per_test(db: Opslag, master_id: str) -> dict[int, Testresultaat]:
    """Het meest recente resultaat per test. {test_id: resultaat}"""
    laatste: dict[int, Testresultaat] = {}
    for r in db.testresultaten(master_id):  # oudste eerst, dus later overschrijft
        laatste[r.test_id] = r
    return laatste


def vooruitgang(db: Opslag, master_id: str, test: str | int) -> float | None:
    """Verschil tussen eerste en laatste resultaat. Positief = beter geworden
    (ook bij tests waar lager beter is). None bij minder dan twee resultaten."""
    t = _test(db, test)
    resultaten = db.testresultaten(master_id, t.id)
    if len(resultaten) < 2:
        return None
    verschil = resultaten[-1].waarde - resultaten[0].waarde
    return round(-verschil if t.lager_is_beter else verschil, 4)
