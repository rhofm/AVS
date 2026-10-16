"""Notities bij een atleet: toevoegen, bekijken, zoeken, aanpassen en verwijderen.

Voor de pagina 'Notities' (knoppen '+ Notitie' en 'Alle notities' op de
landingspagina van een atleet). Een notitie is vrije tekst over wat de trainer
op een training of wedstrijd zag, met de datum waar hij over gaat.

Privacy: de tekst is alleen beschermd door de versleuteling van notities.db,
niet door het pseudoniem. Houd notities feitelijk, zet er geen diagnoses in
en noem geen andere atleten. Nooit notitietekst loggen of printen.
Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from db.queries import Opslag, OpslagFout
from models import Atleet, Notitie

MAANDNAMEN = ("januari", "februari", "maart", "april", "mei", "juni", "juli",
              "augustus", "september", "oktober", "november", "december")


@dataclass
class NotitieMaand:
    naam: str                                   # 'oktober 2026'
    notities: list[Notitie] = field(default_factory=list)


@dataclass
class NotitiesPagina:
    atleet: Atleet
    maanden: list[NotitieMaand]                 # nieuwste eerst
    aantal: int                                 # getoond (na zoeken)
    totaal: int                                 # alle notities van de atleet
    zoek: str
    vandaag: date


def notitiespagina(db: Opslag, master_id: str, *, zoek: str = "", peildatum: date | None = None) -> NotitiesPagina | None:
    """Alle notities van een atleet (nieuwste eerst, per maand), eventueel gefilterd op tekst."""
    atleet = db.atleet(master_id)
    if atleet is None:
        return None
    zoek = (zoek or "").strip()
    notities = db.notities(master_id, zoek=zoek or None)
    totaal = len(notities) if not zoek else len(db.notities(master_id))
    maanden: list[NotitieMaand] = []
    for n in notities:
        naam = f"{MAANDNAMEN[n.datum.month - 1]} {n.datum.year}"
        if not maanden or maanden[-1].naam != naam:
            maanden.append(NotitieMaand(naam))
        maanden[-1].notities.append(n)
    return NotitiesPagina(atleet, maanden, len(notities), totaal, zoek, peildatum or date.today())


def lees_datum(tekst: str | None, *, vandaag: date | None = None) -> date:
    """Datum uit het formulier ('2026-10-16'). Niet leeg en niet in de toekomst."""
    try:
        datum = date.fromisoformat((tekst or "").strip())
    except ValueError:
        raise OpslagFout("Vul een geldige datum in.") from None
    if datum > (vandaag or date.today()):
        raise OpslagFout("De datum mag niet in de toekomst liggen.")
    return datum


def _eigen(db: Opslag, master_id: str, notitie_id: int) -> Notitie:
    """De notitie, maar alleen als hij bij deze atleet hoort."""
    n = db.notitie(notitie_id)
    if n is None or n.atleet_id != master_id:
        raise OpslagFout("Deze notitie bestaat niet (meer).")
    return n


def haal_notitie(db: Opslag, master_id: str, notitie_id: int) -> Notitie | None:
    try:
        return _eigen(db, master_id, notitie_id)
    except OpslagFout:
        return None


def toevoegen(db: Opslag, master_id: str, datum: date, inhoud: str) -> Notitie:
    """Nieuwe notitie. Lege tekst geeft een fout."""
    if not (inhoud or "").strip():
        raise OpslagFout("Schrijf eerst iets in de notitie.")
    return db.notitie_opslaan(Notitie(master_id, datum, inhoud))


def bijwerken(db: Opslag, master_id: str, notitie_id: int, datum: date, inhoud: str) -> Notitie:
    """Datum en tekst van een bestaande notitie aanpassen. Geeft de notitie terug (ook als er niets veranderde)."""
    n = _eigen(db, master_id, notitie_id)
    inhoud = (inhoud or "").strip()
    if not inhoud:
        raise OpslagFout("Een notitie mag niet leeg zijn. Wil je hem weg? Gebruik dan Verwijderen.")
    if n.datum == datum and n.inhoud == inhoud:
        return n
    n.datum, n.inhoud = datum, inhoud
    return db.notitie_opslaan(n)


def verwijderen(db: Opslag, master_id: str, notitie_id: int) -> Notitie:
    """Notitie definitief verwijderen. Geeft de verwijderde notitie terug (voor de melding)."""
    n = _eigen(db, master_id, notitie_id)
    db.notitie_verwijderen(notitie_id)
    return n
