"""Laadt opstellingsregels uit config/ploeg_regels/ en controleert een opstelling ertegen.

Een regelbestand (YAML) beschrijft één competitie in één seizoen, bijvoorbeeld
`u14_u16_2026-2027.yaml`: per ploeg (categorie) het programma van elke
wedstrijd, hoeveel atleten per onderdeel mogen en tellen, wie in de ploeg mag,
en de algemene regels (3 onderdelen per atleet, 4 reserves, ...). Ploegleiders
passen dat bestand aan; in de code staan geen competitieregels.

Gebruik:

    from ploeg import regels
    rs = regels.laad("u14_u16_2026-2027")
    rs.programma("U16-V", "wedstrijd_1")         # -> [Programmaregel(80m, max 3, telt 2), ...]
    rs.controleer("U16-V", "wedstrijd_1", leden, inzet, categorieen)   # -> [Overtreding, ...]
    regels.controleer_dag({"U14-V A": leden_a, "U16-V": leden_b})      # 10.10: één ploeg per dag

Categorieën zijn codes als 'U14-V' (meisjes U14), 'U16-M' (jongens U16) of
'SEN-V'; maak ze met `categorie_code(leeftijdscategorie, geslacht)`. De
leeftijdscategorie op de wedstrijddag komt van `atleten.landingspagina.leeftijdscategorie`.

Bij het laden wordt alles gecontroleerd, ook tegen de puntentelling: elk
onderdeel op een programma moet een puntentelling hebben. Een fout in het
bestand geeft een `RegelFout` met een uitleg in gewone taal.

Overtredingen noemen een atleet alleen met zijn master_id; de UI zet daar de
naam bij. Zo komen er geen namen in logs.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Literal, Mapping

import yaml

from models.ploeg import Inzet, PloegLid
from ploeg import punten as _punten
from ploeg.config import config_map

Soort = Literal["loop", "technisch", "estafette"]
Ernst = Literal["fout", "waarschuwing"]

PUNTENTOEKENNINGEN = ("prestatie", "plaats")   # 18.1: naar prestatie of naar plaats
MATERIAAL = ("ploeg", "eigen")                 # werpmateriaal/hordehoogte van de ploeg of van de atleet

_CATEGORIE = re.compile(r"^(?:(?:U\d{1,2}|SEN)-[MV]|[MV]\d{2})$")   # U14-V, SEN-M, masters M35/V40
_SLEUTELS = {"naam", "seizoen", "bron", "puntentelling", "puntentabel", "puntentoekenning",
             "algemeen", "ploegen", "onderdelen"}
_ALGEMEEN = {"max_onderdelen_per_atleet", "max_reserves", "een_ploeg_per_dag",
             "een_atleet_per_groep", "tellend", "materiaal"}
_PLOEG = {"naam", "geslacht", "toegestaan", "programma"}
_ONDERDEEL = {"naam", "specificatie", "lopers", "samenstelling"}


class RegelFout(ValueError):
    """Een regelbestand is niet te lezen of klopt niet, of een gevraagde ploeg/wedstrijd bestaat niet."""


def categorie_code(leeftijdscategorie: str | None, geslacht: str | None) -> str | None:
    """'U14' + 'V' -> 'U14-V'; 'Senior' + 'M' -> 'SEN-M'. Onbekend (of geslacht X) -> None."""
    if not leeftijdscategorie or geslacht not in ("M", "V"):
        return None
    leeftijd = "SEN" if leeftijdscategorie.strip().lower() in ("senior", "sen") else leeftijdscategorie.strip().upper()
    code = f"{leeftijd}-{geslacht}"
    return code if _CATEGORIE.match(code) else None


def _geslacht_van(categorie: str) -> str:
    return categorie[-1] if "-" in categorie else categorie[0]


# ============================================================
# Onderdelen en programma
# ============================================================
@dataclass(frozen=True, slots=True)
class OnderdeelInfo:
    """Een onderdeel zoals het in een regelbestand staat."""

    sleutel: str                                  # bijv. '80mH' (zelfde als in de puntentelling)
    naam: str                                     # zoals atletiek.nu het noemt: '80 meter horden'
    specificaties: Mapping[str, str] = field(default_factory=dict)   # categorie -> '76.2cm', '3kg'
    lopers: int | None = None                     # estafette: aantal lopers per ploeg
    samenstelling: Mapping[str, int] = field(default_factory=dict)   # gemengde estafette: {'M': 2, 'V': 2}

    @property
    def is_estafette(self) -> bool:
        return self.lopers is not None

    def specificatie(self, categorie: str) -> str | None:
        return self.specificaties.get(categorie)

    def volledige_naam(self, categorie: str) -> str:
        """Naam zoals het onderdeel bij de prestaties heet: naam + specificatie
        ('Kogelstoten 3kg', '80 meter horden 76,2cm'), net als bij de atletiek.nu-import."""
        spec = self.specificatie(categorie)
        return f"{self.naam} {spec.replace('.', ',')}".strip() if spec else self.naam


@dataclass(frozen=True, slots=True)
class Programmaregel:
    """Een onderdeel op het programma van één wedstrijd voor één ploeg."""

    onderdeel: OnderdeelInfo
    max_atleten: int        # max. deelnemers per ploeg (bij estafettes: aantal estafetteploegen)
    soort: Soort
    tellend: int            # zoveel beste atleten tellen voor de punten (estafette: 1)

    @property
    def sleutel(self) -> str:
        return self.onderdeel.sleutel

    @property
    def naam(self) -> str:
        return self.onderdeel.naam


@dataclass(frozen=True, slots=True)
class Ploegsoort:
    """Een ploeg in een competitie, bijv. 'U16 meisjes'."""

    sleutel: str                                   # categorie van de ploeg: 'U16-V'
    naam: str
    geslacht: str                                  # 'M' of 'V'
    toegestaan: tuple[str, ...]                    # categorieën die in de ploeg mogen
    programmas: Mapping[str, Mapping[str, int]]    # 'wedstrijd_1' -> {'80m': 3, ...}


@dataclass(frozen=True, slots=True)
class Overtreding:
    """Iets in een opstelling dat niet mag (fout) of opvalt (waarschuwing)."""

    code: str
    tekst: str
    ernst: Ernst = "fout"
    atleet_id: str | None = None
    onderdeel: str | None = None


# ============================================================
# Regelset
# ============================================================
@dataclass(frozen=True)
class Regelset:
    bestand: str                    # bestandsnaam zonder .yaml; gaat in ploeg.regelset
    naam: str
    seizoen: str
    bron: str
    puntentelling: str              # uitgave in config/puntentelling/
    puntentabel: str
    puntentoekenning: str
    max_onderdelen_per_atleet: int
    max_reserves: int
    een_ploeg_per_dag: bool
    een_atleet_per_groep: bool
    tellend: Mapping[str, int]      # 'loop' / 'technisch' -> aantal
    materiaal: str
    ploegen: Mapping[str, Ploegsoort]
    onderdelen: Mapping[str, OnderdeelInfo]
    _programmas: Mapping[tuple[str, str], tuple[Programmaregel, ...]] = field(repr=False, default_factory=dict)

    # ---------------- opvragen ----------------
    def ploeg(self, sleutel: str) -> Ploegsoort:
        try:
            return self.ploegen[sleutel]
        except KeyError:
            raise RegelFout(f"{self.naam} kent geen ploeg {sleutel!r}; kies uit "
                            f"{', '.join(self.ploegen)}.") from None

    def programmas(self, ploeg: str) -> list[str]:
        """De wedstrijden met een programma voor deze ploeg: ['wedstrijd_1', ..., 'finale_2027']."""
        return list(self.ploeg(ploeg).programmas)

    def programma(self, ploeg: str, programma: str) -> list[Programmaregel]:
        p = self.ploeg(ploeg)
        if programma not in p.programmas:
            raise RegelFout(f"{p.naam} heeft geen programma {programma!r}; kies uit "
                            f"{', '.join(p.programmas)}.")
        return list(self._programmas[(ploeg, programma)])

    def mag_meedoen(self, ploeg: str, categorie: str | None) -> bool:
        return categorie is not None and categorie in self.ploeg(ploeg).toegestaan

    def materiaal_categorie(self, ploeg: str, categorie: str) -> str:
        """Welke categorie bepaalt werpmateriaal en hordehoogte: die van de ploeg of van de atleet."""
        return categorie if self.materiaal == "eigen" else self.ploeg(ploeg).sleutel

    def onderdeel_naam(self, ploeg: str, sleutel: str, categorie: str) -> str:
        """Naam (+ specificatie) van het onderdeel dat deze atleet in deze ploeg doet."""
        info = self.onderdelen.get(sleutel)
        if info is None:
            raise RegelFout(f"Onbekend onderdeel {sleutel!r} in {self.naam}.")
        return info.volledige_naam(self.materiaal_categorie(ploeg, categorie))

    # ---------------- controleren ----------------
    def controleer(self, ploeg: str, programma: str, leden: Iterable[PloegLid], inzet: Iterable[Inzet],
                   categorieen: Mapping[str, str | None]) -> list[Overtreding]:
        """Alle overtredingen van één ploegopstelling.

        `categorieen`: atleet_id -> categoriecode op de wedstrijddag ('U14-V').
        Een opstelling zonder fouten mag worden ingediend; waarschuwingen zijn
        ter informatie (bijv. een estafette met maar 3 lopers).
        """
        p = self.ploeg(ploeg)
        regels = {r.sleutel: r for r in self.programma(ploeg, programma)}
        uit: list[Overtreding] = []

        # --- het inschrijfformulier ---
        leden = list(leden)
        lid_van: dict[str, PloegLid] = {}
        for lid in leden:
            if lid.atleet_id in lid_van:
                uit.append(Overtreding("dubbel_lid", "Deze atleet staat twee keer op het formulier.",
                                       atleet_id=lid.atleet_id))
                continue
            lid_van[lid.atleet_id] = lid
            cat = categorieen.get(lid.atleet_id)
            if cat is None:
                uit.append(Overtreding(
                    "categorie_onbekend",
                    "De categorie van deze atleet is niet bekend (geboortedatum of geslacht ontbreekt).",
                    "waarschuwing", lid.atleet_id))
            elif cat not in p.toegestaan:
                uit.append(Overtreding("niet_toegestaan", f"Een {cat} mag niet in de ploeg {p.naam}.",
                                       atleet_id=lid.atleet_id))

        reserves = sum(1 for lid in lid_van.values() if lid.rol == "reserve")
        if reserves > self.max_reserves:
            uit.append(Overtreding("te_veel_reserves",
                                   f"{reserves} reserves; er mogen er maximaal {self.max_reserves} (9.3)."))

        # --- wie doet wat ---
        per_atleet: dict[str, list[str]] = defaultdict(list)
        per_onderdeel: dict[str, list[Inzet]] = defaultdict(list)
        gezien: set[tuple[str, str]] = set()
        for i in inzet:
            lid = lid_van.get(i.atleet_id)
            if lid is None:
                uit.append(Overtreding("geen_lid", "Deze atleet doet een onderdeel maar staat niet in de ploeg.",
                                       atleet_id=i.atleet_id, onderdeel=i.onderdeel))
            elif lid.rol == "reserve":
                uit.append(Overtreding("reserve_met_onderdeel",
                                       "Een reserve staat niet voor een onderdeel ingeschreven (9.3).",
                                       atleet_id=i.atleet_id, onderdeel=i.onderdeel))
            regel = regels.get(i.onderdeel)
            if regel is None:
                info = self.onderdelen.get(i.onderdeel)
                naam = info.naam if info else i.onderdeel
                uit.append(Overtreding("niet_op_programma", f"{naam} staat niet op het programma van deze wedstrijd.",
                                       atleet_id=i.atleet_id, onderdeel=i.onderdeel))
                continue
            if (i.atleet_id, i.onderdeel) in gezien:
                uit.append(Overtreding("dubbel", f"Deze atleet staat twee keer op {regel.naam}.",
                                       atleet_id=i.atleet_id, onderdeel=i.onderdeel))
                continue
            gezien.add((i.atleet_id, i.onderdeel))
            per_atleet[i.atleet_id].append(i.onderdeel)
            per_onderdeel[i.onderdeel].append(i)

        for sleutel, regel in regels.items():
            ingezet = per_onderdeel.get(sleutel, [])
            if regel.soort == "estafette":
                uit += self._controleer_estafette(regel, ingezet, categorieen)
            elif len(ingezet) > regel.max_atleten:
                uit.append(Overtreding("te_veel_op_onderdeel",
                                       f"{len(ingezet)} atleten op {regel.naam}; maximaal {regel.max_atleten}.",
                                       onderdeel=sleutel))
            if self.een_atleet_per_groep and regel.soort == "technisch":
                for groep, n in sorted(Counter(i.groep for i in ingezet if i.groep is not None).items()):
                    if n > 1:
                        uit.append(Overtreding("zelfde_groep",
                                               f"{n} atleten in groep {groep} van {regel.naam}; "
                                               f"per groep één atleet per ploeg (9.1).", onderdeel=sleutel))

        for atleet_id, onderdelen in per_atleet.items():
            if len(onderdelen) > self.max_onderdelen_per_atleet:
                uit.append(Overtreding(
                    "te_veel_onderdelen",
                    f"{len(onderdelen)} onderdelen; maximaal {self.max_onderdelen_per_atleet}, "
                    f"estafettes meegeteld (4.1).", atleet_id=atleet_id))
        return uit

    @staticmethod
    def _controleer_estafette(regel: Programmaregel, ingezet: list[Inzet],
                              categorieen: Mapping[str, str | None]) -> list[Overtreding]:
        uit = []
        lopers = regel.onderdeel.lopers or 4
        maximaal = regel.max_atleten * lopers
        n = len(ingezet)
        if n > maximaal:
            uit.append(Overtreding("te_veel_lopers", f"{n} lopers op de {regel.naam}; maximaal {maximaal}.",
                                   onderdeel=regel.sleutel))
        elif n % lopers:
            uit.append(Overtreding("estafette_onvolledig",
                                   f"{n} lopers op de {regel.naam}; een estafetteploeg heeft er {lopers}.",
                                   "waarschuwing", onderdeel=regel.sleutel))
        if regel.onderdeel.samenstelling and n == lopers:
            telling = Counter(_geslacht_van(c) for i in ingezet if (c := categorieen.get(i.atleet_id)))
            for geslacht, nodig in regel.onderdeel.samenstelling.items():
                if telling.get(geslacht, 0) != nodig:
                    uit.append(Overtreding(
                        "samenstelling",
                        f"De {regel.naam} moet bestaan uit "
                        + " en ".join(f"{k} {'mannen' if g == 'M' else 'vrouwen'}"
                                      for g, k in regel.onderdeel.samenstelling.items()) + ".",
                        onderdeel=regel.sleutel))
                    break
        return uit

    # ---------------- laden ----------------
    @classmethod
    def uit_dict(cls, ruw, bestand: str = "regels", puntenmap: Path | None = None) -> "Regelset":
        """Bouw en controleer een regelset. `puntenmap`: map met puntentelling/ (standaard config/)."""
        waar = f"{bestand}.yaml"
        if not isinstance(ruw, dict):
            raise RegelFout(f"{waar} is leeg of geen geldig regelbestand.")
        _onbekend(waar, ruw, _SLEUTELS)
        for verplicht in ("naam", "puntentelling", "puntentabel", "ploegen", "onderdelen"):
            if verplicht not in ruw:
                raise RegelFout(f"{waar}: '{verplicht}' ontbreekt.")

        # puntentelling
        try:
            pt = _punten.puntentelling(str(ruw["puntentelling"]), map=puntenmap)
        except _punten.PuntenFout as e:
            raise RegelFout(f"{waar}: {e}") from None
        tabel = str(ruw["puntentabel"])
        if tabel not in pt.tabellen:
            raise RegelFout(f"{waar}: puntentabel {tabel!r} staat niet in {ruw['puntentelling']}.yaml.")
        toekenning = ruw.get("puntentoekenning", "prestatie")
        if toekenning not in PUNTENTOEKENNINGEN:
            raise RegelFout(f"{waar}: puntentoekenning moet {' of '.join(PUNTENTOEKENNINGEN)} zijn.")

        # algemeen
        alg = ruw.get("algemeen") or {}
        if not isinstance(alg, dict):
            raise RegelFout(f"{waar}: 'algemeen' moet een lijst met instellingen zijn.")
        _onbekend(f"{waar}: algemeen", alg, _ALGEMEEN)
        max_ond = _geheel(f"{waar}: max_onderdelen_per_atleet", alg.get("max_onderdelen_per_atleet", 3), 1)
        max_res = _geheel(f"{waar}: max_reserves", alg.get("max_reserves", 4), 0)
        tellend_ruw = alg.get("tellend", {"loop": 1, "technisch": 1})
        if not isinstance(tellend_ruw, dict):
            raise RegelFout(f"{waar}: tellend moet zijn als {{loop: 2, technisch: 1}}.")
        _onbekend(f"{waar}: tellend", tellend_ruw, {"loop", "technisch"})
        tellend = {s: _geheel(f"{waar}: tellend.{s}", tellend_ruw.get(s, 1), 1) for s in ("loop", "technisch")}
        materiaal = alg.get("materiaal", "ploeg")
        if materiaal not in MATERIAAL:
            raise RegelFout(f"{waar}: materiaal moet {' of '.join(MATERIAAL)} zijn.")

        # onderdelen
        if not isinstance(ruw["onderdelen"], dict) or not ruw["onderdelen"]:
            raise RegelFout(f"{waar}: 'onderdelen' is leeg.")
        onderdelen = {str(k): _onderdeel(f"{waar}: onderdelen.{k}", str(k), v) for k, v in ruw["onderdelen"].items()}

        # ploegen en programma's
        if not isinstance(ruw["ploegen"], dict) or not ruw["ploegen"]:
            raise RegelFout(f"{waar}: 'ploegen' is leeg.")
        ploegen: dict[str, Ploegsoort] = {}
        programmas: dict[tuple[str, str], tuple[Programmaregel, ...]] = {}
        for sleutel, d in ruw["ploegen"].items():
            sleutel = str(sleutel)
            pw = f"{waar}: ploeg {sleutel}"
            p = _ploeg(pw, sleutel, d)
            ploegen[sleutel] = p
            for prog, inhoud in p.programmas.items():
                rij = []
                for ond, aantal in inhoud.items():
                    if ond not in onderdelen:
                        raise RegelFout(f"{pw}, {prog}: onderdeel {ond!r} staat niet onder 'onderdelen'.")
                    if not pt.heeft(tabel, ond, p.geslacht):
                        raise RegelFout(f"{pw}, {prog}: geen puntentelling voor {ond!r} "
                                        f"in {ruw['puntentelling']}.yaml / {tabel}.")
                    info = onderdelen[ond]
                    if info.is_estafette:
                        soort, telt = "estafette", 1
                    else:
                        soort = "loop" if pt.formule(tabel, ond, p.geslacht).lager_is_beter else "technisch"
                        telt = min(tellend[soort], aantal)
                    rij.append(Programmaregel(info, aantal, soort, telt))
                programmas[(sleutel, prog)] = tuple(rij)

        return cls(
            bestand=bestand, naam=str(ruw["naam"]), seizoen=str(ruw.get("seizoen", "")),
            bron=str(ruw.get("bron", "")), puntentelling=str(ruw["puntentelling"]), puntentabel=tabel,
            puntentoekenning=toekenning, max_onderdelen_per_atleet=max_ond, max_reserves=max_res,
            een_ploeg_per_dag=bool(alg.get("een_ploeg_per_dag", True)),
            een_atleet_per_groep=bool(alg.get("een_atleet_per_groep", True)),
            tellend=tellend, materiaal=materiaal, ploegen=ploegen, onderdelen=onderdelen,
            _programmas=programmas,
        )


def _onbekend(waar: str, d: dict, toegestaan: set[str]) -> None:
    vreemd = sorted(str(k) for k in d if k not in toegestaan)
    if vreemd:
        raise RegelFout(f"{waar}: onbekende instelling {', '.join(map(repr, vreemd))} (tikfout?). "
                        f"Mogelijk: {', '.join(sorted(toegestaan))}.")


def _geheel(waar: str, v, minimaal: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < minimaal:
        raise RegelFout(f"{waar} moet een heel getal van minstens {minimaal} zijn (nu {v!r}).")
    return v


def _categorie(waar: str, c) -> str:
    c = str(c)
    if not _CATEGORIE.match(c):
        raise RegelFout(f"{waar}: {c!r} is geen categorie; schrijf bijv. U14-V, U16-M of SEN-V.")
    return c


def _onderdeel(waar: str, sleutel: str, d) -> OnderdeelInfo:
    if not isinstance(d, dict) or not isinstance(d.get("naam"), str) or not d["naam"].strip():
        raise RegelFout(f"{waar}: geef minstens een naam, bijv. {{naam: 80 meter horden}}.")
    _onbekend(waar, d, _ONDERDEEL)
    spec = d.get("specificatie") or {}
    if not isinstance(spec, dict):
        raise RegelFout(f"{waar}: specificatie moet per categorie zijn, bijv. {{U16-V: 3kg}}.")
    specs = {_categorie(waar, k): str(v) for k, v in spec.items()}
    lopers = _geheel(f"{waar}: lopers", d["lopers"], 2) if "lopers" in d else None
    samenstelling = d.get("samenstelling") or {}
    if samenstelling:
        if lopers is None or not isinstance(samenstelling, dict) or set(samenstelling) - {"M", "V"}:
            raise RegelFout(f"{waar}: samenstelling hoort bij een estafette, bijv. {{M: 2, V: 2}}.")
        samenstelling = {g: _geheel(f"{waar}: samenstelling.{g}", n, 0) for g, n in samenstelling.items()}
        if sum(samenstelling.values()) != lopers:
            raise RegelFout(f"{waar}: samenstelling telt op tot {sum(samenstelling.values())}, "
                            f"niet tot {lopers} lopers.")
    return OnderdeelInfo(sleutel, d["naam"].strip(), specs, lopers, samenstelling)


def _ploeg(waar: str, sleutel: str, d) -> Ploegsoort:
    _categorie(waar, sleutel)
    if not isinstance(d, dict):
        raise RegelFout(f"{waar}: verwacht naam, geslacht, toegestaan en programma.")
    _onbekend(waar, d, _PLOEG)
    geslacht = d.get("geslacht", _geslacht_van(sleutel))
    if geslacht not in ("M", "V"):
        raise RegelFout(f"{waar}: geslacht moet M of V zijn.")
    toegestaan = d.get("toegestaan", [sleutel])
    if not isinstance(toegestaan, list) or not toegestaan:
        raise RegelFout(f"{waar}: toegestaan moet een lijst zijn, bijv. [U14-V, U16-V].")
    toegestaan = tuple(_categorie(waar, c) for c in toegestaan)
    progs = d.get("programma")
    if not isinstance(progs, dict) or not progs:
        raise RegelFout(f"{waar}: 'programma' ontbreekt of is leeg.")
    programmas: dict[str, dict[str, int]] = {}
    for prog, inhoud in progs.items():
        if not isinstance(inhoud, dict) or not inhoud:
            raise RegelFout(f"{waar}, {prog}: geef de onderdelen als {{80m: 3, verspringen: 2}}.")
        programmas[str(prog)] = {str(o): _geheel(f"{waar}, {prog}, {o}", n, 1) for o, n in inhoud.items()}
    return Ploegsoort(sleutel, str(d.get("naam", sleutel)), geslacht, toegestaan, programmas)


# ============================================================
# Meer ploegen op één dag
# ============================================================
def controleer_dag(ploegen: Mapping[str, Iterable[PloegLid]]) -> list[Overtreding]:
    """10.10: een atleet staat op één wedstrijddag in maar één ploeg (ook niet als reserve
    in een tweede). `ploegen`: naam van de ploeg -> leden."""
    waar: dict[str, list[str]] = defaultdict(list)
    for naam, leden in ploegen.items():
        for lid in {lid.atleet_id for lid in leden}:
            waar[lid].append(naam)
    return [
        Overtreding("twee_ploegen", f"Deze atleet staat in {len(namen)} ploegen op dezelfde dag: "
                                    f"{', '.join(namen)} (10.10).", atleet_id=atleet_id)
        for atleet_id, namen in waar.items() if len(namen) > 1
    ]


# ============================================================
# Bestanden
# ============================================================
def _map(map: Path | None) -> Path:
    return Path(map) if map else config_map() / "ploeg_regels"


def bestanden(map: Path | None = None) -> list[str]:
    """Namen (zonder .yaml) van de regelbestanden die iets bevatten; lege voorbeeldbestanden tellen niet."""
    uit = []
    for pad in sorted(_map(map).glob("*.yaml")):
        try:
            inhoud = yaml.safe_load(pad.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            inhoud = True            # kapot bestand wel tonen: laad() legt uit wat er mis is
        if inhoud:
            uit.append(pad.stem)
    return uit


@lru_cache(maxsize=16)
def _laad(pad: str, gewijzigd: int, puntenmap: str | None) -> Regelset:
    p = Path(pad)
    try:
        ruw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RegelFout(f"{p.name} is geen geldige YAML: {e}") from None
    return Regelset.uit_dict(ruw, bestand=p.stem, puntenmap=Path(puntenmap) if puntenmap else None)


def laad(bestand: str, map: Path | None = None, puntenmap: Path | None = None) -> Regelset:
    """Regelset uit `config/ploeg_regels/<bestand>.yaml`. Een aangepast bestand wordt opnieuw gelezen."""
    naam = bestand[:-5] if bestand.endswith(".yaml") else bestand
    if not naam or "/" in naam or "\\" in naam or naam.startswith("."):
        raise RegelFout(f"Ongeldige naam voor een regelbestand: {bestand!r}.")
    pad = _map(map) / f"{naam}.yaml"
    if not pad.is_file():
        raise RegelFout(f"Regelbestand {naam}.yaml niet gevonden in {pad.parent}.")
    return _laad(str(pad), pad.stat().st_mtime_ns, str(puntenmap) if puntenmap else None)
