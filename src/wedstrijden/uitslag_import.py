"""De uitslagen van een gehouden wedstrijd importeren (atletiek.nu of Seltec) in prestaties.db.

    verslag = uitslagen_importeren(db, wedstrijd_id)        # met de link van de wedstrijd zelf
    for t in verslag.te_controleren: ...                     # trainer bevestigt (pagina 'Uitslagen controleren')
    uitslagen_bevestigen(db, wedstrijd_id, {t.sleutel: master_id, ...}, verslag.te_controleren)

Een uitslag bevat iedereen die meedeed, ook atleten van andere clubs. Per persoon
(naam + club op de site) wordt de atleet gezocht met atleten/koppelen.py:
  * zeker (atletiek.nu-id, naam + geboortejaar, naam + club)          -> opgeslagen;
  * de naam past bij precies één atleet die voor deze wedstrijd
    ingeschreven staat                                                  -> opgeslagen;
  * alleen de naam past (en de club spreekt het niet tegen)             -> te controleren;
  * geen atleet met die naam, of de club past niet                      -> overgeslagen.
Namen en clubs van de site worden nooit opgeslagen: alleen de prestatie onder
het pseudoniem van de gekoppelde atleet (CLAUDE.md, privacy).

Onderdelen heten zoals bij de import van een atletiek.nu-profiel
(atleten/importeer_atletieknu.py): naam + specificatie, bijv. '60 meter horden 76,2cm'.
Staat het onderdeel niet in de lijst, dan wordt het (net als daar) aangemaakt.
DNF, DNS, NM en estafetterijen (geen individuele prestatie) worden overgeslagen.

Opnieuw importeren is veilig: prestaties die er al staan, worden herkend
(UNIQUE in prestaties.db) en niet dubbel opgeslagen.

Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from atleten.importeer_atletieknu import eenheid_van, wind_van
from atleten.koppelen import Koppelaar, normaliseer
from db.queries import Opslag, OpslagFout
from importers.atletieknu_wedstrijd import AtletiekNuWedstrijdImporter
from importers.base import Importer, ImportFout
from importers.seltec import SeltecImporter
from models import Atleet, Onderdeel, Prestatie, Wedstrijd

from .planning import bron_uit_link
from .tijdschema_import import zoek_onderdeel


# ============================================================
# Uitkomst
# ============================================================
@dataclass
class TeControleren:
    """Iemand op de uitslag met dezelfde naam als een atleet van ons, maar niet zeker dezelfde."""
    sleutel: str                       # 'p0', 'p1', ... (veldnaam in het formulier)
    naam: str                          # zoals op de site (alleen om te tonen, wordt niet opgeslagen)
    club: str                          # zoals op de site
    kandidaten: list[Atleet]           # atleten van ons met die naam
    prestaties: list[Prestatie]        # nog zonder atleet

    @property
    def samenvatting(self) -> str:
        """'100m, Verspringen' - welke onderdelen deze persoon deed."""
        return ", ".join(dict.fromkeys(p.onderdeel for p in self.prestaties))


@dataclass
class UitslagVerslag:
    wedstrijd_id: int
    gelezen: int = 0                   # regels op de uitslag (alle clubs)
    nieuw: int = 0                     # opgeslagen prestaties
    al_bekend: int = 0                 # stonden er al (eerder geïmporteerd)
    atleten: list[str] = field(default_factory=list)     # namen van onze atleten met een prestatie
    overgeslagen: int = 0              # DNF/DNS/NM e.d. van onze atleten
    nieuwe_onderdelen: list[str] = field(default_factory=list)
    te_controleren: list[TeControleren] = field(default_factory=list)
    waarschuwingen: list[str] = field(default_factory=list)

    @property
    def tekst(self) -> str:
        n = len(self.atleten)
        if not n and not self.te_controleren:
            delen = [f"Uitslag gelezen ({self.gelezen} regels), maar er staan geen atleten van ons in "
                     "(of hun naam wijkt af)."]
        else:
            delen = [f"Uitslagen geïmporteerd: {self.nieuw} nieuwe prestatie{'s' if self.nieuw != 1 else ''} "
                     f"van {n} {'atleet' if n == 1 else 'atleten'}."]
            if self.al_bekend:
                delen.append(f"{self.al_bekend} stonden er al.")
        if self.overgeslagen:
            delen.append(f"{self.overgeslagen} zonder geldige prestatie (DNF, DNS, NM) overgeslagen.")
        if self.nieuwe_onderdelen:
            delen.append(f"Nieuw in de onderdelenlijst: {', '.join(self.nieuwe_onderdelen)}.")
        if self.te_controleren:
            delen.append(f"{len(self.te_controleren)} te controleren (alleen de naam komt overeen).")
        return " ".join([*delen, *self.waarschuwingen])


# ============================================================
# Hulpfuncties
# ============================================================
def _importer_voor(bron: str, w: Wedstrijd) -> Importer:
    site = bron_uit_link(bron) if not str(bron).isdigit() else (w.bron or "atletieknu")
    if Importer.is_lokaal(bron):                   # opgeslagen pagina('s): kijk naar de inhoud
        html = Importer.lees_bestanden(bron)[0][1].lower()
        site = "seltec" if "competitions/" in html and "atletiek.nu" not in html else "atletieknu"
    if site == "seltec":
        return SeltecImporter()
    if site == "atletieknu":
        return AtletiekNuWedstrijdImporter()
    raise OpslagFout("Dit is geen link naar een wedstrijd op atletiek.nu of Seltec.")


def _onderdeelnaam(u) -> str:
    """'60 meter horden' + '76.2cm' -> '60 meter horden 76,2cm' (zoals bij de profielimport)."""
    return f"{u.onderdeel} {(u.specificatie or '').replace('.', ',')}".strip()


def _geboortejaar(u) -> int | None:
    jaar = getattr(u, "geboortejaar", "") or ""
    return int(jaar) if str(jaar).isdigit() else None


def _club_botst(a: Atleet, club: str) -> bool:
    """Heeft de atleet een club die niet die van de site is? Dan is het iemand anders."""
    return bool(a.club and club and normaliseer(a.club) != normaliseer(club))


class _Onderdelen:
    """Onderdelen opzoeken of (zoals bij de profielimport) aanmaken; onthoudt wat nieuw is."""

    def __init__(self, db: Opslag) -> None:
        self.db, self.alle, self.nieuw = db, db.onderdelen(), []
        self._cache: dict[str, Onderdeel] = {}

    def voor(self, u) -> Onderdeel:
        naam = _onderdeelnaam(u)
        if naam in self._cache:
            return self._cache[naam]
        code = getattr(u, "onderdeel_code", "") if not (u.specificatie or "") else ""
        o = self.db.onderdeel(naam) or zoek_onderdeel(self.alle, naam, code if not code.isdigit() else "")
        if o is None:
            eenheid = eenheid_van(naam)
            o = self.db.onderdeel_opslaan(Onderdeel(naam, eenheid, lager_is_beter=(eenheid == "tijd")))
            self.alle.append(o)
            self.nieuw.append(naam)
        self._cache[naam] = o
        return o


# ============================================================
# Importeren
# ============================================================
def uitslagen_importeren(db: Opslag, wedstrijd_id: int, bron: str | None = None,
                         importer: Importer | None = None) -> UitslagVerslag:
    """Haal de uitslag op, koppel aan onze atleten en sla de zekere prestaties op.

    bron: link, wedstrijd-id of opgeslagen pagina/map; zonder bron de link van de wedstrijd.
    Wie alleen op naam overeenkomt, staat in verslag.te_controleren (nog niet opgeslagen).
    """
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    bron = bron or w.bron_url
    if not bron:
        raise OpslagFout("Deze wedstrijd heeft geen link naar atletiek.nu of Seltec. "
                         "Vul die in bij 'Gegevens wijzigen'.")
    importer = importer or _importer_voor(bron, w)
    try:
        bron_wedstrijd, uitslagen = importer.parse(bron)
    except ImportFout as e:
        raise OpslagFout(str(e)) from None
    if not uitslagen:
        raise OpslagFout("Er staan (nog) geen uitslagen online voor deze wedstrijd.")

    verslag = UitslagVerslag(wedstrijd_id, gelezen=len(uitslagen))
    if bron_wedstrijd is not None and getattr(bron_wedstrijd, "datum", ""):
        try:
            if abs((date.fromisoformat(bron_wedstrijd.datum) - w.datum).days) > 3:
                verslag.waarschuwingen.append(
                    f"Let op: de uitslag is van {bron_wedstrijd.datum} ('{bron_wedstrijd.naam}'), "
                    f"de wedstrijd staat op {w.datum.isoformat()}. Klopt de link?")
        except ValueError:
            pass

    # Per persoon op de uitslag (naam + club + jaar) één keer zoeken.
    personen: dict[tuple, list] = {}
    for u in uitslagen:
        if u.estafette or not (u.atleet or "").strip():
            continue
        personen.setdefault((normaliseer(u.atleet), normaliseer(u.vereniging), _geboortejaar(u)), []).append(u)

    koppelaar = Koppelaar(db)
    ingeschreven = {i.atleet_id for i in db.deelnemers(wedstrijd_id)}
    onderdelen = _Onderdelen(db)
    bron_naam = importer.bron if importer.bron in ("atletieknu", "seltec") else bron_uit_link(bron)
    opslaan: list[Prestatie] = []
    namen: dict[str, str] = {}

    for (_, _, jaar), rijen in personen.items():
        eerste = rijen[0]
        k = koppelaar.zoek(eerste.atleet, None, jaar, eerste.vereniging or None)
        atleet = k.atleet if k.zeker else None
        kandidaten = [a for a in k.kandidaten if not _club_botst(a, eerste.vereniging)] if not atleet else []
        if atleet is None and kandidaten:
            mee = [a for a in kandidaten if a.master_id in ingeschreven]
            if len(mee) == 1:
                atleet, kandidaten = mee[0], []
        if atleet is None and not kandidaten:
            continue                                   # niet van ons
        prestaties = []
        for u in rijen:
            if u.waarde is None:
                verslag.overgeslagen += 1
                continue
            o = onderdelen.voor(u)
            try:
                datum = date.fromisoformat(u.datum) if u.datum else w.datum
            except ValueError:
                datum = w.datum
            prestaties.append(Prestatie(o.naam, datum, u.waarde, onderdeel_id=o.id, wedstrijd_id=w.id,
                                        wind=wind_van(u.wind), bron=bron_naam, indoor=w.indoor))
        if not prestaties:
            continue
        if atleet is not None:
            opslaan += [p.gekoppeld(atleet.master_id) for p in prestaties]
            namen[atleet.master_id] = atleet.naam
        else:
            verslag.te_controleren.append(TeControleren(f"p{len(verslag.te_controleren)}", eerste.atleet,
                                                        eerste.vereniging, kandidaten, prestaties))

    verslag.nieuw, verslag.al_bekend = db.prestaties_opslaan(opslaan)
    verslag.atleten = sorted(namen.values(), key=str.lower)
    verslag.nieuwe_onderdelen = onderdelen.nieuw
    return verslag


def uitslagen_bevestigen(db: Opslag, wedstrijd_id: int, keuzes: dict[str, str],
                         te_controleren: list[TeControleren]) -> tuple[int, int, list[str]]:
    """Sla de prestaties op van de personen die de trainer aan een atleet heeft gekoppeld.

    keuzes: sleutel -> master_id ('' = niet van ons). Alleen kandidaten van die persoon
    zijn toegestaan. Geeft (nieuw, al_bekend, namen).
    """
    if db.wedstrijd(wedstrijd_id) is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    opslaan, namen = [], []
    for t in te_controleren:
        mid = keuzes.get(t.sleutel) or ""
        if not mid:
            continue
        atleet = next((a for a in t.kandidaten if a.master_id == mid), None)
        if atleet is None:
            raise OpslagFout("Kies voor elke regel een van de voorgestelde atleten (of 'niet van ons').")
        opslaan += [p.gekoppeld(mid) for p in t.prestaties if p.wedstrijd_id == wedstrijd_id]
        namen.append(atleet.naam)
    nieuw, bekend = db.prestaties_opslaan(opslaan)
    return nieuw, bekend, namen


# ============================================================
# Te controleren: heen en terug via het formulier
# ============================================================
# Er wordt niets op de server bewaard tussen 'importeren' en 'bevestigen': per persoon gaan
# de kandidaten (master_ids) en de prestaties (onderdeel, datum, waarde, wind; geen namen)
# als verborgen velden mee, en worden bij het bevestigen opnieuw gecontroleerd.

def naar_formulier(t: TeControleren) -> str:
    """De prestaties van één persoon als JSON voor een verborgen veld."""
    return json.dumps([{"onderdeel_id": p.onderdeel_id, "datum": p.datum.isoformat(), "waarde": p.waarde,
                        "wind": p.wind, "bron": p.bron, "indoor": p.indoor} for p in t.prestaties])


def uit_formulier(db: Opslag, wedstrijd_id: int, formulier) -> list[TeControleren]:
    """Terug uit de verborgen velden: sleutels, kandidaat-<sleutel> (master_ids) en prestaties-<sleutel>."""
    uit = []
    for sleutel in formulier.getlist("sleutel"):
        if not sleutel.startswith("p") or not sleutel[1:].isdigit():
            continue
        kandidaten = [a for m in formulier.getlist(f"kandidaat-{sleutel}") if (a := db.atleet(m)) is not None]
        try:
            rijen = json.loads(formulier.get(f"prestaties-{sleutel}", "[]"))
            prestaties = []
            for r in rijen:
                o = db.onderdeel(int(r["onderdeel_id"]))
                if o is None:
                    raise ValueError
                prestaties.append(Prestatie(o.naam, date.fromisoformat(r["datum"]), float(r["waarde"]),
                                            onderdeel_id=o.id, wedstrijd_id=wedstrijd_id,
                                            wind=None if r.get("wind") is None else float(r["wind"]),
                                            bron=r.get("bron") if r.get("bron") in ("atletieknu", "seltec") else None,
                                            indoor=bool(r.get("indoor"))))
        except (ValueError, KeyError, TypeError):
            raise OpslagFout("De gegevens van het formulier kloppen niet; importeer de uitslag opnieuw.") from None
        uit.append(TeControleren(sleutel, formulier.get(f"naam-{sleutel}", ""), formulier.get(f"club-{sleutel}", ""),
                                 kandidaten, prestaties))
    return uit
