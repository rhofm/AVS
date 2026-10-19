"""Doelen van een groep of atleet: overzicht, status per regel, invullen.

Een doel (models/doel.py) heeft een titel, meestal een wedstrijd, een
streefdatum (standaard de wedstrijddatum) en regels: wat precies, voor wie.

Status van een regel (uitgerekend, nooit opgeslagen)
----------------------------------------------------
1. Beoordeling met de hand -> die.
2. 'prestatie': de beste windlegale prestatie van de atleet op dat onderdeel in
   het venster (bij een wedstrijd: alleen op die wedstrijd; anders van startdatum
   tot streefdatum) haalt de streefwaarde -> behaald. Of lager beter is, komt van
   het onderdeel.
3. 'leerdoel': de laatste score tot en met de streefdatum is minstens de
   streefwaarde -> behaald.
4. Anders: streefdatum voorbij -> niet behaald (een wedstrijddoel zonder uitslag
   en regels zonder automatische controle: 'te beoordelen'); daarvoor -> open.

Invullen
--------
Kop: titel, wedstrijd of streefdatum, startdatum, beschrijving, evaluatie.
Regels als genummerde velden (regel-<i>-atleet, -soort, -onderdeel, -leerdoel,
-streef, -omschrijving, -beoordeling). Een regel zonder streefwaarde,
omschrijving en beoordeling telt niet mee. 'Aanvullen uit inschrijvingen'
maakt een regel per ingeschreven atleet en onderdeel van de gekozen wedstrijd,
met het PR erbij als houvast; de trainer vult alleen de streefwaarden in.

Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Mapping

from atleten.prestaties import lees_waarde, toon_waarde
from db.queries import Opslag, OpslagFout
from models import BEOORDELINGEN, DOELSOORTEN, STATUSSEN, Atleet, Doel, DoelRegel, Groep, Onderdeel, Wedstrijd

LEGE_REGELS = 3
WEDSTRIJDEN_TERUG = 60                # dagen: zo ver terug staan wedstrijden in de keuzelijst
GEWEEST_OP_ATLEETPAGINA = 3           # zoveel afgelopen doelen op de atleetpagina


# ============================================================
# Status
# ============================================================
@dataclass
class RegelStand:
    regel: DoelRegel
    atleet: Atleet | None             # None = de hele groep
    wat: str                          # '100m ≤ 12,80', 'HRD-U14-02: score ≥ 4', of de omschrijving
    status: str                       # een van STATUSSEN
    resultaat: str | None = None      # '12,74' of 'score 4', als er iets is
    resultaat_datum: date | None = None
    uitleg: str | None = None         # bijv. 'nog geen uitslag'

    @property
    def status_tekst(self) -> str:
        return STATUSSEN[self.status]

    @property
    def wie(self) -> str:
        return self.atleet.naam if self.atleet else "Hele groep"


@dataclass
class DoelStand:
    doel: Doel
    einde: date                       # streefdatum (eigen datum of die van de wedstrijd)
    wedstrijd: Wedstrijd | None
    groep: Groep | None
    standen: list[RegelStand]
    vandaag: date

    @property
    def dagen_tot(self) -> int:
        return (self.einde - self.vandaag).days

    @property
    def geweest(self) -> bool:
        return self.einde < self.vandaag

    @property
    def behaald(self) -> int:
        return sum(1 for s in self.standen if s.status == "behaald")

    @property
    def telling(self) -> dict[str, int]:
        uit = {s: 0 for s in STATUSSEN}
        for s in self.standen:
            uit[s.status] += 1
        return uit


class _Cache:
    """Onderdelen, leerdoelen, atleten en wedstrijden één keer ophalen."""

    def __init__(self, db: Opslag) -> None:
        self.db = db
        self._o: dict[int, Onderdeel | None] = {}
        self._a: dict[str, Atleet | None] = {}
        self._w: dict[int, Wedstrijd | None] = {}
        self._l: dict[str, object] = {}

    def onderdeel(self, i: int) -> Onderdeel | None:
        if i not in self._o:
            self._o[i] = self.db.onderdeel(i)
        return self._o[i]

    def atleet(self, m: str) -> Atleet | None:
        if m not in self._a:
            self._a[m] = self.db.atleet(m)
        return self._a[m]

    def wedstrijd(self, i: int | None) -> Wedstrijd | None:
        if i is None:
            return None
        if i not in self._w:
            self._w[i] = self.db.wedstrijd(i)
        return self._w[i]

    def leerdoel(self, i: str):
        if i not in self._l:
            self._l[i] = self.db.leerdoel(i)
        return self._l[i]


def einddatum(db: Opslag, d: Doel, cache: _Cache | None = None) -> date:
    w = (cache or _Cache(db)).wedstrijd(d.wedstrijd_id)
    return d.datum or (w.datum if w else None) or d.startdatum or date.today()


def _wat(c: _Cache, r: DoelRegel) -> str:
    if r.soort == "prestatie":
        o = c.onderdeel(r.onderdeel_id)
        if o is None:
            return "onbekend onderdeel"
        tekst = f"{o.naam} {'≤' if o.lager_is_beter else '≥'} {toon_waarde(r.streefwaarde, o.eenheid)}"
    elif r.soort == "leerdoel":
        ld = c.leerdoel(r.leerdoel_id)
        tekst = f"{r.leerdoel_id}: score ≥ {int(r.streefwaarde)}"
        if ld is not None:
            oms = ld.omschrijving if len(ld.omschrijving) <= 70 else ld.omschrijving[:67] + "…"
            tekst += f" ({oms})"
    else:
        return r.omschrijving or ""
    return f"{tekst} – {r.omschrijving}" if r.omschrijving else tekst


def _stand(db: Opslag, c: _Cache, d: Doel, einde: date, r: DoelRegel, vandaag: date) -> RegelStand:
    atleet = c.atleet(r.atleet_id) if r.atleet_id else None
    stand = RegelStand(r, atleet, _wat(c, r), "open")
    voorbij = einde < vandaag
    automatisch = r.atleet_id is not None and r.soort in ("prestatie", "leerdoel")
    if automatisch and r.soort == "prestatie":
        o = c.onderdeel(r.onderdeel_id)
        prestaties = [p for p in db.prestaties(r.atleet_id, r.onderdeel_id) if o is not None and o.windlegaal(p.wind, p.indoor)]
        if d.wedstrijd_id is not None:
            prestaties = [p for p in prestaties if p.wedstrijd_id == d.wedstrijd_id]
        else:
            prestaties = [p for p in prestaties if (d.startdatum or einde) <= p.datum <= einde]
        if prestaties and o is not None:
            beste = o.beste(p.waarde for p in prestaties)
            p = next(p for p in prestaties if p.waarde == beste)
            stand.resultaat, stand.resultaat_datum = toon_waarde(beste, o.eenheid), p.datum
            gehaald = beste <= r.streefwaarde if o.lager_is_beter else beste >= r.streefwaarde
            stand.status = "behaald" if gehaald else ("niet" if voorbij else "open")
        elif voorbij:
            stand.status = "te_beoordelen" if d.wedstrijd_id is not None else "niet"
            stand.uitleg = "nog geen uitslag" if d.wedstrijd_id is not None else "geen prestatie in deze periode"
    elif automatisch and r.soort == "leerdoel":
        scores = [s for s in db.leerdoelscores(r.atleet_id, r.leerdoel_id) if s.datum <= einde]
        if scores:
            laatste = scores[-1]
            stand.resultaat, stand.resultaat_datum = f"score {laatste.score}", laatste.datum
            stand.status = "behaald" if laatste.score >= r.streefwaarde else ("niet" if voorbij else "open")
        elif voorbij:
            stand.status, stand.uitleg = "niet", "nog niet beoordeeld"
    elif voorbij:
        stand.status = "te_beoordelen"
    if r.beoordeling:
        stand.status = r.beoordeling
    return stand


def doelstand(db: Opslag, d: Doel, *, vandaag: date | None = None, alleen_atleet: str | None = None,
              cache: _Cache | None = None) -> DoelStand:
    vandaag = vandaag or date.today()
    c = cache or _Cache(db)
    einde = einddatum(db, d, c)
    regels = [r for r in d.regels if alleen_atleet is None or r.atleet_id == alleen_atleet]
    standen = [_stand(db, c, d, einde, r, vandaag) for r in regels]
    return DoelStand(d, einde, c.wedstrijd(d.wedstrijd_id), db.groep(d.groep_id) if d.groep_id else None,
                     standen, vandaag)


@dataclass
class Doelenoverzicht:
    groep: Groep
    komend: list[DoelStand]           # vroegste eerst
    geweest: list[DoelStand]          # nieuwste eerst


def doelenoverzicht(db: Opslag, groep_id: int, *, vandaag: date | None = None) -> Doelenoverzicht | None:
    groep = db.groep(groep_id)
    if groep is None:
        return None
    c = _Cache(db)
    alle = [doelstand(db, d, vandaag=vandaag, cache=c) for d in db.doelen_van_groep(groep_id)]
    return Doelenoverzicht(groep, [s for s in alle if not s.geweest],
                           sorted((s for s in alle if s.geweest), key=lambda s: s.einde, reverse=True))


def doelen_van_atleet(db: Opslag, master_id: str, *, vandaag: date | None = None) -> list[DoelStand]:
    """De doelen van één atleet (alleen zijn eigen regels): alle komende en de laatste afgelopen."""
    c = _Cache(db)
    alle = [doelstand(db, d, vandaag=vandaag, alleen_atleet=master_id, cache=c) for d in db.doelen_van_atleet(master_id)]
    komend = [s for s in alle if not s.geweest]
    geweest = sorted((s for s in alle if s.geweest), key=lambda s: s.einde, reverse=True)[:GEWEEST_OP_ATLEETPAGINA]
    return komend + geweest


def wedstrijddoelen(db: Opslag, wedstrijd_id: int, *, vandaag: date | None = None) -> list[DoelStand]:
    c = _Cache(db)
    return [doelstand(db, d, vandaag=vandaag, cache=c) for d in db.doelen_van_wedstrijd(wedstrijd_id)]


def markeringen(db: Opslag, groep_id: int) -> list[tuple[date, str]]:
    """(streefdatum, titel) van de doelen van een groep, voor het jaaroverzicht."""
    c = _Cache(db)
    return [(einddatum(db, d, c), d.titel) for d in db.doelen_van_groep(groep_id)]


# ============================================================
# Invullen
# ============================================================
@dataclass
class Formregel:
    atleet: str = ""                  # master_id; '' = hele groep
    soort: str = "prestatie"
    onderdeel: str = ""               # id als tekst
    leerdoel: str = ""
    streef: str = ""                  # zoals getypt ('12,80', '2:05,00', '4')
    omschrijving: str = ""
    beoordeling: str = ""
    pr: str | None = None             # PR van de atleet op dat onderdeel, als houvast

    @property
    def leeg(self) -> bool:
        return not (self.streef.strip() or self.omschrijving.strip() or self.beoordeling)


@dataclass
class Doelformulier:
    groep: Groep | None               # None = persoonlijk doel
    atleet: Atleet | None             # bij een persoonlijk doel
    doel: Doel | None                 # bestaand doel (bewerken) of None (nieuw)
    waarden: dict[str, str]
    regels: list[Formregel]
    atleten: list[Atleet]             # keuze per regel (leden van de groep)
    onderdelen: list[Onderdeel]
    leerdoelen: list                  # models.Leerdoel, voor de keuzelijst
    wedstrijden: list[Wedstrijd]
    melding: str | None = None

    @property
    def soorten(self) -> list[tuple[str, str]]:
        return list(DOELSOORTEN.items())

    @property
    def beoordelingen(self) -> list[tuple[str, str]]:
        return list(BEOORDELINGEN.items())

    @property
    def nieuw(self) -> bool:
        return self.doel is None

    @property
    def persoonlijk(self) -> bool:
        return self.groep is None


def _streef_tekst(c: _Cache, r: DoelRegel) -> str:
    if r.streefwaarde is None:
        return ""
    if r.soort == "leerdoel":
        return str(int(r.streefwaarde))
    o = c.onderdeel(r.onderdeel_id) if r.onderdeel_id else None
    return toon_waarde(r.streefwaarde, o.eenheid).removesuffix(" m").removesuffix(" pnt") if o else str(r.streefwaarde)


def _prs(db: Opslag, master_ids) -> dict[tuple[str, int], float]:
    return {(p.atleet_id, p.onderdeel_id): p.waarde for m in set(master_ids) if m for p in db.prs(m)}


def _met_pr(db: Opslag, c: _Cache, regels: list[Formregel]) -> list[Formregel]:
    prs = _prs(db, [r.atleet for r in regels])
    for r in regels:
        if r.atleet and r.onderdeel.isdigit():
            w, o = prs.get((r.atleet, int(r.onderdeel))), c.onderdeel(int(r.onderdeel))
            r.pr = toon_waarde(w, o.eenheid) if w is not None and o else None
    return regels


def _regels_uit(formulier: Mapping[str, str]) -> list[Formregel]:
    nummers = sorted({int(k.split("-")[1]) for k in formulier if k.startswith("regel-") and k.split("-")[1].isdigit()})
    uit = []
    for i in nummers:
        def v(naam):
            return str(formulier.get(f"regel-{i}-{naam}", "") or "").strip()
        uit.append(Formregel(v("atleet"), v("soort") or "prestatie", v("onderdeel"), v("leerdoel").upper(),
                             v("streef"), v("omschrijving"), v("beoordeling")))
    return uit


def _wedstrijdkeuze(db: Opslag, huidig: int | None, vandaag: date) -> list[Wedstrijd]:
    lijst = db.wedstrijden(van=vandaag - timedelta(days=WEDSTRIJDEN_TERUG))
    if huidig and all(w.id != huidig for w in lijst):
        w = db.wedstrijd(huidig)
        if w:
            lijst.insert(0, w)
    return lijst


def doelformulier(db: Opslag, *, groep_id: int | None = None, master_id: str | None = None,
                  doel_id: int | None = None, ingevuld: Mapping[str, str] | None = None,
                  vandaag: date | None = None) -> Doelformulier | None:
    """Formulier voor een nieuw doel (groep of persoonlijk) of een bestaand doel, of na een fout met wat er stond."""
    vandaag = vandaag or date.today()
    c = _Cache(db)
    doel = None
    if doel_id is not None:
        doel = db.doel(doel_id)
        if doel is None:
            return None
        groep_id = doel.groep_id
        if doel.persoonlijk:
            master_id = doel.regels[0].atleet_id if doel.regels else None
    groep = db.groep(groep_id) if groep_id is not None else None
    atleet = db.atleet(master_id) if master_id else None
    if (groep_id is not None and groep is None) or (groep is None and atleet is None):
        return None
    if ingevuld is not None:
        waarden = {k: str(ingevuld.get(k, "") or "") for k in
                   ("titel", "wedstrijd", "startdatum", "datum", "beschrijving", "evaluatie")}
        regels = [r for r in _regels_uit(ingevuld) if not r.leeg or r.atleet or r.onderdeel or r.leerdoel]
    elif doel is not None:
        waarden = {"titel": doel.titel, "wedstrijd": str(doel.wedstrijd_id or ""),
                   "startdatum": doel.startdatum.isoformat() if doel.startdatum else "",
                   "datum": doel.datum.isoformat() if doel.datum else "",
                   "beschrijving": doel.beschrijving or "", "evaluatie": doel.evaluatie or ""}
        regels = [Formregel(r.atleet_id or "", r.soort, str(r.onderdeel_id or ""), r.leerdoel_id or "",
                            _streef_tekst(c, r), r.omschrijving or "", r.beoordeling or "") for r in doel.regels]
    else:
        waarden = {"titel": "", "wedstrijd": "", "startdatum": vandaag.isoformat(), "datum": "",
                   "beschrijving": "", "evaluatie": ""}
        regels = []
    if atleet is not None:
        for r in regels:
            r.atleet = atleet.master_id
    leeg = Formregel(atleet.master_id if atleet else "")
    regels = _met_pr(db, c, regels) + [Formregel(leeg.atleet) for _ in range(LEGE_REGELS)]
    atleten = [a for a in (db.atleet(m) for m in groep.leden) if a] if groep else [atleet]
    # Atleten die al in het doel staan maar de groep verlieten, blijven kiesbaar.
    for r in regels:
        if r.atleet and all(a.master_id != r.atleet for a in atleten):
            a = db.atleet(r.atleet)
            if a:
                atleten.append(a)
    huidig = int(waarden["wedstrijd"]) if waarden["wedstrijd"].isdigit() else None
    return Doelformulier(groep, atleet, doel, waarden, regels, atleten, db.onderdelen(), db.leerdoelen(),
                         _wedstrijdkeuze(db, huidig, vandaag))


def aanvullen(db: Opslag, f: Doelformulier) -> Doelformulier:
    """Voeg een regel toe per ingeschreven atleet (van de groep, of de atleet zelf) en onderdeel
    van de gekozen wedstrijd die er nog niet staat. De trainer vult de streefwaarden in."""
    wid = f.waarden.get("wedstrijd", "")
    if not wid.isdigit() or db.wedstrijd(int(wid)) is None:
        f.melding = "Kies eerst een wedstrijd; dan kunnen de inschrijvingen worden overgenomen."
        return f
    toegestaan = {a.master_id for a in f.atleten}
    ingevuld = [r for r in f.regels if not (r.leeg and not r.onderdeel and not r.leerdoel)]
    al = {(r.atleet, r.onderdeel) for r in ingevuld}
    nieuw = []
    for i in db.deelnemers(int(wid)):
        if i.onderdeel_id is None or i.atleet_id not in toegestaan or (i.atleet_id, str(i.onderdeel_id)) in al:
            continue
        nieuw.append(Formregel(i.atleet_id, "prestatie", str(i.onderdeel_id)))
        al.add((i.atleet_id, str(i.onderdeel_id)))
    namen = {a.master_id: a.naam for a in f.atleten}
    nieuw.sort(key=lambda r: (namen.get(r.atleet, ""), r.onderdeel))
    leeg = f.atleet.master_id if f.atleet else ""
    f.regels = _met_pr(db, _Cache(db), ingevuld + nieuw) + [Formregel(leeg) for _ in range(LEGE_REGELS)]
    f.melding = (f"{len(nieuw)} {'regels' if len(nieuw) != 1 else 'regel'} toegevoegd uit de inschrijvingen. "
                 "Vul de streefwaarden in; regels zonder streefwaarde worden niet opgeslagen."
                 if nieuw else "Geen nieuwe inschrijvingen (met onderdeel) gevonden voor deze wedstrijd.")
    return f


def _datum(tekst: str, wat: str) -> date | None:
    tekst = str(tekst or "").strip()
    if not tekst:
        return None
    try:
        return date.fromisoformat(tekst)
    except ValueError:
        raise OpslagFout(f"{wat}: kies een geldige datum.") from None


def _lees_regel(db: Opslag, c: _Cache, n: int, r: Formregel, persoonlijk_van: str | None) -> DoelRegel:
    wat = f"Regel {n}"
    if r.soort not in DOELSOORTEN:
        raise OpslagFout(f"{wat}: kies een soort doel.")
    atleet = persoonlijk_van or (r.atleet or None)
    streef = None
    onderdeel = int(r.onderdeel) if r.soort == "prestatie" and r.onderdeel.isdigit() else None
    if r.soort == "prestatie":
        o = c.onderdeel(onderdeel) if onderdeel else None
        if o is None:
            raise OpslagFout(f"{wat}: kies een onderdeel.")
        if not r.streef:
            raise OpslagFout(f"{wat}: vul een streefwaarde in (bijv. 12,80 of 2:05,00).")
        try:
            streef = lees_waarde(r.streef, o.eenheid)
        except ValueError as e:
            raise OpslagFout(f"{wat}: {e}") from None
    elif r.soort == "leerdoel":
        if not r.leerdoel or c.leerdoel(r.leerdoel) is None:
            raise OpslagFout(f"{wat}: kies een bestaand leerdoel (bijv. SPR-U14-02).")
        if not r.streef.isdigit() or not 1 <= int(r.streef) <= 5:
            raise OpslagFout(f"{wat}: de score is 1 tot en met 5.")
        streef = int(r.streef)
    elif not r.omschrijving:
        raise OpslagFout(f"{wat}: beschrijf het doel.")
    if r.beoordeling and r.beoordeling not in BEOORDELINGEN:
        raise OpslagFout(f"{wat}: onbekende beoordeling.")
    try:
        return DoelRegel(r.soort, atleet, onderdeel, r.leerdoel or None, streef, r.omschrijving or None,
                         r.beoordeling or None)
    except ValueError as e:
        raise OpslagFout(f"{wat}: {e}") from None


def opslaan(db: Opslag, formulier: Mapping[str, str], *, groep_id: int | None = None,
            master_id: str | None = None, doel_id: int | None = None) -> Doel:
    """Lees het formulier en sla het doel op (nieuw voor een groep of atleet, of een bestaand doel)."""
    oud = db.doel(doel_id) if doel_id is not None else None
    if doel_id is not None and oud is None:
        raise OpslagFout(f"Doel {doel_id} bestaat niet.")
    if oud is not None:
        groep_id = oud.groep_id
        master_id = oud.regels[0].atleet_id if oud.persoonlijk and oud.regels else None
    if groep_id is None and not master_id:
        raise OpslagFout("Een doel hoort bij een groep of een atleet.")
    c = _Cache(db)
    wid = str(formulier.get("wedstrijd", "") or "").strip()
    regels = [_lees_regel(db, c, n, r, master_id if groep_id is None else None)
              for n, r in enumerate(_regels_uit(formulier), start=1) if not r.leeg]
    if groep_id is None and not regels:
        raise OpslagFout("Vul minstens één regel in: wat wil de atleet bereiken?")
    try:
        d = Doel(formulier.get("titel", ""), groep_id, int(wid) if wid.isdigit() else None,
                 _datum(formulier.get("startdatum"), "Vanaf"), _datum(formulier.get("datum"), "Streefdatum"),
                 formulier.get("beschrijving"), formulier.get("evaluatie"), regels,
                 oud.id if oud else None)
    except ValueError as e:
        raise OpslagFout(str(e)) from None
    return db.doel_opslaan(d)


def verwijderen(db: Opslag, doel_id: int) -> Doel:
    d = db.doel(doel_id)
    if d is None:
        raise OpslagFout(f"Doel {doel_id} bestaat niet.")
    db.doel_verwijderen(doel_id)
    return d
