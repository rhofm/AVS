"""De pagina van één wedstrijd: tijdschema met deelnemers, en atleten inschrijven.

    d = wedstrijd_detail(db, wedstrijd_id)          # voor ui/templates/wedstrijd.html
    f = inschrijfformulier(db, wedstrijd_id, regel_id=12)
    aantal = inschrijven_uit_formulier(db, wedstrijd_id, ["<master_id>", ...], [3, 7])
    w = gegevens_opslaan(db, wedstrijd_id, Gegevens("Clubkampioenschappen", "2027-05-15"))  # wijzigen
    w = gegevens_opslaan(db, None, Gegevens("Clubkampioenschappen", "2027-05-15"))          # nieuw, met de hand

Wie bij welke regel van het tijdschema hoort, rekent wedstrijden/chronoloog.py
uit (inschrijving + categorie van de atleet op de wedstrijddag); hier wordt het
alleen per dag gegroepeerd en aangevuld met:
  * de deelnemerslijst (per atleet de onderdelen, en welke daarvan niet in het
    tijdschema te vinden zijn, of 'onderdelen volgen nog');
  * de botsingen uit chronoloog.botsingen().

Inschrijven vanuit een regel van het tijdschema: het onderdeel staat dan al
aangevinkt en de atleten die qua categorie niet passen, staan apart (de pagina
toont ze pas als je erom vraagt).

Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Iterable

from atleten.landingspagina import categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
from instellingen import naam_sleutel, tijd as toon_tijd, tijdvak
from models import Atleet, Onderdeel, ProgrammaOnderdeel, Wedstrijd

from . import chronoloog, planning


# ============================================================
# Tijdschema met deelnemers
# ============================================================
@dataclass
class TijdschemaRij:
    regel: ProgrammaOnderdeel
    atleten: list[Atleet] = field(default_factory=list)       # doen zeker mee
    misschien: list[Atleet] = field(default_factory=list)     # categorie niet zeker te koppelen

    @property
    def heeft_atleten(self) -> bool:
        return bool(self.atleten or self.misschien)

    @property
    def tijd(self) -> str:
        """'10:30–10:50u', of '10:30u' zonder duur (notatie volgens Instellingen)."""
        r = self.regel
        return tijdvak(r.starttijd, r.eindtijd) if r.eindtijd else toon_tijd(r.starttijd)

    @property
    def onderdeel(self) -> str:
        return self.regel.naam

    @property
    def details(self) -> str:
        """'serie, groep 2' (leeg als er niets bij staat)."""
        r = self.regel
        return ", ".join(x for x in (r.ronde, f"groep {r.groep}" if r.groep else "") if x)


@dataclass
class TijdschemaDag:
    datum: date
    rijen: list[TijdschemaRij]

    @property
    def met_atleten(self) -> int:
        return sum(r.heeft_atleten for r in self.rijen)


@dataclass
class Deelnemer:
    atleet: Atleet
    categorie: str | None                     # 'U16V' op de wedstrijddag; None = onbekend
    onderdelen: list[Onderdeel]               # ingeschreven onderdelen; [] = onderdelen volgen nog
    niet_in_tijdschema: list[str] = field(default_factory=list)   # onderdeelnamen zonder passende regel

    @property
    def volgt_nog(self) -> bool:
        return not self.onderdelen


@dataclass
class UitslagRij:
    """Eén prestatie van een van onze atleten op deze wedstrijd."""
    atleet: Atleet
    onderdeel: str
    prestatie: str                            # zoals trainers hem lezen: '12,93', '1:58,21', '4,80 m'
    wind: float | None
    pr: bool                                  # is dit (nu) het PR van de atleet op dit onderdeel?

    @property
    def wind_tekst(self) -> str:
        return "" if self.wind is None else f"{self.wind:+.1f}".replace(".", ",")


@dataclass
class WedstrijdDetail:
    wedstrijd: Wedstrijd
    dagen: list[TijdschemaDag]
    deelnemers: list[Deelnemer]
    botsingen: list[chronoloog.Botsing]
    dagen_tot: int                            # 0 = vandaag, negatief = geweest
    uitslagen: list[UitslagRij] = field(default_factory=list)   # op achternaam, dan onderdeel

    @property
    def uitslag_mogelijk(self) -> bool:
        """Vanaf de wedstrijddag kun je de uitslag importeren."""
        return self.dagen_tot <= 0

    @property
    def aantal_met_uitslag(self) -> int:
        return len({r.atleet.master_id for r in self.uitslagen})

    @property
    def geweest(self) -> bool:
        return self.dagen_tot < 0

    @property
    def heeft_tijdschema(self) -> bool:
        return any(d.rijen for d in self.dagen)

    @property
    def aantal_regels(self) -> int:
        return sum(len(d.rijen) for d in self.dagen)

    @property
    def aantal_met_atleten(self) -> int:
        return sum(d.met_atleten for d in self.dagen)

    @property
    def aantal_zonder_atleten(self) -> int:
        return self.aantal_regels - self.aantal_met_atleten

    @property
    def meerdaags(self) -> bool:
        return len(self.dagen) > 1

    @property
    def zonder_plek(self) -> list[Deelnemer]:
        """Ingeschreven, maar (een deel) niet terug te vinden in het tijdschema."""
        if not self.heeft_tijdschema:
            return []
        return [d for d in self.deelnemers if d.volgt_nog or d.niet_in_tijdschema]


def _sorteer(a: Atleet) -> tuple[str, str, str]:
    """Op achternaam of voornaam, zoals in Instellingen gekozen."""
    return naam_sleutel(a)


def _code(a: Atleet, op: date) -> str | None:
    return categorie_code(leeftijdscategorie(a, op), a.geslacht)


def wedstrijd_detail(db: Opslag, wedstrijd_id: int, peildatum: date | None = None) -> WedstrijdDetail | None:
    """Alles voor de wedstrijdpagina; None als de wedstrijd niet bestaat."""
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        return None
    vandaag = peildatum or date.today()

    per_dag: dict[date, list[TijdschemaRij]] = {}
    gedekt: dict[str, set[int]] = {}              # master_id -> onderdeel_ids die in het tijdschema staan
    for o in chronoloog.overzicht(db, wedstrijd_id):
        per_dag.setdefault(o.regel.datum, []).append(TijdschemaRij(o.regel, o.atleten, o.misschien))
        for a in [*o.atleten, *o.misschien]:
            gedekt.setdefault(a.master_id, set()).add(o.regel.onderdeel_id)
    dagen = [TijdschemaDag(d, per_dag[d]) for d in sorted(per_dag)]

    alle_onderdelen = {o.id: o for o in db.onderdelen()}
    per_atleet: dict[str, list[Onderdeel]] = {}
    for i in db.deelnemers(wedstrijd_id):
        lijst = per_atleet.setdefault(i.atleet_id, [])
        if i.onderdeel_id is not None and i.onderdeel_id in alle_onderdelen:
            lijst.append(alle_onderdelen[i.onderdeel_id])
    deelnemers = []
    for mid, onderdelen in per_atleet.items():
        a = db.atleet(mid)
        if a is None:
            continue
        onderdelen.sort(key=lambda o: o.naam.lower())
        los = [o.naam for o in onderdelen if o.id not in gedekt.get(mid, set())]
        deelnemers.append(Deelnemer(a, _code(a, w.datum), onderdelen, los))
    deelnemers.sort(key=lambda d: _sorteer(d.atleet))

    return WedstrijdDetail(w, dagen, deelnemers, chronoloog.botsingen(db, wedstrijd_id),
                           (w.datum - vandaag).days, _uitslagen(db, wedstrijd_id, alle_onderdelen))


def _uitslagen(db: Opslag, wedstrijd_id: int, onderdelen: dict[int, Onderdeel]) -> list[UitslagRij]:
    from atleten.prestaties import toon_waarde
    uit, atleten, prs = [], {}, {}
    for p in db.prestaties_van_wedstrijd(wedstrijd_id):
        o = onderdelen.get(p.onderdeel_id)
        if o is None:
            continue
        if p.atleet_id not in atleten:
            atleten[p.atleet_id] = db.atleet(p.atleet_id)
            prs[p.atleet_id] = {x.onderdeel_id: x.waarde for x in db.prs(p.atleet_id)}
        a = atleten[p.atleet_id]
        if a is None:
            continue
        uit.append(UitslagRij(a, o.naam, toon_waarde(p.waarde, o.eenheid), p.wind,
                              prs[p.atleet_id].get(o.id) == p.waarde))
    return sorted(uit, key=lambda r: (*_sorteer(r.atleet), r.onderdeel.lower()))


# ============================================================
# Inschrijven
# ============================================================
@dataclass
class Kandidaat:
    atleet: Atleet
    categorie: str | None                     # 'U16V' op de wedstrijddag
    past: bool | None                         # past bij de categorie van de regel (None = niet te zeggen)
    ingeschreven: list[str]                   # onderdelen waarvoor al ingeschreven ([] + al_mee = volgt nog)
    al_mee: bool                              # staat al op de deelnemerslijst van deze wedstrijd

    @property
    def zoektekst(self) -> str:
        return " ".join(x for x in (self.atleet.naam, self.categorie or "", self.atleet.specialisatie or "")).lower()


@dataclass
class InschrijfFormulier:
    wedstrijd: Wedstrijd
    regel: ProgrammaOnderdeel | None          # ingeschreven vanuit deze regel van het tijdschema
    onderdelen: list[Onderdeel]               # uit het tijdschema (of alle, zonder tijdschema)
    overige_onderdelen: list[Onderdeel]       # de rest van de onderdelenlijst
    gekozen_onderdelen: set[int]
    kandidaten: list[Kandidaat]               # actieve atleten (en wie al meegaat), op achternaam
    gekozen: set[str] = field(default_factory=set)   # aangevinkte atleten (na een fout opnieuw tonen)

    @property
    def overige_gekozen(self) -> bool:
        """Is er een onderdeel buiten het tijdschema aangevinkt (dan staat dat lijstje open)?"""
        return any(o.id in self.gekozen_onderdelen for o in self.overige_onderdelen)

    @property
    def passend(self) -> list[Kandidaat]:
        return [k for k in self.kandidaten if k.past is not False]

    @property
    def niet_passend(self) -> list[Kandidaat]:
        return [k for k in self.kandidaten if k.past is False]


def inschrijfformulier(db: Opslag, wedstrijd_id: int, regel_id: int | None = None, *,
                       onderdelen: Iterable[int] = (), gekozen: Iterable[str] = ()) -> InschrijfFormulier | None:
    """Formulier om atleten in te schrijven; None als de wedstrijd (of de regel) niet bestaat."""
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        return None
    regel = None
    if regel_id is not None:
        regel = db.programma_regel(regel_id)
        if regel is None or regel.wedstrijd_id != wedstrijd_id:
            return None

    alle = db.onderdelen()
    in_schema = {r.onderdeel_id for r in db.programma(wedstrijd_id) if r.onderdeel_id is not None}
    if in_schema:
        eerst = [o for o in alle if o.id in in_schema]
        rest = [o for o in alle if o.id not in in_schema]
    else:
        eerst, rest = alle, []
    gekozen_onderdelen = set(onderdelen)
    if regel is not None and regel.onderdeel_id is not None:
        gekozen_onderdelen.add(regel.onderdeel_id)

    namen = {o.id: o.naam for o in alle}
    per_atleet: dict[str, list[str]] = {}
    for i in db.deelnemers(wedstrijd_id):
        lijst = per_atleet.setdefault(i.atleet_id, [])
        if i.onderdeel_id is not None and i.onderdeel_id in namen:
            lijst.append(namen[i.onderdeel_id])
    atleten = {a.master_id: a for a in db.atleten(alleen_actief=True)}
    for mid in per_atleet:                                  # wie al meegaat, ook als niet (meer) actief
        if mid not in atleten and (a := db.atleet(mid)) is not None:
            atleten[mid] = a

    kandidaten = []
    for a in sorted(atleten.values(), key=_sorteer):
        cat = leeftijdscategorie(a, w.datum)
        past = chronoloog.past_bij(regel, cat, a.geslacht) if regel is not None else True
        kandidaten.append(Kandidaat(a, categorie_code(cat, a.geslacht), past,
                                    sorted(per_atleet.get(a.master_id, []), key=str.lower),
                                    a.master_id in per_atleet))
    return InschrijfFormulier(w, regel, eerst, rest, gekozen_onderdelen, kandidaten, set(gekozen))


def inschrijven_uit_formulier(db: Opslag, wedstrijd_id: int, master_ids: Iterable[str],
                              onderdeel_ids: Iterable[int | str]) -> int:
    """Schrijf de gekozen atleten in voor de gekozen onderdelen (geen onderdelen = 'volgen nog').

    Eerst alles controleren, dan pas opslaan. Geeft het aantal atleten.
    """
    if db.wedstrijd(wedstrijd_id) is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    ids = list(dict.fromkeys(m for m in master_ids if m))
    if not ids:
        raise OpslagFout("Vink minstens één atleet aan.")
    for m in ids:
        if db.atleet(m) is None:
            raise OpslagFout("Een van de gekozen atleten bestaat niet (meer).")
    onderdelen = []
    for o in dict.fromkeys(onderdeel_ids):
        try:
            oid = int(o)
        except (TypeError, ValueError):
            raise OpslagFout("Onbekend onderdeel gekozen.") from None
        if db.onderdeel(oid) is None:
            raise OpslagFout("Onbekend onderdeel gekozen.")
        onderdelen.append(oid)
    for m in ids:
        planning.inschrijven(db, wedstrijd_id, m, onderdelen)
    return len(ids)


def afmelden(db: Opslag, wedstrijd_id: int, master_id: str, onderdeel_id: int | None = None) -> str:
    """Afmelden voor één onderdeel of de hele wedstrijd. Geeft een zin voor de melding.

    Was dit het laatste onderdeel, dan blijft de atleet op de lijst met 'onderdelen
    volgen nog' (alleen 'Afmelden' zonder onderdeel haalt hem van de wedstrijd).
    """
    a = db.atleet(master_id)
    if a is None or db.wedstrijd(wedstrijd_id) is None:
        raise OpslagFout("Deze atleet of wedstrijd bestaat niet (meer).")
    if onderdeel_id is None:
        planning.afmelden(db, wedstrijd_id, master_id)
        return f"{a.naam} is afgemeld voor deze wedstrijd."
    o = db.onderdeel(onderdeel_id)
    if o is None:
        raise OpslagFout("Onbekend onderdeel.")
    planning.afmelden(db, wedstrijd_id, master_id, onderdeel_id)
    if not [i for i in db.inschrijvingen(master_id) if i.wedstrijd_id == wedstrijd_id]:
        planning.inschrijven(db, wedstrijd_id, master_id)            # blijft mee, onderdelen volgen nog
    return f"{a.naam} is afgemeld voor {o.naam}."


# ============================================================
# Gegevens van de wedstrijd (nieuw met de hand, of wijzigen)
# ============================================================
@dataclass
class Gegevens:
    """Wat er in het formulier staat (ook na een fout, zodat niets opnieuw getypt hoeft)."""
    naam: str = ""
    datum: str = ""                    # 'YYYY-MM-DD' zoals <input type="date"> hem geeft
    locatie: str = ""
    link: str = ""
    indoor: bool = False

    @classmethod
    def van(cls, w: Wedstrijd) -> Gegevens:
        return cls(w.naam, w.datum.isoformat(), w.locatie or "", w.bron_url or "", w.indoor)


def gegevens_opslaan(db: Opslag, wedstrijd_id: int | None, g: Gegevens) -> Wedstrijd:
    """Nieuwe wedstrijd (wedstrijd_id None) of de gegevens van een bestaande wijzigen.

    De link wordt genormaliseerd (zie planning.normaliseer_link) en mag niet al bij
    een andere wedstrijd horen: dan zouden planning en uitslag uit elkaar lopen.
    Het tijdschema verandert niet; werk dat bij met 'Tijdschema bijwerken'.
    """
    naam = " ".join(g.naam.split())
    if not naam:
        raise OpslagFout("Geef de wedstrijd een naam.")
    try:
        datum = date.fromisoformat(g.datum.strip())
    except ValueError:
        raise OpslagFout("Vul een geldige datum in.") from None
    link = planning.normaliseer_link(g.link)
    if link and not link.lower().startswith(("http://", "https://")):
        raise OpslagFout("De link moet beginnen met https:// (bijv. een pagina op atletiek.nu of Seltec).")

    oud = None
    if wedstrijd_id is not None:
        oud = db.wedstrijd(wedstrijd_id)
        if oud is None:
            raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    if link:
        ander = next((w for w in db.wedstrijden() if w.bron_url == link and w.id != wedstrijd_id), None)
        if ander is not None:
            raise OpslagFout(f"Deze link hoort al bij de wedstrijd '{ander.naam}' van {ander.datum.isoformat()}.")
    bron = planning.bron_uit_link(link)
    if oud is not None and not link and oud.bron != "handmatig" and db.prestaties_van_wedstrijd(oud.id):
        bron = oud.bron                  # uitslag al geïmporteerd: herkomst blijft kloppen
    w = Wedstrijd(naam=naam, datum=datum, locatie=" ".join(g.locatie.split()) or None, bron=bron,
                  bron_url=link, indoor=bool(g.indoor), id=wedstrijd_id)
    return db.wedstrijd_opslaan(w)


# ============================================================
# Tijdschema aanpassen (tijd, duur en dag per regel)
# ============================================================
# Voor als één of een paar onderdelen wat verschuiven. Alleen de regels die echt
# veranderen worden opgeslagen; de volgorde volgt daarna vanzelf uit dag en tijd
# (Opslag.programma sorteert daarop). Let op: 'Tijdschema bijwerken' haalt alles
# opnieuw op van de site en overschrijft deze aanpassingen.

def _veld(soort: str, regel_id: int) -> str:
    return f"{soort}-{regel_id}"


@dataclass
class RegelInvoer:
    regel: ProgrammaOnderdeel           # zoals opgeslagen
    dag: str                            # 'YYYY-MM-DD', zoals in het formulier
    tijd: str                           # 'HH:MM'
    duur: str                           # minuten als tekst; '' = onbekend

    @property
    def veld_dag(self) -> str:
        return _veld("dag", self.regel.id)

    @property
    def veld_tijd(self) -> str:
        return _veld("tijd", self.regel.id)

    @property
    def veld_duur(self) -> str:
        return _veld("duur", self.regel.id)

    @property
    def details(self) -> str:
        r = self.regel
        return ", ".join(x for x in (r.ronde, f"groep {r.groep}" if r.groep else "") if x)


@dataclass
class TijdschemaFormulier:
    regels: list[RegelInvoer]           # op dag en tijd zoals opgeslagen
    dagen: list[date]                   # de dagen van de wedstrijd (voor de keuzelijst)

    @property
    def meerdaags(self) -> bool:
        return len(self.dagen) > 1


def tijdschemaformulier(db: Opslag, wedstrijd_id: int, formulier=None) -> TijdschemaFormulier:
    """De regels om aan te passen; met `formulier` (na een fout) staan de ingevulde waarden erin."""
    regels = db.programma(wedstrijd_id)
    w = db.wedstrijd(wedstrijd_id)
    dagen = sorted({r.datum for r in regels} | ({w.datum} if w else set()))
    invoer = []
    for r in regels:
        f = formulier or {}
        invoer.append(RegelInvoer(
            r, f.get(_veld("dag", r.id), r.datum.isoformat()), f.get(_veld("tijd", r.id), r.starttijd),
            f.get(_veld("duur", r.id), "" if r.duur is None else str(r.duur))))
    return TijdschemaFormulier(invoer, dagen)


@dataclass(frozen=True)
class TijdWijziging:
    oud: ProgrammaOnderdeel
    nieuw: ProgrammaOnderdeel

    @property
    def tekst(self) -> str:
        o, n = self.oud, self.nieuw
        delen = []
        if o.datum != n.datum:
            delen.append(f"{o.datum.isoformat()} → {n.datum.isoformat()}")
        if o.starttijd != n.starttijd:
            delen.append(f"{toon_tijd(o.starttijd)} → {toon_tijd(n.starttijd)}")
        if o.duur != n.duur:
            delen.append(f"duur {o.duur or '?'} → {n.duur or '?'} min")
        return f"{o.omschrijving}: {', '.join(delen)}"


def tijdschema_wijzigingen(db: Opslag, wedstrijd_id: int, formulier) -> list[TijdWijziging]:
    """Lees het formulier en controleer alles; geeft alleen de regels die echt veranderen.

    Velden per regel: tijd-<id> ('HH:MM'), duur-<id> (minuten, leeg = onbekend) en
    dag-<id> ('YYYY-MM-DD', alleen bij meerdaagse wedstrijden in het formulier).
    Regels die niet in het formulier staan, blijven zoals ze zijn. Fout -> OpslagFout,
    en dan is er nog niets opgeslagen.
    """
    uit = []
    for r in db.programma(wedstrijd_id):
        tijd = formulier.get(_veld("tijd", r.id))
        duur = formulier.get(_veld("duur", r.id))
        dag = formulier.get(_veld("dag", r.id))
        if tijd is None and duur is None and dag is None:
            continue
        try:
            datum = r.datum if dag is None else date.fromisoformat(dag.strip())
        except ValueError:
            raise OpslagFout(f"{r.omschrijving}: kies een geldige dag.") from None
        if tijd is not None and not tijd.strip():
            raise OpslagFout(f"{r.omschrijving}: vul een starttijd in.")
        nieuwe_duur = r.duur
        if duur is not None:
            duur = duur.strip()
            if not duur:
                nieuwe_duur = None
            elif duur.isdigit():
                nieuwe_duur = int(duur)
            else:
                raise OpslagFout(f"{r.omschrijving}: de duur is een aantal minuten (of leeg).")
        try:
            nieuw = replace(r, datum=datum, starttijd=r.starttijd if tijd is None else tijd.strip(),
                            duur=nieuwe_duur)
        except ValueError as e:
            raise OpslagFout(f"{r.omschrijving}: {e}") from None
        if (nieuw.datum, nieuw.starttijd, nieuw.duur) != (r.datum, r.starttijd, r.duur):
            uit.append(TijdWijziging(r, nieuw))
    return uit


def tijdschema_aanpassen(db: Opslag, wijzigingen: Iterable[TijdWijziging]) -> int:
    """Sla de gecontroleerde wijzigingen op. Geeft het aantal aangepaste regels."""
    n = 0
    for w in wijzigingen:
        db.programma_opslaan(w.nieuw)
        n += 1
    return n


# ============================================================
# Regels met de hand toevoegen of verwijderen
# ============================================================
# Voor een wedstrijd zonder online tijdschema, of een onderdeel dat ontbreekt. Een volgende
# import vervangt het hele tijdschema, dus ook deze regels.

@dataclass
class NieuweRegel:
    """Wat in het formulier 'Regel toevoegen' staat (als tekst, zoals getypt)."""
    dag: str = ""
    tijd: str = ""
    onderdeel_id: str = ""             # keuze uit de lijst, of ...
    onderdeel_tekst: str = ""          # ... een eigen naam
    categorie: str = ""
    ronde: str = ""
    groep: str = ""
    duur: str = ""
    opmerking: str = ""

    @classmethod
    def van(cls, formulier) -> "NieuweRegel":
        return cls(**{v: (formulier.get(f"nieuw-{v}") or "").strip() for v in cls.__dataclass_fields__})


def regel_toevoegen(db: Opslag, wedstrijd_id: int, invoer: NieuweRegel) -> ProgrammaOnderdeel:
    """Controleer het formulier en voeg de regel toe; OpslagFout met een leesbare tekst bij een fout."""
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    try:
        datum = date.fromisoformat(invoer.dag) if invoer.dag else w.datum
    except ValueError:
        raise OpslagFout("Kies een geldige dag.") from None
    if not invoer.tijd:
        raise OpslagFout("Vul een starttijd in.")
    onderdeel_id = None
    if invoer.onderdeel_id:
        if not invoer.onderdeel_id.isdigit() or db.onderdeel(int(invoer.onderdeel_id)) is None:
            raise OpslagFout("Kies een onderdeel uit de lijst.")
        onderdeel_id = int(invoer.onderdeel_id)
    if onderdeel_id is None and not invoer.onderdeel_tekst:
        raise OpslagFout("Kies een onderdeel uit de lijst of typ de naam.")
    if invoer.groep and not invoer.groep.isdigit():
        raise OpslagFout("Groep is een nummer: 1, 2, 3, ...")
    if invoer.duur and not invoer.duur.isdigit():
        raise OpslagFout("De duur is een aantal minuten (of leeg).")
    try:
        regel = ProgrammaOnderdeel(
            wedstrijd_id, datum, invoer.tijd, onderdeel_id, invoer.onderdeel_tekst or None,
            invoer.categorie or None, invoer.ronde, int(invoer.groep) if invoer.groep else None,
            int(invoer.duur) if invoer.duur else None, invoer.opmerking or None)
    except ValueError as e:
        raise OpslagFout(str(e)) from None
    return db.programma_opslaan(regel)


def regel_verwijderen(db: Opslag, wedstrijd_id: int, regel_id: int) -> ProgrammaOnderdeel:
    """Verwijder één regel van dit tijdschema; geeft de verwijderde regel. OpslagFout als hij er niet is."""
    regel = db.programma_regel(regel_id)
    if regel is None or regel.wedstrijd_id != wedstrijd_id:
        raise OpslagFout("Deze regel staat niet (meer) in het tijdschema.")
    db.programma_verwijderen(regel_id)
    return regel


# ============================================================
# Een wedstrijd kiezen om één atleet in te schrijven
# ============================================================
# Vanaf de wedstrijdplanning van een atleet ('+ Inschrijven'): kies een komende
# wedstrijd uit de lijst (of maak een nieuwe); daarna het gewone inschrijfformulier
# van die wedstrijd, met deze atleet al aangevinkt.

@dataclass
class KeuzeWedstrijd:
    wedstrijd: Wedstrijd
    dagen_tot: int
    ingeschreven: bool                 # staat al op de deelnemerslijst
    onderdelen: list[str]              # waarvoor al ingeschreven ([] + ingeschreven = volgen nog)
    heeft_tijdschema: bool

    @property
    def zoektekst(self) -> str:
        w = self.wedstrijd
        return " ".join(x for x in (w.naam, w.locatie or "", w.datum.isoformat(), *self.onderdelen)).lower()


@dataclass
class WedstrijdKeuze:
    atleet: Atleet
    categorie: str | None              # 'U16V' vandaag
    wedstrijden: list[KeuzeWedstrijd]  # komende wedstrijden (vandaag meegerekend), vroegste eerst


def wedstrijdkeuze(db: Opslag, master_id: str, peildatum: date | None = None) -> WedstrijdKeuze | None:
    """Komende wedstrijden om de atleet voor in te schrijven; None als de atleet niet bestaat."""
    a = db.atleet(master_id)
    if a is None:
        return None
    vandaag = peildatum or date.today()
    namen = {o.id: o.naam for o in db.onderdelen()}
    per_wedstrijd: dict[int, list[str]] = {}
    for i in db.inschrijvingen(master_id):
        lijst = per_wedstrijd.setdefault(i.wedstrijd_id, [])
        if i.onderdeel_id is not None and i.onderdeel_id in namen:
            lijst.append(namen[i.onderdeel_id])
    rijen = []
    for w in db.wedstrijden(van=vandaag):
        rijen.append(KeuzeWedstrijd(w, (w.datum - vandaag).days, w.id in per_wedstrijd,
                                    sorted(per_wedstrijd.get(w.id, []), key=str.lower),
                                    bool(db.programma(w.id))))
    rijen.sort(key=lambda r: (r.wedstrijd.datum, r.wedstrijd.naam.lower()))
    return WedstrijdKeuze(a, _code(a, vandaag), rijen)
