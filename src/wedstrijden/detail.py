"""De pagina van één wedstrijd: tijdschema met deelnemers, en atleten inschrijven.

    d = wedstrijd_detail(db, wedstrijd_id)          # voor ui/templates/wedstrijd.html
    f = inschrijfformulier(db, wedstrijd_id, regel_id=12)
    aantal = inschrijven_uit_formulier(db, wedstrijd_id, ["<master_id>", ...], [3, 7])

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

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from atleten.landingspagina import categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
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
        """'10:30–10:50', of '10:30' zonder duur."""
        r = self.regel
        return f"{r.starttijd}–{r.eindtijd}" if r.eindtijd else r.starttijd

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
class WedstrijdDetail:
    wedstrijd: Wedstrijd
    dagen: list[TijdschemaDag]
    deelnemers: list[Deelnemer]
    botsingen: list[chronoloog.Botsing]
    dagen_tot: int                            # 0 = vandaag, negatief = geweest

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


def _sorteer(a: Atleet) -> tuple[str, str]:
    return a.achternaam.lower(), a.voornaam.lower()


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
                           (w.datum - vandaag).days)


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
