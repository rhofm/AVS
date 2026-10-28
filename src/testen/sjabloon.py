"""Testsjablonen: wat een test meet, met scoreformules, opgeslagen als YAML-bestand.

Een sjabloon heeft een naam en één of meer onderdelen (rijen). Elk onderdeel heeft een naam,
een soort (lengte in m, tijd in s of gewicht in kg) en eventueel een scoreformule met
parameters (zie formule.py). Hebben minstens twee onderdelen een formule, dan kunnen de
scores worden opgeteld tot een totaalscore (`totaal_optellen`, standaard aan).

Het YAML-bestand (één sjabloon per bestand) ziet er zo uit en is dus makkelijk te delen:

    naam: Sprongkracht
    totaal_optellen: true
    onderdelen:
      - naam: Hoogspringen staand
        soort: lengte          # lengte | tijd | gewicht
        formule: C1 * L        # mag ontbreken
        parameters: [100]      # C1, C2, ... in deze volgorde
      - naam: 30 m sprint
        soort: tijd
        formule: C1 / T
        parameters: [150]

Waar ze staan: de meegeleverde sjablonen in `config/testen/` (zoals de ploegregels, ook
naast de .exe aan te vullen), en je eigen sjablonen in de map `testsjablonen` in de
gegevensmap. Een eigen sjabloon met dezelfde bestandsnaam wint van een meegeleverd sjabloon.
Zet je een .yaml-bestand in die map, dan verschijnt het vanzelf in de lijst.
"""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import yaml

from .formule import Formule, FormuleFout

#: soort -> (naam van het resultaat in de formule, eenheid, lager is beter)
SOORTEN: dict[str, tuple[str, str, bool]] = {
    "lengte": ("L", "m", False),
    "tijd": ("T", "s", True),
    "gewicht": ("M", "kg", False),
}
SOORT_LABELS = {"lengte": "Lengte (m)", "tijd": "Tijd (s)", "gewicht": "Gewicht (kg)"}
MAX_ONDERDELEN = 20
MAX_PARAMETERS = 9
MAX_NAAM = 80
MAP_NAAM = "testsjablonen"
CONFIG_SUBMAP = "testen"


class SjabloonFout(ValueError):
    """Het sjabloon klopt niet. `problemen` bevat alle punten die misgaan."""

    def __init__(self, problemen: str | Sequence[str]):
        self.problemen = [problemen] if isinstance(problemen, str) else list(problemen)
        super().__init__(" ".join(self.problemen))


@dataclass
class Onderdeel:
    """Eén rij van een test: wat er gemeten wordt, en hoe het meetresultaat een score wordt."""
    naam: str
    soort: str = "tijd"                                   # lengte | tijd | gewicht
    formule: str = ""                                     # leeg = geen score
    parameters: list[float] = field(default_factory=list)  # C1, C2, ...

    @property
    def variabele(self) -> str:
        return SOORTEN[self.soort][0]

    @property
    def eenheid(self) -> str:
        return SOORTEN[self.soort][1]

    @property
    def lager_is_beter(self) -> bool:
        return SOORTEN[self.soort][2]

    @property
    def heeft_formule(self) -> bool:
        return bool(self.formule.strip())

    def compileer(self) -> Formule:
        """De uitrekenbare formule. FormuleFout als hij niet klopt."""
        return Formule(self.formule, len(self.parameters), self.variabele)

    def score(self, resultaat: float) -> float:
        return self.compileer().bereken(resultaat, self.parameters)


