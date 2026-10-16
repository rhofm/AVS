"""Atleten combineren tot groepen: leden, trainingstijden per weekdag en het weekrooster.

Pagina's:
  * 'Nieuwe groep' (knop op de pagina Groepen): naam, seizoen en de atleten in
    één keer kiezen; `groep_aanmaken()` slaat op.
  * 'Trainingsdagen wijzigen' (knop 'Wijzigen' bij de trainingsdagen op de
    landingspagina van een groep): alleen de dagen en begintijden;
    `trainingsdagen_opslaan()` slaat op.
  * 'Wijzigen' (knop bij de atletenlijst op de landingspagina van een groep):
    de trainingsdagen met begintijden en de leden. Het formulier stuurt de volledige nieuwe ledenlijst mee (één
    vinkje per atleet); `leden_opslaan()` slaat die op en meldt wie erbij kwam en
    wie eraf ging.

Een atleet uit de groep halen verwijdert niets anders: aanwezigheid, PR's en
leerdoelscores blijven bij de atleet bewaard. Geen SQL: alles via `Opslag`.

Trainingstijden en trainingsschema
---------------------------------
Een groep heeft per weekdag een begintijd of niets (`Groep.trainingsdagen`,
tabel groep_trainingstijden). Een
atleet kan in meerdere groepen zitten. Komt een atleet in een groep, of krijgt
een groep een extra trainingsdag, dan worden die dagen AANGEVULD in het
trainingsschema van de atleet (dat bepaalt de absentielijst). Er wordt nooit
een dag uit een schema gehaald: of iemand op een dag niet meer komt, kan per
atleet verschillen. Dat pas je aan op de pagina 'Trainingsschema'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Iterable, Mapping

from atleten.landingspagina import DAG_KORT, categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
from models import DAGEN, Atleet, Groep, Trainingsschema

from .landingspagina import trainingsdagen as afgeleide_trainingsdagen

DAG_VELD = "dag-"                     # vinkje per weekdag: dag-dinsdag=1
TIJD_VELD = "tijd-"                   # begintijd per weekdag: tijd-dinsdag=18:30
_TIJD = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class Kandidaat:
    atleet: Atleet
    categorie: str | None
    andere_groepen: list[str] = field(default_factory=list)

    @property
    def categorie_code(self) -> str | None:
        return categorie_code(self.categorie, self.atleet.geslacht)


@dataclass
class LedenFormulier:
    groep: Groep                      # bij een nieuwe groep: nog niet opgeslagen (id None)
    leden: list[Kandidaat]            # nu in de groep (ook niet-actieve), op achternaam
    overigen: list[Kandidaat]         # actieve atleten die nog niet in de groep zitten, op achternaam
    gekozen: set[str] = field(default_factory=set)   # aangevinkte atleten als vinkjes_uit_keuze
    vinkjes_uit_keuze: bool = False   # True: vinkjes volgen `gekozen` (nieuwe groep, of opnieuw na een fout)
    afgeleide_dagen: str = ""         # zonder vaste dagen: wat de app nu afleidt ('Di, Do'), als hint

    @property
    def nieuw(self) -> bool:
        return self.groep.id is None

    @property
    def dagen(self) -> list[tuple[str, str, bool, str]]:
        """Voor de dagkeuze: (dag, kort, aangevinkt, begintijd) van maandag t/m zondag."""
        td = self.groep.trainingsdagen
        return [(d, DAG_KORT[d], d in td, td.get(d) or "") for d in DAGEN]


MAX_NAAM = 80


def huidig_seizoen(peildatum: date) -> str:
    """Seizoen van september t/m augustus: oktober 2026 -> '2026-2027', maart 2027 -> '2026-2027'."""
    begin = peildatum.year if peildatum.month >= 9 else peildatum.year - 1
    return f"{begin}-{begin + 1}"


def lees_trainingsdagen(formulier: Mapping[str, str], *, streng: bool = True) -> dict[str, str | None]:
    """Trainingsdagen uit het formulier: {'dinsdag': '18:30', 'donderdag': None}.

    Een dag telt mee als het vinkje aan staat óf er een begintijd is ingevuld.
    Tijden als '18:30' of '9:00' (wordt '09:00'). Elke trainingsdag heeft een
    begintijd nodig: een vinkje zonder tijd of een ongeldige tijd geeft een fout.
    Met streng=False wordt zo'n dag als {'dag': None} teruggegeven, alleen om het
    formulier na een fout opnieuw te tonen (niet om op te slaan).
    """
    uit: dict[str, str | None] = {}
    for d in DAGEN:
        tijd = str(formulier.get(TIJD_VELD + d, "") or "").strip()
        if not formulier.get(DAG_VELD + d) and not tijd:
            continue
        if not tijd:
            if streng:
                raise OpslagFout(f"Geef een begintijd op voor {d}.")
            uit[d] = None
            continue
        m = _TIJD.match(tijd.replace(".", ":"))
        if m is None:
            if streng:
                raise OpslagFout(f"Ongeldige begintijd {tijd!r} op {d}; gebruik bijv. 18:30.")
            uit[d] = None
            continue
        uit[d] = f"{int(m.group(1)):02d}:{m.group(2)}"
    return uit


def nieuw_formulier(db: Opslag, *, naam: str = "", seizoen: str | None = None, gekozen: Iterable[str] = (),
                    trainingsdagen: dict[str, str | None] | None = None,
                    peildatum: date | None = None) -> LedenFormulier:
    """Formulier voor een nieuwe groep: alle actieve atleten om uit te kiezen."""
    vandaag = peildatum or date.today()
    overigen = [Kandidaat(a, leeftijdscategorie(a, vandaag), [g.naam for g in db.groepen_van_atleet(a.master_id)])
                for a in db.atleten(alleen_actief=True)]
    groep = Groep(naam, huidig_seizoen(vandaag) if seizoen is None else seizoen,
                  trainingsdagen=dict(trainingsdagen or {}))
    return LedenFormulier(groep, [], overigen, set(gekozen), vinkjes_uit_keuze=True)


def _atleten_uit_keuze(db: Opslag, gekozen: Iterable[str]) -> dict[str, Atleet]:
    """master_ids uit het formulier -> atleten (dubbele en lege weg). Onbekende ids geven een fout."""
    uit: dict[str, Atleet] = {}
    for m in dict.fromkeys(m.strip() for m in gekozen if m and m.strip()):
        a = db.atleet(m) if len(m) == 32 else None
        if a is None:
            raise OpslagFout("Onbekende atleet in de keuze.")
        uit[m] = a
    return uit


def _controleer_dagen(trainingsdagen: dict[str, str | None]) -> dict[str, str]:
    """Controleer dagen en tijden en zet ze in weekvolgorde met tijden als 'HH:MM'.

    Elke dag heeft een begintijd nodig (leeg = geen training, dan staat de dag er niet in).
    """
    dagen: dict[str, str] = {}
    for d, t in trainingsdagen.items():
        if d not in DAGEN:
            raise OpslagFout("Ongeldige trainingsdagen.")
        if not t:
            raise OpslagFout(f"Geef een begintijd op voor {d}.")
        m = _TIJD.match(t.replace(".", ":"))
        if m is None:
            raise OpslagFout(f"Ongeldige begintijd {t!r} op {d}; gebruik bijv. 18:30.")
        dagen[d] = f"{int(m.group(1)):02d}:{m.group(2)}"
    return {d: dagen[d] for d in DAGEN if d in dagen}


def dagen_tekst(dagen: dict[str, str | None]) -> str:
    """{'dinsdag': '18:30', 'donderdag': None} -> 'Di 18:30, Do'."""
    return ", ".join(f"{DAG_KORT[d]} {t}" if t else DAG_KORT[d] for d, t in dagen.items())


def groep_aanmaken(db: Opslag, naam: str, seizoen: str | None, gekozen: Iterable[str],
                   trainingsdagen: dict[str, str | None] | None = None) -> Groep:
    """Maak een nieuwe groep met deze atleten en vaste trainingsdagen ({'dinsdag': '18:30'}).

    Fout bij lege naam of als de naam in dat seizoen al bestaat; dan wordt niets opgeslagen.
    """
    naam = " ".join((naam or "").split())
    seizoen = " ".join((seizoen or "").split()) or None
    if not naam:
        raise OpslagFout("Geef de groep een naam.")
    if len(naam) > MAX_NAAM:
        raise OpslagFout(f"De naam is te lang (maximaal {MAX_NAAM} tekens).")
    if any(g.naam.lower() == naam.lower() and g.seizoen == seizoen for g in db.groepen()):
        raise OpslagFout(f"Er is al een groep '{naam}'" + (f" in seizoen {seizoen}." if seizoen else "."))
    atleten = _atleten_uit_keuze(db, gekozen)
    dagen = _controleer_dagen(trainingsdagen or {})
    g = db.groep_opslaan(Groep(naam, seizoen, list(atleten)))
    if dagen:
        db.groep_trainingsdagen_opslaan(g.id, dagen)
        g.trainingsdagen = dagen
        for m in g.leden:
            schema_aanvullen(db, m, dagen)
    return g


def ledenformulier(db: Opslag, groep_id: int, *, peildatum: date | None = None,
                   gekozen: Iterable[str] | None = None,
                   trainingsdagen: dict[str, str | None] | None = None) -> LedenFormulier | None:
    """Formulier 'Wijzigen' van een bestaande groep: leden, andere atleten en de trainingsdagen.

    gekozen / trainingsdagen: wat er net was ingevuld (na een fout), in plaats van wat er is opgeslagen.
    """
    groep = db.groep(groep_id)
    if groep is None:
        return None
    vandaag = peildatum or date.today()
    hint = ""
    if not groep.trainingsdagen:
        dagen, _ = afgeleide_trainingsdagen(db, groep, vandaag)
        hint = dagen_tekst({d: None for d in DAGEN if d in dagen})
    if trainingsdagen is not None:
        groep.trainingsdagen = dict(trainingsdagen)

    def kandidaat(a: Atleet) -> Kandidaat:
        anderen = [g.naam for g in db.groepen_van_atleet(a.master_id) if g.id != groep.id]
        return Kandidaat(a, leeftijdscategorie(a, vandaag), anderen)

    leden = [kandidaat(a) for a in (db.atleet(m) for m in groep.leden) if a is not None]
    binnen = set(groep.leden)
    overigen = [kandidaat(a) for a in db.atleten(alleen_actief=True) if a.master_id not in binnen]
    if gekozen is None:
        return LedenFormulier(groep, leden, overigen, afgeleide_dagen=hint)
    gekozen = {m for m in gekozen if m in binnen or m in {k.atleet.master_id for k in overigen}}
    return LedenFormulier(groep, leden, overigen, gekozen, vinkjes_uit_keuze=True, afgeleide_dagen=hint)


@dataclass
class Wijziging:
    toegevoegd: list[Atleet]
    verwijderd: list[Atleet]
    dagen: dict[str, str] | None = None                            # nieuwe trainingstijden; None = niet gewijzigd
    schema_aangevuld: list[Atleet] = field(default_factory=list)   # trainingsschema kreeg dagen van de groep erbij

    @property
    def leeg(self) -> bool:
        return not self.toegevoegd and not self.verwijderd and self.dagen is None

    @property
    def tekst(self) -> str:
        """Korte melding voor na het opslaan."""
        if self.leeg:
            return "Niets gewijzigd."
        zinnen = []
        if self.toegevoegd or self.verwijderd:
            delen = []
            if self.toegevoegd:
                delen.append(f"{len(self.toegevoegd)} toegevoegd ({', '.join(a.naam for a in self.toegevoegd)})")
            if self.verwijderd:
                delen.append(f"{len(self.verwijderd)} verwijderd ({', '.join(a.naam for a in self.verwijderd)})")
            zinnen.append("Atleten gewijzigd: " + "; ".join(delen) + ".")
        if self.dagen is not None:
            zinnen.append(f"Trainingsdagen nu: {dagen_tekst(self.dagen)}." if self.dagen
                          else "Geen vaste trainingsdagen meer.")
        return " ".join(zinnen)


def leden_opslaan(db: Opslag, groep_id: int, gekozen: Iterable[str],
                  trainingsdagen: dict[str, str | None] | None = None) -> Wijziging:
    """Maak de leden van de groep precies `gekozen` (master_ids) en, als meegegeven, de
    trainingsdagen precies `trainingsdagen` ({} = geen vaste dagen; None = niet aanpassen).

    Onbekende ids of ongeldige dagen/tijden geven een fout; dan wordt niets opgeslagen.
    """
    groep = db.groep(groep_id)
    if groep is None:
        raise OpslagFout(f"Groep {groep_id} bestaat niet.")
    dagen = None if trainingsdagen is None else _controleer_dagen(trainingsdagen)
    atleten = _atleten_uit_keuze(db, gekozen)
    nieuw = list(atleten)
    oud = set(groep.leden)
    toegevoegd = [atleten[m] for m in nieuw if m not in oud]
    verwijderd = [a for a in (db.atleet(m) for m in groep.leden if m not in atleten) if a is not None]
    if toegevoegd or verwijderd:
        groep.leden = nieuw
        db.groep_opslaan(groep)
    oude_dagen = dict(groep.trainingsdagen)
    dagen_gewijzigd = dagen is not None and dagen != oude_dagen
    if dagen_gewijzigd:
        db.groep_trainingsdagen_opslaan(groep.id, dagen)
    huidige_dagen = dagen if dagen_gewijzigd else oude_dagen

    # Trainingsschema aanvullen (nooit iets weghalen): nieuwe leden krijgen alle
    # dagen van de groep, bestaande leden alleen de dagen die er nu bij kwamen.
    erbij = [d for d in huidige_dagen if d not in oude_dagen]
    aangevuld = []
    for m in nieuw:
        if schema_aanvullen(db, m, huidige_dagen if m not in oud else erbij):
            aangevuld.append(atleten[m])

    sorteer = lambda a: (a.achternaam.lower(), a.voornaam.lower())   # noqa: E731
    return Wijziging(sorted(toegevoegd, key=sorteer), sorted(verwijderd, key=sorteer),
                     dagen if dagen_gewijzigd else None, sorted(aangevuld, key=sorteer))


def trainingsdagen_opslaan(db: Opslag, groep_id: int, trainingsdagen: dict[str, str | None]) -> Wijziging:
    """Alleen de trainingsdagen en -tijden van een groep wijzigen (pagina 'Trainingsdagen wijzigen').

    Zelfde regels als leden_opslaan(): {} = geen vaste dagen meer; dagen die erbij
    komen worden aangevuld in de trainingsschema's van de leden. De leden blijven gelijk.
    """
    groep = db.groep(groep_id)
    if groep is None:
        raise OpslagFout(f"Groep {groep_id} bestaat niet.")
    return leden_opslaan(db, groep_id, groep.leden, trainingsdagen)


# ============================================================
# Trainingsschema aanvullen vanuit de groep
# ============================================================
def schema_aanvullen(db: Opslag, master_id: str, dagen: Iterable[str]) -> list[str]:
    """Zet `dagen` aan in het trainingsschema van de atleet (er gaat niets uit). Geeft de nieuwe dagen."""
    schema = db.trainingsschema(master_id)
    erbij = [d for d in DAGEN if d in set(dagen) and not schema.traint_op(d)]
    if erbij:
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(master_id, schema.dagen + erbij))
    return erbij


# ============================================================
# Weekrooster van één atleet (over al zijn groepen)
# ============================================================
@dataclass(frozen=True)
class RoosterRegel:
    dag: str                          # 'dinsdag'
    tijd: str                         # '18:30'
    groep_id: int
    groep: str                        # naam, zoals in de app


def rooster(db: Opslag, master_id: str) -> list[RoosterRegel]:
    """Alle groepstrainingen van de atleet in een week, op dag en tijd gesorteerd."""
    regels = [RoosterRegel(d, t, g.id, g.naam)
              for g in db.groepen_van_atleet(master_id) for d, t in g.trainingsdagen.items()]
    return sorted(regels, key=lambda r: (DAGEN.index(r.dag), r.tijd, r.groep.lower()))
