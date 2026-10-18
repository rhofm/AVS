"""Trainingsschema van één atleet aanpassen: op welke weekdagen hij/zij traint.

Voor de pagina 'Trainingsschema' (knop 'Aanpassen' op de landingspagina van een
atleet). Het formulier stuurt de gekozen dagen mee ('dag' = 'maandag', ...);
`schema_opslaan()` slaat het volledige schema op en meldt wat er veranderde.

Heeft de atleet op een dag vaste groepstrainingen (één of meer groepen, of één
groep met meerdere tijden), dan kiest hij die training(en) per stuk (veld
'training-<dag>'); de dag telt dan als trainingsdag als er minstens één is
gekozen. Een deelkeuze wordt bewaard in trainingsschema.db (trainingskeuze).
Let op: schema en keuze bepalen wie op een absentielijst al op 'aanwezig'
staat (zie groepen/absentie.py en Trainingsschema.traint_mee).
Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from db.queries import Opslag, OpslagFout
from instellingen import dagvolgorde, tijd as toon_tijd
from models import DAGEN, Atleet, Trainingsschema

from .landingspagina import DAG_KORT

#: Zoveel dagen voor en na vandaag kijken naar de trainingen van de groepen.
GROEPSVENSTER = 28


@dataclass
class Optie:
    """Eén vaste groepstraining op een weekdag waaruit de atleet kan kiezen."""
    groep_id: int
    groep: str                                        # naam
    tijd: str                                         # '18:30'
    gekozen: bool

    @property
    def waarde(self) -> str:
        """Waarde in het formulier: 'groep_id|tijd' (veld 'training-<dag>')."""
        return f"{self.groep_id}|{self.tijd}"

    @property
    def tekst(self) -> str:
        return f"{self.groep} {toon_tijd(self.tijd)}"

    @property
    def tijd_tekst(self) -> str:
        """De begintijd zoals Instellingen hem wil laten zien ('18:30u' / '6:30PM')."""
        return toon_tijd(self.tijd)


@dataclass
class FormDag:
    dag: str                                          # 'maandag'
    kort: str                                         # 'Ma'
    traint: bool
    groepen: list[str] = field(default_factory=list)  # groepen zonder vaste tijd die dag (alleen ter info)
    opties: list[Optie] = field(default_factory=list) # vaste groepstrainingen om uit te kiezen

    @property
    def veld(self) -> str:
        return TRAINING_VELD + self.dag


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

    @property
    def heeft_opties(self) -> bool:
        return any(d.opties for d in self.dagen)


TRAINING_VELD = "training-"           # per dag: training-zaterdag=<groep_id>|<tijd> (meerdere mogelijk)


def groepsdagen(db: Opslag, master_id: str, peildatum: date | None = None) -> dict[str, list[str]]:
    """Per weekdag de groepen van de atleet die dan trainen zonder vaste begintijd.

    Groepen met een vaste begintijd op die dag staan niet hier maar als keuze
    (zie opties()). Hier: groepen zonder vaste tijden, met een geplande training
    op die weekdag rond de peildatum.
    """
    vandaag = peildatum or date.today()
    van, tot = vandaag - timedelta(days=GROEPSVENSTER), vandaag + timedelta(days=GROEPSVENSTER)
    uit: dict[str, list[str]] = {d: [] for d in DAGEN}
    for g in db.groepen_van_atleet(master_id):
        geplande = {DAGEN[t.datum.weekday()] for t in db.trainingen(g.id, van=van, tot=tot)}
        for dag in DAGEN:
            if dag in geplande and not g.tijden(dag):
                uit[dag].append(g.naam)
    return uit


def opties(db: Opslag, master_id: str) -> dict[str, list[tuple[int, str, str]]]:
    """Per weekdag de vaste groepstrainingen van de atleet: [(groep_id, groepsnaam, tijd)], op tijd."""
    uit: dict[str, list[tuple[int, str, str]]] = {d: [] for d in DAGEN}
    for g in db.groepen_van_atleet(master_id):
        for dag, tijd in g.momenten:
            uit[dag].append((g.id, g.naam, tijd))
    for dag in DAGEN:
        uit[dag].sort(key=lambda o: (o[2], o[1].lower()))
    return uit


def schemaformulier(db: Opslag, master_id: str, *, peildatum: date | None = None) -> SchemaFormulier | None:
    atleet = db.atleet(master_id)
    if atleet is None:
        return None
    schema = db.trainingsschema(master_id)
    per_dag = groepsdagen(db, master_id, peildatum)
    per_optie = opties(db, master_id)
    dagen = []
    for d in dagvolgorde():
        keuze = schema.keuze.get(d)
        lijst = [Optie(gid, naam, tijd, schema.traint_op(d) and (not keuze or (gid, tijd) in keuze))
                 for gid, naam, tijd in per_optie[d]]
        dagen.append(FormDag(d, DAG_KORT[d], schema.traint_op(d), per_dag[d], lijst))
    return SchemaFormulier(atleet, dagen)


@dataclass
class SchemaWijziging:
    erbij: list[str]                  # dagen die erbij kwamen
    eraf: list[str]                   # dagen die vervielen
    nieuw: list[str]                  # het hele nieuwe schema
    keuze_gewijzigd: bool = False     # andere trainingen gekozen op een dag
    gekozen: dict[str, list[str]] = field(default_factory=dict)   # voor de melding: {'zaterdag': ['Sprint 10:30']}

    @property
    def leeg(self) -> bool:
        return not self.erbij and not self.eraf and not self.keuze_gewijzigd

    @property
    def tekst(self) -> str:
        """Korte melding voor na het opslaan."""
        if self.leeg:
            return "Trainingsschema niet gewijzigd."
        if not self.nieuw:
            return "Trainingsschema opgeslagen: geen trainingsdagen."
        delen = [f"{d} ({', '.join(self.gekozen[d])})" if self.gekozen.get(d) else d for d in self.nieuw]
        return f"Trainingsschema opgeslagen: {', '.join(delen)}."


def lees_trainingen(formulier) -> dict[str, set[tuple[int, str]]]:
    """Gekozen trainingen uit het formulier: {'zaterdag': {(3, '10:30')}}. Ongeldige waarden geven een fout."""
    uit: dict[str, set[tuple[int, str]]] = {}
    lijst = (lambda k: formulier.getlist(k)) if hasattr(formulier, "getlist") else (lambda k: formulier.get(k) or [])
    for d in DAGEN:
        for waarde in lijst(TRAINING_VELD + d):
            gid, _, tijd = str(waarde).partition("|")
            if not gid.isdigit() or not tijd:
                raise OpslagFout("Ongeldige keuze van een training.")
            uit.setdefault(d, set()).add((int(gid), tijd))
    return uit


def schema_opslaan(db: Opslag, master_id: str, gekozen: Iterable[str],
                   trainingen: dict[str, set[tuple[int, str]]] | None = None) -> SchemaWijziging:
    """Maak het schema van de atleet precies `gekozen` (weekdagnamen). Onbekende dagen geven een fout.

    trainingen: de aangevinkte vaste groepstrainingen per dag ({'zaterdag': {(groep_id, '10:30')}}).
    Een dag met een aangevinkte training telt als trainingsdag. Zijn op een dag
    niet alle trainingen gekozen, dan wordt de keuze bewaard (alleen die trainingen
    komen vooraf op 'aanwezig'); alles gekozen = geen keuze nodig.
    None = keuzes niet aanpassen.
    """
    if db.atleet(master_id) is None:
        raise OpslagFout(f"Atleet {master_id} bestaat niet.")
    keuze = {d.strip().lower() for d in gekozen if d and d.strip()}
    onbekend = keuze - set(DAGEN)
    if onbekend:
        raise OpslagFout(f"Onbekende dag(en): {', '.join(sorted(onbekend))}.")
    schema = db.trainingsschema(master_id)
    oud = set(schema.dagen)
    beschikbaar = opties(db, master_id)
    namen = {(gid, tijd): f"{naam} {toon_tijd(tijd)}" for d in DAGEN for gid, naam, tijd in beschikbaar[d]}

    nieuwe_keuze = dict(schema.keuze)
    gekozen_tekst: dict[str, list[str]] = {}
    if trainingen is not None:
        nieuwe_keuze = {}
        for d in DAGEN:
            mogelijk = {(gid, tijd) for gid, _, tijd in beschikbaar[d]}
            aan = set(trainingen.get(d, set()))
            if aan - mogelijk:
                raise OpslagFout(f"Op {d} is een training gekozen die de groepen van de atleet niet hebben.")
            if aan:
                keuze.add(d)
            elif mogelijk:
                keuze.discard(d)          # alle trainingen van die dag uitgevinkt = traint die dag niet
            if aan and aan != mogelijk:
                nieuwe_keuze[d] = aan
            if aan and len(mogelijk) > 1:
                gekozen_tekst[d] = [namen[o] for o in sorted(aan, key=lambda o: (o[1], namen[o]))]

    nieuw = [d for d in DAGEN if d in keuze]
    nieuwe_keuze = {d: v for d, v in nieuwe_keuze.items() if d in keuze}
    oude_keuze = {d: v for d, v in schema.keuze.items() if d in oud}
    wijziging = SchemaWijziging([d for d in nieuw if d not in oud], [d for d in DAGEN if d in oud - keuze], nieuw,
                                nieuwe_keuze != oude_keuze, gekozen_tekst)
    if wijziging.erbij or wijziging.eraf:
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(master_id, nieuw))
    if trainingen is not None and nieuwe_keuze != schema.keuze:
        db.trainingskeuze_opslaan(master_id, nieuwe_keuze)
    return wijziging