@dataclass
class Sjabloon:
    naam: str
    onderdelen: list[Onderdeel] = field(default_factory=list)
    totaal_optellen: bool = True
    slug: str = ""                                        # bestandsnaam zonder .yaml; leeg = nog niet opgeslagen

    @property
    def aantal_formules(self) -> int:
        return sum(1 for o in self.onderdelen if o.heeft_formule)

    @property
    def totaal_mogelijk(self) -> bool:
        """Is er iets om op te tellen? Minstens twee onderdelen met een formule."""
        return self.aantal_formules >= 2

    @property
    def telt_totaal(self) -> bool:
        return self.totaal_mogelijk and self.totaal_optellen

    def problemen(self) -> list[str]:
        """Alles wat er aan dit sjabloon niet klopt, in gewone taal. Leeg = in orde."""
        p: list[str] = []
        if not self.naam.strip():
            p.append("Geef de test een naam.")
        elif len(self.naam.strip()) > MAX_NAAM:
            p.append(f"De naam van de test is te lang (maximaal {MAX_NAAM} tekens).")
        if not self.onderdelen:
            p.append("Een test heeft minstens één onderdeel (resultaatrij).")
        if len(self.onderdelen) > MAX_ONDERDELEN:
            p.append(f"Een test kan hooguit {MAX_ONDERDELEN} onderdelen hebben.")
        namen: set[str] = set()
        for i, o in enumerate(self.onderdelen, start=1):
            wie = f"Onderdeel {i}" + (f" ({o.naam.strip()})" if o.naam.strip() else "")
            if not o.naam.strip():
                p.append(f"Onderdeel {i}: geef het een naam.")
            elif o.naam.strip().casefold() in namen:
                p.append(f"{wie}: deze naam komt twee keer voor.")
            namen.add(o.naam.strip().casefold())
            if len(o.naam.strip()) > MAX_NAAM:
                p.append(f"{wie}: de naam is te lang (maximaal {MAX_NAAM} tekens).")
            if o.soort not in SOORTEN:
                p.append(f"{wie}: kies lengte, tijd of gewicht.")
                continue
            if len(o.parameters) > MAX_PARAMETERS:
                p.append(f"{wie}: hooguit {MAX_PARAMETERS} parameters.")
            if o.heeft_formule:
                try:
                    o.compileer()
                except FormuleFout as e:
                    p.append(f"{wie}: {e}")
            elif o.parameters:
                p.append(f"{wie}: parameters zonder formule; zet het aantal parameters op 0 of vul een formule in.")
        return p

    def controleer(self) -> None:
        p = self.problemen()
        if p:
            raise SjabloonFout(p)

    # ---------------------------------------------------------------- YAML
    def naar_dict(self) -> dict:
        uit: dict = {"naam": self.naam.strip()}
        if self.totaal_mogelijk:
            uit["totaal_optellen"] = self.totaal_optellen
        uit["onderdelen"] = []
        for o in self.onderdelen:
            d: dict = {"naam": o.naam.strip(), "soort": o.soort}
            if o.heeft_formule:
                d["formule"] = o.formule.strip()
                d["parameters"] = [_netjes(x) for x in o.parameters]
            uit["onderdelen"].append(d)
        return uit

    def naar_yaml(self) -> str:
        kop = ("# Testsjabloon voor AVS. Soorten: lengte (m), tijd (s), gewicht (kg).\n"
               "# Formule: + - * / ^ sqrt( ) en haakjes; het resultaat heet L (lengte), T (tijd) of M (gewicht),\n"
               "# de parameters heten C1, C2, ... (zie 'parameters', in die volgorde).\n")
        return kop + yaml.dump(self.naar_dict(), Dumper=_Dumper, sort_keys=False, allow_unicode=True)

    @classmethod
    def uit_dict(cls, data: object, slug: str = "") -> "Sjabloon":
        if not isinstance(data, dict):
            raise SjabloonFout("Het bestand moet een sjabloon bevatten (naam: ..., onderdelen: ...).")
        onbekend = set(data) - {"naam", "totaal_optellen", "onderdelen"}
        if onbekend:
            raise SjabloonFout(f"Onbekend veld in het sjabloon: {', '.join(sorted(map(str, onbekend)))}.")
        rijen = data.get("onderdelen")
        if not isinstance(rijen, list) or not rijen:
            raise SjabloonFout("Het sjabloon heeft geen 'onderdelen' (een lijst met minstens één onderdeel).")
        onderdelen = []
        for i, r in enumerate(rijen, start=1):
            if not isinstance(r, dict):
                raise SjabloonFout(f"Onderdeel {i}: verwacht naam, soort en eventueel formule en parameters.")
            onbekend = set(r) - {"naam", "soort", "formule", "parameters"}
            if onbekend:
                raise SjabloonFout(f"Onderdeel {i}: onbekend veld {', '.join(sorted(map(str, onbekend)))}.")
            par = r.get("parameters") or []
            if not isinstance(par, list):
                raise SjabloonFout(f"Onderdeel {i}: 'parameters' moet een lijst met getallen zijn, bijv. [1.5, 2].")
            try:
                waarden = [float(str(x).replace(",", ".")) for x in par]
            except ValueError:
                raise SjabloonFout(f"Onderdeel {i}: 'parameters' moet getallen bevatten.") from None
            onderdelen.append(Onderdeel(str(r.get("naam") or "").strip(), str(r.get("soort") or "tijd").strip().lower(),
                                        "" if r.get("formule") is None else str(r["formule"]).strip(), waarden))
        optellen = data.get("totaal_optellen", True)
        if not isinstance(optellen, bool):
            raise SjabloonFout("'totaal_optellen' moet true of false zijn.")
        s = cls(str(data.get("naam") or "").strip(), onderdelen, optellen, slug)
        s.controleer()
        return s

    @classmethod
    def uit_yaml(cls, tekst: str, slug: str = "") -> "Sjabloon":
        try:
            data = yaml.safe_load(tekst)
        except yaml.YAMLError as e:
            raise SjabloonFout(f"Het bestand is geen geldige YAML: {e}") from None
        return cls.uit_dict(data, slug)

    # -------------------------------------------------------------- scoren
    def scores(self, waarden: Sequence[float | None]) -> tuple[list[float | None], float | None]:
        """Scores per onderdeel (None = geen formule of geen resultaat) en de totaalscore (None = niet opgeteld).

        FormuleFout als een formule bij dit resultaat niet uit te rekenen is. Het totaal is er alleen
        als alle onderdelen met een formule een resultaat hebben.
        """
        scores: list[float | None] = []
        for o, w in zip(self.onderdelen, waarden):
            scores.append(o.score(w) if o.heeft_formule and w is not None else None)
        totaal = None
        if self.telt_totaal:
            delen = [s for o, s in zip(self.onderdelen, scores) if o.heeft_formule]
            if all(s is not None for s in delen):
                totaal = float(sum(delen))
        return scores, totaal


