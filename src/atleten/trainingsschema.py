"""Trainingsschema van één atleet aanpassen: op welke weekdagen hij/zij traint.

Voor de pagina 'Trainingsschema' (knop 'Aanpassen' op de landingspagina van een
atleet). Het formulier stuurt de gekozen dagen mee ('dag' = 'maandag', ...);
`schema_opslaan()` slaat het volledige schema op en meldt wat er veranderde.

Ter hulp toont de pagina per dag welke groepen van de atleet dan trainen (uit
de geplande trainingen rond vandaag). Let op: het schema bepaalt wie op een
absentielijst al op 'aanwezig' staat (zie groepen/absentie.py).
Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from db.queries import Opslag, OpslagFout
from models import DAGEN, Atleet, Trainingsschema

from .landingspagina import DAG_KORT

#: Zoveel dagen voor en na vandaag kijken naar de trainingen van de groepen.
GROEPSVENSTER = 28


@dataclass
class FormDag:
    dag: str                                          # 'maandag'
    kort: str                                         # 'Ma'
    traint: bool
    groepen: list[str] = field(default_factory=list)  # groepen van de atleet die op deze weekdag trainen


@dataclass
class SchemaFormulier:
    atleet: Atleet
    dagen: list[FormDag]

    @property
    def aantal(self) -> int:
        return sum(d.traint for d in self.dagen)

    @property
    def heeft_groepsdagen(self) -> bool:
        return any(d.groepen for d in self.dagen)


def groepsdagen(db: Opslag, master_id: str, peildatum: date | None = None) -> dict[str, list[str]]:
    """Per weekdag de groepen van de atleet die dan trainen.

    Bron: de vaste trainingstijden van de groep ('Sprint 18:30'), aangevuld met de
    weekdagen van geplande trainingen rond de peildatum (voor groepen zonder
    vaste tijden of met een extra training).
    """
    vandaag = peildatum or date.today()
    van, tot = vandaag - timedelta(days=GROEPSVENSTER), vandaag + timedelta(days=GROEPSVENSTER)
    uit: dict[str, list[str]] = {d: [] for d in DAGEN}
    for g in db.groepen_van_atleet(master_id):
        dagen = set(g.trainingsdagen) | {DAGEN[t.datum.weekday()] for t in db.trainingen(g.id, van=van, tot=tot)}
        for dag in DAGEN:
            if dag in dagen:
                tijd = g.starttijd(dag)
                uit[dag].append(f"{g.naam} {tijd}" if tijd else g.naam)
    return uit


def schemaformulier(db: Opslag, master_id: str, *, peildatum: date | None = None) -> SchemaFormulier | None:
    atleet = db.atleet(master_id)
    if atleet is None:
        return None
    schema = db.trainingsschema(master_id)
    per_dag = groepsdagen(db, master_id, peildatum)
    return SchemaFormulier(atleet, [FormDag(d, DAG_KORT[d], schema.traint_op(d), per_dag[d]) for d in DAGEN])


@dataclass
class SchemaWijziging:
    erbij: list[str]                  # dagen die erbij kwamen
    eraf: list[str]                   # dagen die vervielen
    nieuw: list[str]                  # het hele nieuwe schema

    @property
    def leeg(self) -> bool:
        return not self.erbij and not self.eraf

    @property
    def tekst(self) -> str:
        """Korte melding voor na het opslaan."""
        if self.leeg:
            return "Trainingsschema niet gewijzigd."
        dagen = ", ".join(self.nieuw) if self.nieuw else "geen trainingsdagen"
        return f"Trainingsschema opgeslagen: {dagen}."


def schema_opslaan(db: Opslag, master_id: str, gekozen: Iterable[str]) -> SchemaWijziging:
    """Maak het schema van de atleet precies `gekozen` (weekdagnamen). Onbekende dagen geven een fout."""
    if db.atleet(master_id) is None:
        raise OpslagFout(f"Atleet {master_id} bestaat niet.")
    keuze = {d.strip().lower() for d in gekozen if d and d.strip()}
    onbekend = keuze - set(DAGEN)
    if onbekend:
        raise OpslagFout(f"Onbekende dag(en): {', '.join(sorted(onbekend))}.")
    oud = set(db.trainingsschema(master_id).dagen)
    nieuw = [d for d in DAGEN if d in keuze]
    wijziging = SchemaWijziging([d for d in nieuw if d not in oud], [d for d in DAGEN if d in oud - keuze], nieuw)
    if not wijziging.leeg:
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(master_id, nieuw))
    return wijziging
