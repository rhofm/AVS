"""Rooster van een groep: de geplande inhoud per training, invullen, importeren en toepassen.

Een rooster is een sjabloon van een paar weken (models/rooster.py). Een groep
volgt een rooster vanaf een startdatum (groep_rooster); de koppeling geldt tot
de volgende koppeling van de groep. Optioneel: zonder koppeling gebeurt er niets.

Toepassen op trainingen (kopiëren + herkomst)
---------------------------------------------
De inhoud van de roosterregel wordt in de training gekopieerd, en
training.rooster_regel_id onthoudt waar hij vandaan komt. Zo kan de trainer de
training daarna gewoon aanpassen:
  * nieuwe trainingen (trainingen_aanvullen) krijgen meteen de inhoud uit het rooster;
  * na het koppelen of wijzigen van een rooster worden toekomstige trainingen
    bijgewerkt, maar alleen als ze nog leeg zijn of nog naar een roosterregel wijzen;
  * wie een training met de hand aanpast, maakt hem los van het rooster
    (rooster_regel_id leeg, training_bewerken); 'Terugzetten naar rooster' koppelt hem weer;
  * trainingen in het verleden veranderen nooit; afwijkende trainingen (varianten) ook niet.

Welke regel bij een training hoort: de geldende koppeling op de datum -> de
roosterweek -> de regel op die dag met dezelfde begintijd (een regel zonder
tijd hoort bij de vaste, eerste tijd van die dag).

Importeren
----------
Een tabel geplakt uit Excel (tab-gescheiden) of een CSV-bestand (';' of ',').
Eerste regel = kolomnamen: week + dag, of datum; verder tijd, onderwerp,
warming-up, kern a, kern b, cooling-down, notities (hoofdletters, spaties en
streepjes maken niet uit). Eerst controleren (voorbeeld met waarschuwingen), dan
opslaan; tussendoor wordt niets bewaard: het formulier draagt de tekst mee.

Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Mapping

from db.queries import Opslag, OpslagFout
from instellingen import dagvolgorde, weekbegin
from models import DAGEN, INHOUD, INHOUD_VELDEN, GroepRooster, Groep, Rooster, RoosterRegel, Training
from models.rooster import MAX_WEKEN

MAX_TABEL = 500_000                   # tekens in een geplakte tabel of bestand
VOORBEELD_CSV = ("week;dag;tijd;onderwerp;warming_up;kern_a;kern_b;cooling_down;notities\r\n"
                 "1;dinsdag;;Starts;Inlopen en loopscholing;Startblok 6x 20m;Tempo 4x 80m;Uitlopen;\r\n"
                 "1;donderdag;;Horden;Inlopen;Hordenritme 3 passen;;Rekken;Horden op 76 cm\r\n"
                 "2;dinsdag;;Snelheid;Inlopen en loopscholing;Vliegende 30m;;Uitlopen;\r\n")


# ============================================================
# Welke regel hoort bij een training
# ============================================================
def geldende_koppeling(koppelingen: list[GroepRooster], datum: date) -> GroepRooster | None:
    """De koppeling met de laatste startdatum <= datum (koppelingen gesorteerd op startdatum)."""
    geldend = None
    for k in koppelingen:
        if k.startdatum <= datum:
            geldend = k
    return geldend


class _Roosters:
    """Roosters per id, één keer uit de database gelezen."""

    def __init__(self, db: Opslag) -> None:
        self.db, self._cache = db, {}

    def __call__(self, rooster_id: int) -> Rooster | None:
        if rooster_id not in self._cache:
            self._cache[rooster_id] = self.db.rooster(rooster_id)
        return self._cache[rooster_id]


def _past(regel: RoosterRegel, groep: Groep, dag: str, tijd: str | None) -> bool:
    """Hoort de regel bij een training op deze dag en begintijd? Zonder tijd = de vaste tijd van de dag."""
    return regel.dag == dag and (regel.starttijd or groep.starttijd(dag)) == tijd


def regel_bij(regels: Iterable[RoosterRegel], week: int, groep: Groep, dag: str, tijd: str | None) -> RoosterRegel | None:
    """De regel voor dit moment; een regel met de exacte tijd gaat voor een regel zonder tijd."""
    passend = [r for r in regels if r.week == week and _past(r, groep, dag, tijd)]
    return next((r for r in passend if r.starttijd), passend[0] if passend else None)


def regel_voor(groep: Groep, t: Training, koppelingen: list[GroepRooster], roosters) -> RoosterRegel | None:
    """De roosterregel voor deze training, of None (geen koppeling, buiten het rooster, niets gepland)."""
    k = geldende_koppeling(koppelingen, t.datum)
    r = roosters(k.rooster_id) if k else None
    if r is None:
        return None
    week = k.week_op(t.datum, r.aantal_weken)
    if week is None:
        return None
    return regel_bij(r.regels, week, groep, DAGEN[t.datum.weekday()], t.effectieve_starttijd(groep))


def inhoud(t: Training) -> dict[str, str | None]:
    return {v: getattr(t, v) for v in INHOUD_VELDEN}


def zonder_inhoud(t: Training) -> bool:
    return not any(inhoud(t).values())


def rooster_toepassen(db: Opslag, groep: Groep, *, trainingen: list[Training] | None = None,
                      peildatum: date | None = None) -> int:
    """Zet de inhoud uit het rooster in trainingen van de groep. Geeft het aantal gewijzigde trainingen.

    trainingen: alleen deze (bijv. net aangemaakt); anders alle trainingen vanaf vandaag.
    Een training wordt alleen aangeraakt als hij nog leeg is of nog naar een roosterregel
    wijst. Wijst hij naar een regel maar is er (nu) geen regel meer, dan wordt hij weer leeg.
    """
    if groep.id is None:
        return 0
    koppelingen = db.groep_roosters(groep.id)
    lijst = trainingen if trainingen is not None else db.trainingen(groep.id, van=peildatum or date.today())
    if not koppelingen and not any(t.rooster_regel_id for t in lijst):
        return 0
    roosters = _Roosters(db)
    gewijzigd = 0
    for t in lijst:
        if t.is_afwijkend or (t.rooster_regel_id is None and not zonder_inhoud(t)):
            continue                                  # variant, of met de hand ingevuld: niet aankomen
        regel = regel_voor(groep, t, koppelingen, roosters)
        if regel is None:
            if t.rooster_regel_id is None:
                continue
            for v in INHOUD_VELDEN:
                setattr(t, v, None)
            t.rooster_regel_id = None
        elif t.rooster_regel_id == regel.id and inhoud(t) == regel.inhoud:
            continue
        else:
            for v in INHOUD_VELDEN:
                setattr(t, v, getattr(regel, v))
            t.rooster_regel_id = regel.id
        db.training_opslaan(t)
        gewijzigd += 1
    return gewijzigd


def toepassen_voor_rooster(db: Opslag, rooster_id: int, *, peildatum: date | None = None) -> int:
    """rooster_toepassen() voor elke groep die dit rooster volgt (na het wijzigen van een regel)."""
    return sum(rooster_toepassen(db, db.groep(gid), peildatum=peildatum)
               for gid in db.groepen_met_rooster(rooster_id) if db.groep(gid) is not None)


@dataclass
class RoosterStatus:
    """Hoe een training zich tot het rooster verhoudt (voor de trainingspagina)."""
    regel: RoosterRegel | None        # wat het rooster voor deze training plant
    gekoppeld: bool                   # de inhoud komt (nog) uit het rooster

    @property
    def afwijkend(self) -> bool:
        """Het rooster plant iets, maar de training is met de hand aangepast."""
        return self.regel is not None and not self.gekoppeld


def rooster_status(db: Opslag, groep: Groep, t: Training) -> RoosterStatus | None:
    """None als de groep op die datum geen rooster heeft (en de training er niet naar wijst)."""
    koppelingen = db.groep_roosters(groep.id)
    regel = regel_voor(groep, t, koppelingen, _Roosters(db)) if koppelingen else None
    if regel is None and t.rooster_regel_id is None:
        return None
    gekoppeld = t.rooster_regel_id is not None and regel is not None and t.rooster_regel_id == regel.id
    return RoosterStatus(regel, gekoppeld)


def terugzetten(db: Opslag, training_id: int) -> Training:
    """Zet de inhoud van een (gewone) training terug naar wat het rooster plant."""
    t = db.training(training_id)
    if t is None or t.is_afwijkend:
        raise OpslagFout("Alleen een gewone training kan terug naar het rooster.")
    groep = db.groep(t.groep_id)
    regel = regel_voor(groep, t, db.groep_roosters(groep.id), _Roosters(db))
    if regel is None:
        raise OpslagFout("Het rooster plant niets voor deze training.")
    for v in INHOUD_VELDEN:
        setattr(t, v, getattr(regel, v))
    t.rooster_regel_id = regel.id
    return db.training_opslaan(t)


def losmaken_als_aangepast(db: Opslag, t: Training) -> None:
    """Na het bewerken: wijkt de inhoud af van de roosterregel, dan is de training niet meer uit het rooster."""
    if t.rooster_regel_id is None:
        return
    regel = db.rooster_regel(t.rooster_regel_id)
    if regel is None or regel.inhoud != inhoud(t):
        t.rooster_regel_id = None


# ============================================================
# Rooster van een groep: koppelen en het overzicht
# ============================================================
@dataclass
class Moment:
    """Een kolom in het rooster: een vaste training van de groep in de week."""
    dag: str
    tijd: str | None                  # begintijd ('18:30'); None = groep zonder vaste tijden
    vast: bool = True                 # False = staat in het rooster, maar de groep traint dan niet


@dataclass
class Cel:
    week: int
    moment: Moment
    regel: RoosterRegel | None
    nu: bool = False                  # de week van vandaag
    tijd_veld: str = ""               # begintijd voor de link naar het bewerkformulier; '' = de vaste tijd


@dataclass
class Koppelregel:
    koppeling: GroepRooster
    rooster: Rooster
    tot: date | None                  # tot en met (volgende koppeling of einddatum); None = doorlopend
    nu: bool = False

    @property
    def omschrijving(self) -> str:
        if self.koppeling.herhalen:
            return f"{self.rooster.aantal_weken} weken, herhaalt"
        return f"{self.rooster.aantal_weken} weken, één keer"


@dataclass
class Roosterpagina:
    groep: Groep
    koppelingen: list[Koppelregel]
    rooster: Rooster | None           # het rooster dat getoond wordt
    momenten: list[Moment]
    weken: list[list[Cel]]            # per week een rij cellen (zelfde volgorde als momenten)
    andere_groepen: list[str]         # die hetzelfde rooster volgen
    roosters: list[Rooster]           # om uit te kiezen bij koppelen
    week_nu: int | None
    vandaag: date

    @property
    def standaard_start(self) -> date:
        """Voorstel voor een nieuwe koppeling: het begin van volgende week."""
        return weekbegin(self.vandaag) + timedelta(weeks=1)

    @property
    def aantal_regels(self) -> int:
        return len(self.rooster.regels) if self.rooster else 0


def _momenten(groep: Groep, rooster: Rooster | None) -> list[Moment]:
    vast = [Moment(d, t) for d in dagvolgorde() for t in groep.tijden(d)]
    uit = list(vast)
    for r in (rooster.regels if rooster else []):
        if not any(_past(r, groep, m.dag, m.tijd) for m in vast):
            m = Moment(r.dag, r.starttijd, vast=False)
            if not any((x.dag, x.tijd) == (m.dag, m.tijd) for x in uit):
                uit.append(m)
    volgorde = {d: i for i, d in enumerate(dagvolgorde())}
    return sorted(uit, key=lambda m: (volgorde[m.dag], m.tijd or ""))


def roosterpagina(db: Opslag, groep_id: int, *, rooster_id: int | None = None,
                  peildatum: date | None = None) -> Roosterpagina | None:
    groep = db.groep(groep_id)
    if groep is None:
        return None
    vandaag = peildatum or date.today()
    koppelingen = db.groep_roosters(groep_id)
    roosters = _Roosters(db)
    nu = geldende_koppeling(koppelingen, vandaag)
    regels = []
    for i, k in enumerate(koppelingen):
        r = roosters(k.rooster_id)
        volgende = koppelingen[i + 1].startdatum - timedelta(days=1) if i + 1 < len(koppelingen) else None
        tot = min((d for d in (volgende, k.einddatum) if d), default=None)
        if not k.herhalen:
            eind = k.startdatum + timedelta(weeks=r.aantal_weken, days=-1)
            tot = min(tot, eind) if tot else eind
        regels.append(Koppelregel(k, r, tot, k is nu))

    # Welk rooster tonen: gekozen, anders dat van vandaag, anders het eerstvolgende, anders het laatste.
    gekozen = None
    if rooster_id is not None:
        gekozen = roosters(rooster_id)
    elif koppelingen:
        komend = [k for k in koppelingen if k.startdatum > vandaag]
        k = nu or (komend[0] if komend else koppelingen[-1])
        gekozen = roosters(k.rooster_id)
    week_nu = None
    if gekozen is not None and nu is not None and nu.rooster_id == gekozen.id:
        week_nu = nu.week_op(vandaag, gekozen.aantal_weken)
    momenten = _momenten(groep, gekozen)
    weken = []
    if gekozen is not None:
        for w in range(1, gekozen.aantal_weken + 1):
            rij = []
            for m in momenten:
                regel = (regel_bij(gekozen.regels, w, groep, m.dag, m.tijd) if m.vast else
                         next((r for r in gekozen.regels if r.moment == (w, m.dag, m.tijd)), None))
                if regel is not None:
                    tijd_veld = regel.starttijd or ""
                else:
                    tijd_veld = "" if m.vast and m.tijd == groep.starttijd(m.dag) else (m.tijd or "")
                rij.append(Cel(w, m, regel, w == week_nu, tijd_veld))
            weken.append(rij)
    andere = []
    if gekozen is not None:
        andere = [g.naam for g in (db.groep(i) for i in db.groepen_met_rooster(gekozen.id) if i != groep_id) if g]
    return Roosterpagina(groep, regels, gekozen, momenten, weken, andere, db.roosters(), week_nu, vandaag)


def _datum(tekst: str, wat: str) -> date:
    try:
        return date.fromisoformat(str(tekst).strip())
    except ValueError:
        raise OpslagFout(f"{wat}: kies een geldige datum.") from None


def koppelen(db: Opslag, groep_id: int, formulier: Mapping[str, str], *, peildatum: date | None = None) -> tuple[GroepRooster, int]:
    """Koppel een (bestaand of nieuw) rooster aan de groep vanaf een startdatum. Geeft (koppeling, bijgewerkt).

    Velden: rooster (id of 'nieuw'), naam + weken (bij nieuw), start, herhalen ('1'), eind (optioneel).
    De start wordt het begin van de week.
    """
    groep = db.groep(groep_id)
    if groep is None:
        raise OpslagFout(f"Groep {groep_id} bestaat niet.")
    keuze = str(formulier.get("rooster", "")).strip()
    if keuze == "nieuw":
        try:
            weken = int(str(formulier.get("weken", "")).strip())
        except ValueError:
            raise OpslagFout(f"Kies het aantal weken (1 tot {MAX_WEKEN}).") from None
        try:
            rooster = db.rooster_opslaan(Rooster(formulier.get("naam", ""), weken))
        except ValueError as e:
            raise OpslagFout(str(e)) from None
    elif keuze.isdigit() and db.rooster(int(keuze)) is not None:
        rooster = db.rooster(int(keuze))
    else:
        raise OpslagFout("Kies een rooster of maak een nieuw rooster.")
    start = weekbegin(_datum(formulier.get("start", ""), "Vanaf"))
    eind = _datum(formulier["eind"], "Tot en met") if str(formulier.get("eind", "")).strip() else None
    try:
        k = GroepRooster(groep_id, rooster.id, start, formulier.get("herhalen") == "1", eind)
    except ValueError as e:
        raise OpslagFout(str(e)) from None
    db.groep_rooster_opslaan(k)
    return k, rooster_toepassen(db, db.groep(groep_id), peildatum=peildatum)


def rooster_wijzigen(db: Opslag, rooster_id: int, naam: str, weken) -> tuple[Rooster, int]:
    """Naam en aantal weken van een rooster wijzigen (geldt voor elke groep die het volgt). Geeft (rooster, bijgewerkt)."""
    if db.rooster(rooster_id) is None:
        raise OpslagFout(f"Rooster {rooster_id} bestaat niet.")
    try:
        aantal = int(str(weken).strip())
    except ValueError:
        raise OpslagFout(f"Kies 1 tot {MAX_WEKEN} weken.") from None
    try:
        r = db.rooster_opslaan(Rooster(naam, aantal, id=rooster_id))
    except ValueError as e:
        raise OpslagFout(str(e)) from None
    return r, toepassen_voor_rooster(db, rooster_id)


def ontkoppelen(db: Opslag, groep_id: int, startdatum: str, *, peildatum: date | None = None) -> int:
    """Haal een koppeling weg; toekomstige trainingen die uit dat rooster kwamen worden bijgewerkt."""
    groep = db.groep(groep_id)
    if groep is None:
        raise OpslagFout(f"Groep {groep_id} bestaat niet.")
    db.groep_rooster_verwijderen(groep_id, _datum(startdatum, "Koppeling"))
    return rooster_toepassen(db, groep, peildatum=peildatum)


# ============================================================
# Eén regel bewerken
# ============================================================
@dataclass
class Regelformulier:
    rooster: Rooster
    week: int
    dag: str
    tijd: str | None
    waarden: dict[str, str]
    groep: Groep | None = None        # waar je vandaan komt (terug-link)
    andere_groepen: list[str] = field(default_factory=list)

    @property
    def velden(self) -> list[tuple[str, str, int, str]]:
        return [(v, titel, n, self.waarden.get(v, "")) for v, titel, n in INHOUD]


def _moment(rooster: Rooster, week, dag, tijd) -> tuple[int, str, str | None]:
    try:
        week = int(week)
    except (TypeError, ValueError):
        raise OpslagFout("Onbekende week.") from None
    if not 1 <= week <= rooster.aantal_weken:
        raise OpslagFout(f"Het rooster heeft {rooster.aantal_weken} weken.")
    dag = str(dag or "").lower()
    if dag not in DAGEN:
        raise OpslagFout("Onbekende dag.")
    try:
        return week, dag, RoosterRegel(week, dag, tijd or None).starttijd
    except ValueError as e:
        raise OpslagFout(str(e)) from None


def regelformulier(db: Opslag, rooster_id: int, week, dag, tijd, *, groep_id: int | None = None,
                   ingevuld: Mapping[str, str] | None = None) -> Regelformulier | None:
    r = db.rooster(rooster_id)
    if r is None:
        return None
    week, dag, tijd = _moment(r, week, dag, tijd)
    if ingevuld is not None:
        waarden = {v: str(ingevuld.get(v, "")) for v in INHOUD_VELDEN}
    else:
        regel = db.rooster_regel_op(r.id, week, dag, tijd)
        waarden = {v: (getattr(regel, v) or "") if regel else "" for v in INHOUD_VELDEN}
    groep = db.groep(groep_id) if groep_id else None
    andere = [g.naam for g in (db.groep(i) for i in db.groepen_met_rooster(r.id)) if g and g.id != groep_id]
    return Regelformulier(r, week, dag, tijd, waarden, groep, andere)


def _lees_inhoud(formulier: Mapping[str, str]) -> dict[str, str | None]:
    uit = {}
    for veld, titel, maximaal in INHOUD:
        tekst = str(formulier.get(veld, "") or "").replace("\r\n", "\n").strip()
        if len(tekst) > maximaal:
            raise OpslagFout(f"{titel} is te lang (maximaal {maximaal} tekens).")
        uit[veld] = tekst or None
    return uit


def regel_opslaan(db: Opslag, rooster_id: int, week, dag, tijd, formulier: Mapping[str, str], *,
                  peildatum: date | None = None) -> tuple[RoosterRegel | None, int]:
    """Sla een regel op (alles leeg = regel weg) en werk de trainingen bij. Geeft (regel, bijgewerkt)."""
    r = db.rooster(rooster_id)
    if r is None:
        raise OpslagFout(f"Rooster {rooster_id} bestaat niet.")
    week, dag, tijd = _moment(r, week, dag, tijd)
    nieuw = RoosterRegel(week, dag, tijd, rooster_id=r.id, **_lees_inhoud(formulier))
    geleegd = 0
    bestaand = db.rooster_regel_op(r.id, week, dag, tijd)
    if nieuw.leeg and bestaand is not None:
        # Eerst de toekomstige trainingen uit deze regel leegmaken: na het weghalen van de regel
        # zet de database hun verwijzing op NULL en lijken ze met de hand ingevuld.
        for t in db.trainingen_uit_regel(bestaand.id, van=peildatum or date.today()):
            for v in INHOUD_VELDEN:
                setattr(t, v, None)
            t.rooster_regel_id = None
            db.training_opslaan(t)
            geleegd += 1
    regel = db.rooster_regel_opslaan(nieuw)
    return regel, geleegd + toepassen_voor_rooster(db, r.id, peildatum=peildatum)


# ============================================================
# Importeren: geplakte tabel of CSV
# ============================================================
_KOLOMMEN = {
    "week": "week", "weeknummer": "week", "wk": "week",
    "dag": "dag", "weekdag": "dag",
    "datum": "datum", "date": "datum",
    "tijd": "tijd", "starttijd": "tijd", "begintijd": "tijd", "aanvang": "tijd",
    "onderwerp": "onderwerp", "titel": "onderwerp", "thema": "onderwerp",
    "warmingup": "warming_up", "warming": "warming_up", "wu": "warming_up",
    "kerna": "kern_a", "kern1": "kern_a", "kern": "kern_a",
    "kernb": "kern_b", "kern2": "kern_b",
    "coolingdown": "cooling_down", "cooldown": "cooling_down", "cd": "cooling_down",
    "notities": "notities", "notitie": "notities", "opmerking": "notities", "opmerkingen": "notities",
}


def _kolom(naam: str) -> str | None:
    sleutel = re.sub(r"[\s_\-.]+", "", naam.strip().lower().lstrip("﻿"))
    return _KOLOMMEN.get(sleutel)


def _dag(tekst: str) -> str | None:
    """'dinsdag', 'Di', 'di.', 'din' -> 'dinsdag'. Minstens twee letters."""
    t = tekst.strip().lower().rstrip(".")
    if len(t) < 2:
        return None
    return next((d for d in DAGEN if d.startswith(t)), None)


def _lees_datum(tekst: str) -> date | None:
    t = tekst.strip()
    try:
        return date.fromisoformat(t)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", t)          # 6-10-2026, 06/10/2026
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


@dataclass
class Importregel:
    rij: int                          # regelnummer in de tabel (kop = 1)
    regel: RoosterRegel | None
    fout: str | None = None
    let_op: str | None = None


@dataclass
class Importresultaat:
    regels: list[Importregel]
    met_datum: bool                   # kolom datum i.p.v. week + dag
    start: date | None                # bij datums: begin van week 1
    aantal_weken: int
    fout: str | None = None           # de hele tabel is onbruikbaar

    @property
    def goed(self) -> list[RoosterRegel]:
        return [r.regel for r in self.regels if r.regel is not None and r.fout is None]

    @property
    def fouten(self) -> list[Importregel]:
        return [r for r in self.regels if r.fout]

    @property
    def let_op(self) -> list[Importregel]:
        return [r for r in self.regels if r.let_op and not r.fout]

    @property
    def bruikbaar(self) -> bool:
        return self.fout is None and not self.fouten and bool(self.goed)


def decodeer(inhoud: bytes) -> str:
    """Bytes van een geüpload bestand naar tekst: UTF-8 (met of zonder BOM), anders Windows-1252 (Excel)."""
    try:
        return inhoud.decode("utf-8-sig")
    except UnicodeDecodeError:
        return inhoud.decode("cp1252", errors="replace")


def lees_tabel(tekst: str, *, groep: Groep | None = None, start: date | None = None) -> Importresultaat:
    """Lees een geplakte tabel of CSV-tekst. start: bij een kolom datum het begin van week 1
    (standaard het begin van de week van de vroegste datum). Controleert ook tegen de trainingen van de groep."""
    tekst = (tekst or "").lstrip("﻿")
    if len(tekst) > MAX_TABEL:
        return Importresultaat([], False, None, 0, "De tabel is te groot.")
    regels_tekst = [r for r in tekst.splitlines() if r.strip()]
    if len(regels_tekst) < 2:
        return Importresultaat([], False, None, 0, "Plak een tabel met een kopregel en minstens één regel.")
    kop = regels_tekst[0]
    scheiding = "\t" if "\t" in kop else (";" if kop.count(";") >= kop.count(",") else ",")
    rijen = list(csv.reader(io.StringIO(tekst.strip("\r\n")), delimiter=scheiding))
    kolommen = [_kolom(k) for k in rijen[0]]
    if "datum" in kolommen:
        met_datum = True
    elif "week" in kolommen and "dag" in kolommen:
        met_datum = False
    else:
        return Importresultaat([], False, None, 0,
                               "De kopregel heeft een kolom 'datum' nodig, of de kolommen 'week' en 'dag'.")
    if not any(k in INHOUD_VELDEN for k in kolommen):
        return Importresultaat([], met_datum, None, 0,
                               "Geen kolom met inhoud gevonden (onderwerp, warming-up, kern a, kern b, cooling-down of notities).")

    ruw = []
    for nr, rij in enumerate(rijen[1:], start=2):
        if not any(c.strip() for c in rij):
            continue
        ruw.append((nr, {k: (rij[i] if i < len(rij) else "") for i, k in enumerate(kolommen) if k}))

    datums = {}
    if met_datum:
        for nr, w in ruw:
            d = _lees_datum(w.get("datum", ""))
            if d is not None:
                datums[nr] = d
        if start is None and datums:
            start = weekbegin(min(datums.values()))
        elif start is not None:
            start = weekbegin(start)

    uit, gezien = [], {}
    for nr, w in ruw:
        try:
            if met_datum:
                d = datums.get(nr)
                if d is None:
                    raise ValueError(f"'{w.get('datum', '')}' is geen datum (gebruik bijv. 2026-10-06 of 6-10-2026).")
                if start is None or d < start:
                    raise ValueError("Deze datum ligt voor de start van het rooster.")
                week, dag = (weekbegin(d) - start).days // 7 + 1, DAGEN[d.weekday()]
            else:
                try:
                    week = int(w.get("week", "").strip())
                except ValueError:
                    raise ValueError(f"'{w.get('week', '')}' is geen weeknummer.") from None
                dag = _dag(w.get("dag", ""))
                if dag is None:
                    raise ValueError(f"'{w.get('dag', '')}' is geen dag (maandag … zondag of ma … zo).")
            if not 1 <= week <= MAX_WEKEN:
                raise ValueError(f"Week {week}: een rooster heeft 1 tot {MAX_WEKEN} weken.")
            velden = {}
            for veld, titel, maximaal in INHOUD:
                waarde = w.get(veld, "").replace("\r\n", "\n").strip()
                if len(waarde) > maximaal:
                    raise ValueError(f"{titel} is te lang (maximaal {maximaal} tekens).")
                velden[veld] = waarde or None
            regel = RoosterRegel(week, dag, w.get("tijd", "").strip() or None, **velden)
        except ValueError as e:
            uit.append(Importregel(nr, None, str(e)))
            continue
        if regel.leeg:
            continue                                  # niets ingevuld: overslaan
        let_op = None
        if regel.moment in gezien:
            gezien[regel.moment].let_op = f"Dubbel met regel {nr}: die telt."
        gezien[regel.moment] = item = Importregel(nr, regel)
        if groep is not None and groep.trainingsdagen:
            if not groep.tijden(regel.dag):
                let_op = f"{regel.dag.capitalize()} is geen trainingsdag van {groep.naam}."
            elif regel.starttijd and regel.starttijd not in groep.tijden(regel.dag):
                let_op = f"{groep.naam} traint op {regel.dag} niet om {regel.starttijd}."
        item.let_op = item.let_op or let_op
        uit.append(item)
    goed = [r.regel for r in uit if r.regel is not None]
    aantal = max((r.week for r in goed), default=0)
    return Importresultaat(uit, met_datum, start, aantal)


def importeren(db: Opslag, groep_id: int, formulier: Mapping[str, str], tekst: str, *,
               peildatum: date | None = None) -> tuple[Rooster, GroepRooster, int]:
    """Maak een nieuw rooster uit de tabel en koppel het aan de groep. Geeft (rooster, koppeling, bijgewerkt).

    Velden: naam, start (begin van week 1; bij datums mag hij leeg zijn), herhalen ('1'), eind (optioneel).
    """
    groep = db.groep(groep_id)
    if groep is None:
        raise OpslagFout(f"Groep {groep_id} bestaat niet.")
    start = _datum(formulier["start"], "Vanaf") if str(formulier.get("start", "")).strip() else None
    res = lees_tabel(tekst, groep=groep, start=start)
    if res.fout:
        raise OpslagFout(res.fout)
    if res.fouten:
        raise OpslagFout(f"{len(res.fouten)} {'regels kloppen' if len(res.fouten) != 1 else 'regel klopt'} niet; "
                         "pas de tabel aan.")
    if not res.goed:
        raise OpslagFout("Er staat niets in de tabel om te importeren.")
    start = res.start if res.met_datum else (weekbegin(start) if start else None)
    if start is None:
        raise OpslagFout("Kies vanaf wanneer de groep het rooster volgt.")
    try:
        rooster = db.rooster_opslaan(Rooster(formulier.get("naam", ""), res.aantal_weken))
    except ValueError as e:
        raise OpslagFout(str(e)) from None
    db.rooster_regels_vervangen(rooster.id, res.goed)
    eind = _datum(formulier["eind"], "Tot en met") if str(formulier.get("eind", "")).strip() else None
    try:
        k = GroepRooster(groep_id, rooster.id, start, formulier.get("herhalen") == "1", eind)
    except ValueError as e:
        raise OpslagFout(str(e)) from None
    db.groep_rooster_opslaan(k)
    return db.rooster(rooster.id), k, rooster_toepassen(db, db.groep(groep_id), peildatum=peildatum)
