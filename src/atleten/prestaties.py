"""Prestaties van één atleet: handmatig toevoegen, PR-historie, seizoensbesten,
en waarden lezen/tonen in de notatie die trainers gewend zijn."""

from __future__ import annotations

import re
from datetime import date

from db.queries import Opslag, OpslagFout
from models import Onderdeel, Prestatie

MAX_WIND = 2.0  # m/s; bij meer rugwind telt een prestatie niet voor records


# ============================================================
# Waarden lezen en tonen
# ============================================================
def lees_waarde(tekst: str, eenheid: str) -> float:
    """Tekst uit een invoerveld naar een getal.

    Tijden: '12,93' / '12.93' -> 12.93 s, '1:58,21' -> 118.21 s, '1:02:03' -> 3723 s.
    Afstand/hoogte: '4,80' of '4.80 m' -> 4.8. Punten: '4500' -> 4500.0.
    """
    schoon = tekst.strip().lower().replace(",", ".")
    schoon = re.sub(r"\s*(m|s|sec|pnt|punten)$", "", schoon)
    try:
        if eenheid == "tijd" and ":" in schoon:
            delen = [float(d) for d in schoon.split(":")]
            totaal = 0.0
            for d in delen:
                totaal = totaal * 60 + d
            return round(totaal, 2)
        return float(schoon)
    except ValueError:
        raise ValueError(f"'{tekst}' is geen geldige {eenheid}.") from None


def toon_waarde(waarde: float, eenheid: str) -> str:
    """Getal naar Nederlandse notatie: 12,93 / 1:58,21 / 4,80 m / 4500 pnt."""
    if eenheid == "tijd":
        if waarde >= 60:
            minuten, seconden = divmod(round(waarde, 2), 60)
            uren, minuten = divmod(int(minuten), 60)
            sec = f"{seconden:05.2f}".replace(".", ",")
            return f"{uren}:{minuten:02d}:{sec}" if uren else f"{minuten}:{sec}"
        return f"{waarde:.2f}".replace(".", ",")
    if eenheid in ("afstand", "hoogte"):
        return f"{waarde:.2f}".replace(".", ",") + " m"
    return f"{waarde:.0f} pnt"


def windlegaal(p: Prestatie) -> bool:
    return p.wind is None or p.wind <= MAX_WIND


# ============================================================
# Toevoegen
# ============================================================
def handmatig_toevoegen(db: Opslag, master_id: str, onderdeel: str | int, datum: date,
                        waarde: float | str, *, wind: float | None = None,
                        wedstrijd_id: int | None = None, ronde: str = "") -> tuple[Prestatie, bool]:
    """Voeg een prestatie toe die niet uit een import komt.

    `waarde` mag tekst zijn ('1:58,21'). Geeft (prestatie, is_nieuw_pr).
    """
    o = db.onderdeel(onderdeel)
    if o is None:
        raise OpslagFout(f"Onbekend onderdeel {onderdeel!r}.")
    if db.atleet(master_id) is None:
        raise OpslagFout("Onbekende atleet.")
    if isinstance(waarde, str):
        waarde = lees_waarde(waarde, o.eenheid)

    # Niet db.prs(): de view `pr` telt ook prestaties met te veel rugwind mee.
    historie = pr_historie(db, master_id, o.id, alleen_windlegaal=True)
    oud_pr = historie[-1].waarde if historie else None
    p = Prestatie(o.naam, datum, waarde, atleet_id=master_id, onderdeel_id=o.id,
                  wedstrijd_id=wedstrijd_id, wind=wind, ronde=ronde, bron="handmatig")
    db.prestatie_opslaan(p)
    nieuw_pr = windlegaal(p) and (oud_pr is None or o.is_beter(waarde, oud_pr))
    return p, nieuw_pr


# ============================================================
# Overzichten
# ============================================================
def pr_historie(db: Opslag, master_id: str, onderdeel_id: int,
                alleen_windlegaal: bool = True) -> list[Prestatie]:
    """Elke keer dat het PR verbeterd werd, oudste eerst. Laat de ontwikkeling zien."""
    o = db.onderdeel(onderdeel_id)
    if o is None:
        return []
    prestaties = sorted(db.prestaties(master_id, onderdeel_id), key=lambda p: p.datum)
    historie: list[Prestatie] = []
    for p in prestaties:
        if alleen_windlegaal and not windlegaal(p):
            continue
        if not historie or o.is_beter(p.waarde, historie[-1].waarde):
            historie.append(p)
    return historie


def beste_in_periode(db: Opslag, master_id: str, van: date, tot: date,
                     alleen_windlegaal: bool = True) -> dict[int, Prestatie]:
    """Beste prestatie per onderdeel binnen een periode. {onderdeel_id: prestatie}"""
    onderdelen: dict[int, Onderdeel] = {o.id: o for o in db.onderdelen()}
    beste: dict[int, Prestatie] = {}
    for p in db.prestaties(master_id):
        if not (van <= p.datum <= tot) or (alleen_windlegaal and not windlegaal(p)):
            continue
        huidig = beste.get(p.onderdeel_id)
        if huidig is None or onderdelen[p.onderdeel_id].is_beter(p.waarde, huidig.waarde):
            beste[p.onderdeel_id] = p
    return beste


def seizoensbesten(db: Opslag, master_id: str, jaar: int) -> dict[int, Prestatie]:
    """Beste prestatie per onderdeel in een kalenderjaar (baanseizoen)."""
    return beste_in_periode(db, master_id, date(jaar, 1, 1), date(jaar, 12, 31))