class _Dumper(yaml.SafeDumper):
    """Blokstijl, behalve lijsten met alleen getallen: `parameters: [1.5, 2]`."""

    def represent_list(self, data):
        return self.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=all(not isinstance(x, (dict, list)) for x in data))


_Dumper.add_representer(list, _Dumper.represent_list)


def _netjes(x: float) -> float | int:
    return int(x) if float(x).is_integer() else x


# ====================================================================== bestanden
def maak_slug(naam: str) -> str:
    """Bestandsnaam voor een testnaam: 'Hoogspringen staand' -> 'hoogspringen_staand'."""
    s = unicodedata.normalize("NFKD", naam).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:60] or "test"


_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def sjabloonmap(datamap: Path | str | None = None) -> Path:
    """De map voor eigen sjablonen: `testsjablonen` in de gegevensmap."""
    if datamap is None:
        from db.init_db import standaard_map
        datamap = standaard_map()
    return Path(datamap) / MAP_NAAM


@dataclass
class Bron:
    sjabloon: Sjabloon
    pad: Path
    eigen: bool                       # in de gegevensmap (aan te passen); anders meegeleverd in config/testen


@dataclass
class Bibliotheek:
    bronnen: list[Bron]
    fouten: list[str]                 # bestanden die niet gelezen konden worden, met uitleg

    def vind(self, slug: str | None) -> Bron | None:
        return next((b for b in self.bronnen if slug and b.sjabloon.slug == slug), None)

    def per_naam(self, naam: str) -> Bron | None:
        return next((b for b in self.bronnen if b.sjabloon.naam.casefold() == naam.strip().casefold()), None)


