"""Absentie-tool per training/groep.

Werkwijze voor de trainer:
    1. lijst = absentielijst(db, training_id)   # vooraf ingevuld
    2. de trainer past alleen de uitzonderingen aan (afgemeld, afwezig, blessure)
    3. opslaan(db, lijst)                       # elke status wordt expliciet bewaard

Vooraf invullen: leden van de groep die volgens hun trainingsschema deze
training doen, staan op 'aanwezig'. Op een dag met meer trainingen telt de
gekozen training (`Trainingsschema.traint_mee`); wie die dag een andere
training koos, staat er wel op (zie het invulformulier) maar niet vooraf ingevuld. Al opgeslagen statuses gaan altijd voor.
Leden die die dag niet ingeroosterd staan, komen alleen op de lijst als
alle_leden=True (bijv. voor een extra training).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from db.queries import Opslag, OpslagFout
from models import ABSENTIE_STATUSSEN, Absentie

__all__ = ["Absentie", "absentielijst", "zet_status", "opslaan", "overzicht"]


def absentielijst(db: Opslag, training_id: int, alle_leden: bool = False) -> list[Absentie]:
    """De lijst voor één training: opgeslagen statuses, aangevuld met 'aanwezig' voor wie ingeroosterd staat.

    Volgorde: zoals de groep (op achternaam). Niets wordt opgeslagen.
    """
    training = db.training(training_id)
    if training is None:
        raise OpslagFout(f"Training {training_id} bestaat niet.")
    groep = db.groep(training.groep_id)
    leden = groep.leden if groep else []

    opgeslagen = {a.atleet_id: a for a in db.absenties(training_id)}
    if alle_leden:
        ingeroosterd = set(leden)
    else:
        ingeroosterd = {m for m in leden if db.trainingsschema(m).traint_mee(training, groep)}

    lijst = []
    for m in leden:
        if m in opgeslagen:
            lijst.append(opgeslagen.pop(m))
        elif m in ingeroosterd:
            lijst.append(Absentie(training_id, m, "aanwezig"))
    # Opgeslagen statuses van atleten die (inmiddels) niet meer in de groep zitten.
    lijst.extend(opgeslagen.values())
    return lijst


def zet_status(lijst: list[Absentie], master_id: str, status: str, reden: str | None = None) -> list[Absentie]:
    """Pas één atleet aan in een lijst uit absentielijst(); voegt hem toe als hij er nog niet op stond."""
    for i, a in enumerate(lijst):
        if a.atleet_id == master_id:
            lijst[i] = replace(a, status=status, reden=reden)
            return lijst
    training_id = lijst[0].training_id if lijst else None
    if training_id is None:
        raise ValueError("Lege lijst: gebruik db.absentie_opslaan() met een training_id.")
    lijst.append(Absentie(training_id, master_id, status, reden))
    return lijst


def opslaan(db: Opslag, lijst: list[Absentie]) -> None:
    """De hele lijst in één keer opslaan."""
    db.absenties_opslaan(lijst)


def overzicht(db: Opslag, master_id: str, groep_id: int | None = None) -> dict[str, float | int]:
    """Aantallen per status en het aanwezigheidspercentage van één atleet.

    {'aanwezig': 18, 'afgemeld': 2, 'afwezig': 1, 'blessure': 3, 'totaal': 24, 'percentage_aanwezig': 75.0}
    """
    telling = Counter(a.status for a in db.absenties_van_atleet(master_id, groep_id))
    totaal = sum(telling.values())
    uit: dict[str, float | int] = {s: telling.get(s, 0) for s in ABSENTIE_STATUSSEN}
    uit["totaal"] = totaal
    uit["percentage_aanwezig"] = round(100 * telling["aanwezig"] / totaal, 1) if totaal else 0.0
    return uit
