"""Een ploeg op de wedstrijdpagina zetten: inschrijvingen in prestaties.db bijwerken.

Is een ploeg aan een wedstrijd gekoppeld, dan schrijft opslaan de opstelling ook
in voor die wedstrijd (tabel `inschrijving`), zodat de wedstrijdpagina, het
persoonlijk schema en de botsingencontrole (wedstrijden/chronoloog.py) de ploeg
kennen. Een lid zonder onderdeel (bijv. een reserve) staat erop als 'gaat mee,
onderdelen volgen nog'.

Alleen wat de ploeg zelf veranderde, wordt aangepast: `synchroniseer()` krijgt
de oude en de nieuwe opstelling en meldt af wat uit de ploeg is gehaald.
Inschrijvingen die de trainer met de hand op de wedstrijdpagina maakte voor
andere onderdelen, blijven staan.

Onderdelen worden gezocht op naam + specificatie (zoals in de matrix,
`vergelijk.normaliseer`); bestaat er nog geen, dan wordt het aangemaakt, net als
bij een import van atletiek.nu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from atleten.importeer_atletieknu import eenheid_van
from db.queries import Opslag
from models import Inschrijving, Inzet, Onderdeel, Ploeg, PloegLid
from ploeg.regels import Regelset
from ploeg.vergelijk import categorie_op, normaliseer
from wedstrijden import planning

#: master_id -> namen van de onderdelen (leeg = gaat mee, onderdelen volgen nog)
Gewenst = dict[str, set[str]]


@dataclass(slots=True)
class Wijzigingen:
    ingeschreven: int = 0           # nieuwe inschrijvingen (atleet + onderdeel, of 'gaat mee')
    afgemeld: int = 0

    @property
    def iets(self) -> bool:
        return bool(self.ingeschreven or self.afgemeld)


def gewenst(db: Opslag, regelset: Regelset, ploeg: Ploeg, leden: Iterable[PloegLid],
            inzet: Iterable[Inzet]) -> Gewenst:
    """Welke inschrijvingen bij deze opstelling horen."""
    uit: Gewenst = {lid.atleet_id: set() for lid in leden}
    for i in inzet:
        if i.atleet_id not in uit or i.onderdeel not in regelset.onderdelen:
            continue
        a = db.atleet(i.atleet_id)
        cat = categorie_op(a, ploeg.datum, regelset) if a else None
        uit[i.atleet_id].add(regelset.onderdeel_naam(ploeg.categorie, i.onderdeel, cat or ploeg.categorie))
    return uit


def _onderdeel_id(db: Opslag, naam: str, bekend: dict[str, int]) -> int:
    """Id van het onderdeel met deze naam (genormaliseerd), of een nieuw onderdeel."""
    sleutel = normaliseer(naam)
    if sleutel not in bekend:
        eenheid = eenheid_van(naam)
        o = db.onderdeel_opslaan(Onderdeel(naam, eenheid, lager_is_beter=(eenheid == "tijd")))
        bekend[sleutel] = o.id
    return bekend[sleutel]


def synchroniseer(db: Opslag, ploeg: Ploeg, oud: Gewenst, nieuw: Gewenst) -> Wijzigingen:
    """Inschrijvingen voor de gekoppelde wedstrijd van `oud` naar `nieuw` brengen."""
    w = Wijzigingen()
    if ploeg.wedstrijd_id is None or db.wedstrijd(ploeg.wedstrijd_id) is None:
        return w
    wid = ploeg.wedstrijd_id
    bekend = {normaliseer(o.naam): o.id for o in db.onderdelen()}

    def huidig(m: str) -> list[Inschrijving]:
        return [i for i in db.inschrijvingen(m) if i.wedstrijd_id == wid]

    # uit de ploeg of van een onderdeel gehaald: afmelden (alleen wat de ploeg had)
    for m, namen in oud.items():
        weg = namen - nieuw.get(m, set())
        for naam in weg:
            oid = bekend.get(normaliseer(naam))
            if oid is not None and any(i.onderdeel_id == oid for i in huidig(m)):
                planning.afmelden(db, wid, m, oid)
                w.afgemeld += 1
        regels = huidig(m)
        if m not in nieuw and regels and all(i.onderdeel_id is None for i in regels):
            planning.afmelden(db, wid, m)                       # alleen 'gaat mee' van de ploeg
            w.afgemeld += 1

    # erbij: inschrijven
    for m, namen in nieuw.items():
        voor = {(i.onderdeel_id) for i in huidig(m)}
        ids = [_onderdeel_id(db, n, bekend) for n in sorted(namen)]
        planning.inschrijven(db, wid, m, ids)
        na = {(i.onderdeel_id) for i in huidig(m)}
        w.ingeschreven += len(na - voor)
    return w
