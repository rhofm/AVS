"""Komende wedstrijden plannen: datum, naam, locatie, link, en wie met welke onderdelen meedoet.

Gebruikt de bestaande tabellen in prestaties.db:
  * `wedstrijd`    - één rij per wedstrijd (naam, datum, locatie, link = bron_url, indoor);
  * `inschrijving` - één rij per atleet per onderdeel (onder het pseudoniem).

Een geplande wedstrijd en de uitslag ervan zijn dus dezelfde rij: importeer je
later de uitslag via dezelfde link, dan komen de prestaties bij deze wedstrijd.
Daarvoor wordt de link genormaliseerd (zie normaliseer_link): een atletiek.nu-
link naar de hoofdpagina, inschrijvingen of uitslagen wijst naar dezelfde wedstrijd.

Werkwijze:
    w = plan_wedstrijd(db, "Clubkampioenschappen", date(2027, 5, 15), locatie="Nijmegen",
                       link="https://www.atletiek.nu/wedstrijd/main/45678/")
    inschrijven(db, w.id, anna.master_id, ["100m", "Verspringen"])
    for o in komende_wedstrijden(db):
        print(o.wedstrijd.naam, o.aantal_deelnemers)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from db.queries import Opslag, OpslagFout
from models import Inschrijving, Wedstrijd

_ATLETIEKNU_RE = re.compile(r"atletiek\.nu/wedstrijd/[a-z]+/(\d+)", re.I)


# ============================================================
# Links
# ============================================================
def normaliseer_link(link: str | None) -> str | None:
    """Eén vaste vorm per wedstrijd, zodat planning en latere import dezelfde rij vinden.

    atletiek.nu: elke wedstrijdpagina (/main/, /inschrijvingen/, /uitslagen/, ...)
    wordt https://www.atletiek.nu/wedstrijd/uitslagen/<id>/. Andere links blijven
    zoals ze zijn, zonder spaties en #anker.
    """
    if link is None or not link.strip():
        return None
    link = link.strip().split("#", 1)[0]
    m = _ATLETIEKNU_RE.search(link)
    if m:
        return f"https://www.atletiek.nu/wedstrijd/uitslagen/{m.group(1)}/"
    return link


def bron_uit_link(link: str | None) -> str:
    """'atletieknu', 'seltec' of 'handmatig' (zonder of met een onbekende link)."""
    tekst = (link or "").lower()
    if "atletiek.nu" in tekst:
        return "atletieknu"
    if "seltec" in tekst or "uitslagen.atletiek.nl" in tekst:
        return "seltec"
    return "handmatig"


# ============================================================
# Wedstrijden
# ============================================================
def plan_wedstrijd(db: Opslag, naam: str, datum: date, locatie: str | None = None,
                   link: str | None = None, indoor: bool = False) -> Wedstrijd:
    """Nieuwe geplande wedstrijd, of de bestaande bijwerken als de link al bekend is."""
    if not naam.strip():
        raise OpslagFout("Een wedstrijd heeft een naam nodig.")
    link = normaliseer_link(link)
    w = Wedstrijd(naam=naam.strip(), datum=datum, locatie=locatie, bron=bron_uit_link(link),
                  bron_url=link, indoor=indoor)
    return db.wedstrijd_opslaan(w)   # hergebruikt een wedstrijd met dezelfde bron_url


def wedstrijd_afgelast(db: Opslag, wedstrijd_id: int) -> None:
    """Haal een geplande wedstrijd en alle inschrijvingen weg (niet als er al uitslagen zijn)."""
    db.wedstrijd_verwijderen(wedstrijd_id)


# ============================================================
# Inschrijven en afmelden
# ============================================================
def _onderdeel_id(db: Opslag, onderdeel: str | int) -> int:
    o = db.onderdeel(onderdeel)
    if o is None:
        raise OpslagFout(f"Onbekend onderdeel {onderdeel!r}; voeg het eerst toe met onderdeel_opslaan().")
    return o.id


def inschrijven(db: Opslag, wedstrijd_id: int, master_id: str,
                onderdelen: Iterable[str | int] = ()) -> list[Inschrijving]:
    """Zet een atleet op de deelnemerslijst, per onderdeel (naam of id).

    Zonder onderdelen: de atleet gaat mee, onderdelen volgen later. Worden die
    later toegevoegd, dan verdwijnt de regel 'onderdeel nog onbekend'.
    Geeft alle inschrijvingen van deze atleet voor deze wedstrijd terug.
    """
    if db.wedstrijd(wedstrijd_id) is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    if db.atleet(master_id) is None:
        raise OpslagFout(f"Atleet {master_id} bestaat niet.")
    ids = [_onderdeel_id(db, o) for o in onderdelen]   # eerst alles controleren, dan pas opslaan

    if ids:
        if _alleen_onbekend(db, wedstrijd_id, master_id):
            db.inschrijving_verwijderen(Inschrijving(master_id, wedstrijd_id, None))
        for oid in ids:
            db.inschrijving_opslaan(Inschrijving(master_id, wedstrijd_id, oid))
    elif not _van_atleet(db, wedstrijd_id, master_id):
        db.inschrijving_opslaan(Inschrijving(master_id, wedstrijd_id, None))
    return _van_atleet(db, wedstrijd_id, master_id)


def afmelden(db: Opslag, wedstrijd_id: int, master_id: str, onderdeel: str | int | None = None) -> None:
    """Afmelden voor één onderdeel, of zonder onderdeel voor de hele wedstrijd."""
    oid = None if onderdeel is None else _onderdeel_id(db, onderdeel)
    db.inschrijving_verwijderen(Inschrijving(master_id, wedstrijd_id, oid))


def _van_atleet(db: Opslag, wedstrijd_id: int, master_id: str) -> list[Inschrijving]:
    return [i for i in db.inschrijvingen(master_id) if i.wedstrijd_id == wedstrijd_id]


def _alleen_onbekend(db: Opslag, wedstrijd_id: int, master_id: str) -> bool:
    regels = _van_atleet(db, wedstrijd_id, master_id)
    return bool(regels) and all(i.onderdeel_id is None for i in regels)


# ============================================================
# Overzichten
# ============================================================
@dataclass
class WedstrijdOverzicht:
    """Eén wedstrijd met de deelnemers: master_id -> onderdeelnamen ([] = nog onbekend)."""
    wedstrijd: Wedstrijd
    deelnemers: dict[str, list[str]] = field(default_factory=dict)

    @property
    def aantal_deelnemers(self) -> int:
        return len(self.deelnemers)

    @property
    def link(self) -> str | None:
        return self.wedstrijd.bron_url

    def per_onderdeel(self) -> dict[str, list[str]]:
        """Onderdeelnaam -> master_ids, bijv. voor het maken van een ploeg."""
        uit: dict[str, list[str]] = {}
        for master_id, onderdelen in self.deelnemers.items():
            for o in onderdelen:
                uit.setdefault(o, []).append(master_id)
        return dict(sorted(uit.items()))


def overzicht(db: Opslag, wedstrijd_id: int) -> WedstrijdOverzicht:
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    namen = {o.id: o.naam for o in db.onderdelen()}
    volgorde = {m.master_id: n for n, m in enumerate(db.atleten(alleen_actief=False))}  # op achternaam
    deelnemers: dict[str, list[str]] = {}
    for i in db.deelnemers(wedstrijd_id):
        lijst = deelnemers.setdefault(i.atleet_id, [])
        if i.onderdeel_id is not None:
            lijst.append(namen[i.onderdeel_id])
    deelnemers = {m: sorted(o) for m, o in sorted(deelnemers.items(), key=lambda kv: volgorde.get(kv[0], 0))}
    return WedstrijdOverzicht(w, deelnemers)


def komende_wedstrijden(db: Opslag, vanaf: date | None = None, tot: date | None = None) -> list[WedstrijdOverzicht]:
    """Alle wedstrijden vanaf vandaag (of `vanaf`), vroegste eerst, met deelnemers."""
    return [overzicht(db, w.id) for w in db.wedstrijden(van=vanaf or date.today(), tot=tot)]
