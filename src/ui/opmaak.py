"""Jinja2-filters voor de UI: datums en kleine teksten in Nederlandse notatie.

Werkt met elke Jinja2-omgeving (Flask én FastAPI gebruiken Jinja2), dus los
van de nog te kiezen webframework:

    from ui.opmaak import registreer_filters
    registreer_filters(app.jinja_env)            # Flask
    registreer_filters(templates.env)            # FastAPI (Jinja2Templates)
"""

from __future__ import annotations

from datetime import date

MAANDEN = ("jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec")
DAGEN_KORT = ("ma", "di", "wo", "do", "vr", "za", "zo")


def datum_kort(d: date | None) -> str:
    """date(2026, 10, 24) -> 'za 24 okt'."""
    if d is None:
        return ""
    return f"{DAGEN_KORT[d.weekday()]} {d.day} {MAANDEN[d.month - 1]}"


def datum_lang(d: date | None) -> str:
    """date(2026, 10, 24) -> '24 okt 2026'."""
    if d is None:
        return ""
    return f"{d.day} {MAANDEN[d.month - 1]} {d.year}"


def over_dagen(n: int) -> str:
    """0 -> 'vandaag', 1 -> 'morgen', 9 -> 'over 9 dagen'; -1 -> 'gisteren', -3 -> '3 dagen geleden'."""
    if n == 0:
        return "vandaag"
    if n == 1:
        return "morgen"
    if n == -1:
        return "gisteren"
    if n < 0:
        return f"{-n} dagen geleden" if n > -14 else f"{-n // 7} weken geleden"
    if n < 14:
        return f"over {n} dagen"
    return f"over {n // 7} weken"


def getal(x: float | None) -> str:
    """4.25 -> '4,25'; 12.0 -> '12'. Voor testwaarden met een vrije eenheid."""
    if x is None:
        return ""
    tekst = f"{x:.2f}".rstrip("0").rstrip(".")
    return tekst.replace(".", ",")


def tekstdatum(tekst: str | None) -> str:
    """'2026-10-16 14:03:00' (zoals de database tijdstempels geeft) -> '16 okt 2026'."""
    if not tekst:
        return ""
    try:
        return datum_lang(date.fromisoformat(str(tekst)[:10]))
    except ValueError:
        return str(tekst)


def registreer_filters(env) -> None:
    env.filters["tekstdatum"] = tekstdatum
    env.filters["getal"] = getal
    env.filters["datum_kort"] = datum_kort
    env.filters["datum_lang"] = datum_lang
    env.filters["over_dagen"] = over_dagen
