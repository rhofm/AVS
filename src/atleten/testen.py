"""Testresultaten van één atleet: het laatste resultaat per test. Vastleggen gaat via testen.resultaten."""

from __future__ import annotations

from db.queries import Opslag
from models import Testresultaat


def laatste_per_test(db: Opslag, master_id: str) -> dict[int, Testresultaat]:
    """Het meest recente resultaat per test. {test_id: resultaat}"""
    laatste: dict[int, Testresultaat] = {}
    for r in db.testresultaten(master_id):  # oudste eerst, dus later overschrijft
        laatste[r.test_id] = r
    return laatste

