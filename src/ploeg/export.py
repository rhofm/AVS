"""Csv van een ploeg om in te lezen bij atletiek.nu (teaminschrijving).

Kolommen (docs/Ploegopstelling_ontwerp.md, 'Exporteren'):
AU nummer, Naam, Geslacht, Geboortedatum, Vereniging, Categorie, Team, en dan
één kolom per onderdeel van het programma. In een onderdeelkolom staat de
prestatie die AVS gebruikt (beste volgens de prestatiebasis van de ploeg; de
serie-indeling gaat op de seizoensbeste, bepaling 17.5) of 'x' als de atleet
is opgesteld maar er geen prestatie is; leeg = niet opgesteld. Reserves staan
erin zonder onderdelen (9.3).

Privacy: de csv bevat persoonsgegevens (naam, geboortedatum, AU-nummer). Hij
wordt in het geheugen gemaakt en alleen als download gegeven; AVS slaat hem
nergens op en logt de inhoud niet.

Puntkomma als scheidingsteken en een BOM, zodat Excel hem in het Nederlands goed opent.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from atleten.prestaties import toon_waarde
from db.queries import Opslag
from ploeg.paginas import ploegpagina

KOPPEN = ["AU nummer", "Naam", "Geslacht", "Geboortedatum", "Vereniging", "Categorie", "Team"]


@dataclass(slots=True)
class Export:
    bestandsnaam: str
    inhoud: bytes
    atleten: int


def _geboortedatum(tekst: str | None) -> str:
    if not tekst:
        return ""
    if len(tekst) == 4:
        return tekst
    d = date.fromisoformat(tekst)
    return f"{d.day:02d}-{d.month:02d}-{d.year}"


def _waarde(waarde: float, eenheid: str) -> str:
    """Prestatie zonder eenheid: '12,53', '2:31,64', '4,85'."""
    return toon_waarde(waarde, eenheid).removesuffix(" m").removesuffix(" pnt")


def _bestandsnaam(naam: str, datum: date) -> str:
    ascii_ = unicodedata.normalize("NFKD", naam).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_).strip("_").lower() or "ploeg"
    return f"ploeg_{slug}_{datum.isoformat()}.csv"


def atletieknu_csv(db: Opslag, ploeg_id: int) -> Export | None:
    """De csv van een opgeslagen ploeg, of None als de ploeg niet bestaat."""
    pg = ploegpagina(db, ploeg_id)
    if pg is None:
        return None
    p, m = pg.ploeg, pg.matrix
    uit = io.StringIO()
    schrijver = csv.writer(uit, delimiter=";", lineterminator="\r\n")
    schrijver.writerow(KOPPEN + [r.kop for r in m.regels])

    # deelnemers eerst, dan reserves; binnen elke groep in de volgorde van de matrix (op naam)
    volgorde = [r for r in m.rijen if pg.rol.get(r.master_id) == "deelnemer"] + \
               [r for r in m.rijen if pg.rol.get(r.master_id) == "reserve"]
    for rij in volgorde:
        a = rij.atleet
        regel = [a.au_licentienummer or "", a.naam, a.geslacht or "", _geboortedatum(a.geboortedatum),
                 a.club or "", rij.categorie or "", p.naam]
        for r in m.regels:
            if (rij.master_id, r.sleutel) not in pg.inzet:
                regel.append("")
                continue
            c = rij.cellen[r.sleutel]
            # alleen een echte prestatie; een voorspelling of estafette wordt 'x' (ingeschreven)
            echt = c.waarde is not None and not c.voorspeld
            regel.append(_waarde(c.waarde, c.eenheid) if echt else "x")
        schrijver.writerow(regel)
    return Export(_bestandsnaam(p.naam, p.datum), ("﻿" + uit.getvalue()).encode("utf-8"), len(volgorde))
