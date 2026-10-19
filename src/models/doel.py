"""Doelen: wat een groep of atleet wil bereiken, meestal bij een bepaalde wedstrijd.

Hoort bij prestaties.db (tabellen doel en doel_regel; migratie prestaties/004).
Atleten heten hier, zoals overal in models/, met hun master_id; het pseudoniem
blijft binnen db/.

    d = Doel("Competitiefinale", groep_id=3, wedstrijd_id=12, regels=[
        DoelRegel("prestatie", atleet_id=anna, onderdeel_id=1, streefwaarde=12.80),
        DoelRegel("vrij", omschrijving="Ploeg haalt 18 000 punten"),        # hele groep
    ])

Of een regel behaald is, wordt uitgerekend (groepen/doelen.py) en niet
opgeslagen; alleen een beoordeling met de hand staat in de database.
Vrije tekst (titel, beschrijving, omschrijving, evaluatie): feitelijk houden,
geen namen van andere atleten, geen diagnoses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

DOELSOORTEN: dict[str, str] = {
    "prestatie": "Prestatie",          # onderdeel + streefwaarde
    "leerdoel": "Leerdoel",            # leerdoel + score 1-5
    "vrij": "Vrij doel",               # alleen een omschrijving
}
BEOORDELINGEN: dict[str, str] = {"behaald": "Behaald", "deels": "Deels behaald", "niet": "Niet behaald"}

#: Status van een regel (uitgerekend): code -> tekst.
STATUSSEN: dict[str, str] = {
    "behaald": "Behaald",
    "deels": "Deels behaald",
    "niet": "Niet behaald",
    "open": "Open",
    "te_beoordelen": "Te beoordelen",
}
MAX_TITEL = 120
MAX_TEKST = 4000


def _tekst(waarde, maximaal: int = MAX_TEKST) -> str | None:
    if waarde is None:
        return None
    tekst = str(waarde).replace("\r\n", "\n").strip()
    if len(tekst) > maximaal:
        raise ValueError(f"Tekst is te lang (maximaal {maximaal} tekens).")
    return tekst or None


@dataclass(slots=True)
class DoelRegel:
    """Wat precies, en voor wie. atleet_id None = de hele groep."""
    soort: str                         # een van DOELSOORTEN
    atleet_id: str | None = None       # master_id
    onderdeel_id: int | None = None    # bij 'prestatie'
    leerdoel_id: str | None = None     # bij 'leerdoel', bijv. 'HRD-U14-02'
    streefwaarde: float | None = None  # seconden/meters/punten, of score 1-5 bij een leerdoel
    omschrijving: str | None = None
    beoordeling: str | None = None     # None = automatisch / nog open; anders een van BEOORDELINGEN
    doel_id: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.soort not in DOELSOORTEN:
            raise ValueError(f"Onbekende soort doel {self.soort!r}.")
        self.omschrijving = _tekst(self.omschrijving, 400)
        self.leerdoel_id = _tekst(self.leerdoel_id, 20)
        if self.beoordeling is not None and self.beoordeling not in BEOORDELINGEN:
            raise ValueError(f"Onbekende beoordeling {self.beoordeling!r}.")
        if self.streefwaarde is not None:
            self.streefwaarde = float(self.streefwaarde)
        if self.soort == "prestatie" and (self.onderdeel_id is None or self.streefwaarde is None):
            raise ValueError("Een prestatiedoel heeft een onderdeel en een streefwaarde.")
        if self.soort == "leerdoel":
            if self.leerdoel_id is None or self.streefwaarde is None:
                raise ValueError("Een leerdoel heeft een leerdoel en een score.")
            if not (1 <= self.streefwaarde <= 5 and self.streefwaarde == int(self.streefwaarde)):
                raise ValueError("De score van een leerdoel is 1 tot en met 5.")
        if self.soort == "vrij" and not self.omschrijving:
            raise ValueError("Een vrij doel heeft een omschrijving.")
        if self.soort != "prestatie":
            self.onderdeel_id = None
        if self.soort != "leerdoel":
            self.leerdoel_id = None
        if self.soort == "vrij":
            self.streefwaarde = None

    @property
    def voor_groep(self) -> bool:
        return self.atleet_id is None


@dataclass(slots=True)
class Doel:
    titel: str
    groep_id: int | None = None        # None = persoonlijk doel (alle regels voor één atleet)
    wedstrijd_id: int | None = None
    startdatum: date | None = None     # resultaten tellen vanaf hier; None = vandaag (bij opslaan)
    datum: date | None = None          # streefdatum; None = de datum van de wedstrijd
    beschrijving: str | None = None
    evaluatie: str | None = None
    regels: list[DoelRegel] = field(default_factory=list)
    id: int | None = None
    aangemaakt_op: str | None = None

    def __post_init__(self) -> None:
        self.titel = " ".join(str(self.titel or "").split())
        if not self.titel:
            raise ValueError("Geef het doel een titel.")
        if len(self.titel) > MAX_TITEL:
            raise ValueError(f"De titel is te lang (maximaal {MAX_TITEL} tekens).")
        self.beschrijving = _tekst(self.beschrijving)
        self.evaluatie = _tekst(self.evaluatie)
        if self.startdatum and self.datum and self.datum < self.startdatum:
            raise ValueError("De streefdatum ligt voor de startdatum.")

    @property
    def persoonlijk(self) -> bool:
        return self.groep_id is None