def laad_bibliotheek(datamap: Path | str | None = None) -> Bibliotheek:
    """Alle sjablonen: eigen eerst (die winnen), dan de meegeleverde. Kapotte bestanden komen in `fouten`."""
    from ploeg.config import config_bestanden
    mappen: list[tuple[Path, bool]] = []
    eigen_map = sjabloonmap(datamap)
    eigen = sorted(eigen_map.glob("*.yaml")) if eigen_map.is_dir() else []
    meegeleverd = config_bestanden(CONFIG_SUBMAP)
    bronnen: dict[str, Bron] = {}
    fouten: list[str] = []
    for pad, is_eigen in [(p, True) for p in eigen] + [(p, False) for p in meegeleverd]:
        slug = pad.stem
        if slug in bronnen or not _SLUG.match(slug):
            if not _SLUG.match(slug):
                fouten.append(f"{pad.name}: gebruik een bestandsnaam met kleine letters, cijfers, _ en -.")
            continue
        try:
            tekst = pad.read_text(encoding="utf-8")
            if all(not r.strip() or r.lstrip().startswith("#") for r in tekst.splitlines()):
                continue                                                  # leeg voorbeeldbestand
            bronnen[slug] = Bron(Sjabloon.uit_yaml(tekst, slug), pad, is_eigen)
        except (OSError, UnicodeDecodeError) as e:
            fouten.append(f"{pad.name}: kon het bestand niet lezen ({e}).")
        except SjabloonFout as e:
            fouten.append(f"{pad.name}: {e}")
    lijst = sorted(bronnen.values(), key=lambda b: b.sjabloon.naam.casefold())
    # Twee sjablonen met dezelfde naam kunnen niet naast elkaar (de testnaam is uniek): de eerste wint.
    gezien: set[str] = set()
    uniek = []
    for b in lijst:
        sleutel = b.sjabloon.naam.casefold()
        if sleutel in gezien:
            fouten.append(f"{b.pad.name}: er is al een sjabloon met de naam '{b.sjabloon.naam}'.")
            continue
        gezien.add(sleutel)
        uniek.append(b)
    return Bibliotheek(uniek, fouten)


def opslaan(sjabloon: Sjabloon, datamap: Path | str | None = None, *, bibliotheek: Bibliotheek | None = None) -> Sjabloon:
    """Schrijf het sjabloon naar de map met eigen sjablonen en geef het terug met zijn `slug`.

    Een sjabloon dat al een slug heeft wordt onder dezelfde bestandsnaam bewaard (ook als het een
    meegeleverd sjabloon was: dan komt er een eigen versie die voorrang heeft). Een nieuw sjabloon
    krijgt een bestandsnaam uit zijn naam. De naam moet uniek zijn.
    """
    sjabloon.controleer()
    bib = bibliotheek or laad_bibliotheek(datamap)
    andere = bib.per_naam(sjabloon.naam)
    if andere is not None and andere.sjabloon.slug != sjabloon.slug:
        raise SjabloonFout(f"Er is al een test met de naam '{sjabloon.naam.strip()}'. Kies een andere naam.")
    slug = sjabloon.slug
    if not slug:
        basis = maak_slug(sjabloon.naam)
        slug, n = basis, 2
        while bib.vind(slug) is not None or (sjabloonmap(datamap) / f"{slug}.yaml").exists():
            slug, n = f"{basis}_{n}", n + 1
    map_ = sjabloonmap(datamap)
    map_.mkdir(parents=True, exist_ok=True)
    doel = map_ / f"{slug}.yaml"
    fd, tmp = tempfile.mkstemp(dir=map_, suffix=".tmp")                    # eerst helemaal schrijven, dan vervangen
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(Sjabloon(sjabloon.naam, sjabloon.onderdelen, sjabloon.totaal_optellen, slug).naar_yaml())
        os.replace(tmp, doel)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return Sjabloon(sjabloon.naam.strip(), sjabloon.onderdelen, sjabloon.totaal_optellen, slug)


def verwijderen(slug: str, datamap: Path | str | None = None) -> bool:
    """Verwijder een eigen sjabloon (een meegeleverd sjabloon blijft). True als er een bestand weg is."""
    if not _SLUG.match(slug or ""):
        return False
    pad = sjabloonmap(datamap) / f"{slug}.yaml"
    if pad.is_file():
        pad.unlink()
        return True
    return False
