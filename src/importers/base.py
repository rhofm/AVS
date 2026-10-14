"""
Gemeenschappelijke basis voor alle importers: de klasse Importer met de interface
can_handle(url) en parse(bron), plus de hulpfuncties die elke importer nodig heeft.

Een nieuwe importer maken:

    class MijnImporter(Importer):
        bron = "mijnsite"                                   # waarde voor de kolom 'bron'
        site = "mijnsite.nl"                                # voor meldingen aan de gebruiker
        url_patronen = (r"mijnsite\\.nl/uitslagen/\\d+",)

        def parse(self, bron: str):
            html = self.haal_op(bron)
            ...

Elke subklasse met een `bron` wordt automatisch geregistreerd; importers/detect.py kiest
daaruit de eerste waarvan can_handle(url) True geeft.

Sommige sites (atletiek.nu) herkennen de Python-bibliotheek requests aan zijn
verbindingskenmerken en geven dan een 'Checking your browser'-pagina. Zet daarvoor
`imiteer_browser = "chrome"`: de importer haalt dan op via curl_cffi, dat zich als Chrome
voordoet (pip install curl_cffi).

Fouten tijdens het importeren (site onbereikbaar, geblokkeerd, niets gevonden) worden als
ImportFout gegooid, met een melding die je direct aan de gebruiker kunt tonen. Een
opdrachtregelscript vangt die op en stopt met sys.exit(str(fout)); de UI toont hem.
"""

from __future__ import annotations

import csv
import re
import sys
import time
import unicodedata
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, ClassVar, Iterable, Protocol

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}


class ImportFout(Exception):
    """Importeren lukt niet; de tekst is bedoeld voor de gebruiker."""


# --------------------------------------------------------------------------- hulpfuncties

def clean(text: str) -> str:
    """Witruimte (ook harde spaties) samenvoegen tot enkele spaties en afknippen."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def normaliseer(naam: str) -> str:
    """Voor vergelijken: hoofdletterongevoelig, zonder accenten, enkele spaties."""
    zonder_accent = "".join(c for c in unicodedata.normalize("NFKD", naam or "")
                            if not unicodedata.combining(c))
    return clean(zonder_accent).casefold()


def to_number(prestatie: str) -> float | None:
    """
    Prestatie als getal (seconden / meters / punten), None bij DNF, DNS, nm., ...
      '1:54,71' -> 114.71 | '1:02:03,4' -> 3723.4 | '1.02:03,4' -> 3723.4 (atletiek.nu)
      '10,1h' -> 10.1 | '3785' -> 3785.0 | 'DNF' -> None
    """
    s = (prestatie or "").strip().rstrip("hH").strip().replace(",", ".")
    if not re.fullmatch(r"\d[\d.:]*", s):
        return None
    try:
        delen = s.split(":")
        if len(delen) == 1:
            return float(s)
        if len(delen) == 2 and "." in delen[0]:          # atletiek.nu-uren: "1.02:03.4"
            delen = delen[0].split(".", 1) + delen[1:]
        waarde = 0
        for deel in delen[:-1]:
            waarde = waarde * 60 + int(deel)
        return round(waarde * 60 + float(delen[-1]), 3)
    except ValueError:
        return None


def write_csv(path: str | Path, rows: list[dict], velden: Iterable[str] | None = None) -> None:
    """CSV met ';' en utf-8-sig, zodat hij goed opent in Excel. `velden` = kolommen als rows leeg is."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        kolommen = list(rows[0].keys()) if rows else list(velden or [])
        writer = csv.DictWriter(f, fieldnames=kolommen, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------------- filteren
# Werkt op elke uitslag met de velden atleet, vereniging, team, estafette en lopers
# (zoals de Uitslag-dataclasses van atletieknu_wedstrijd en seltec).

class UitslagAchtig(Protocol):
    atleet: str
    vereniging: str
    team: str
    estafette: bool
    lopers: str


def naam_past(waarden: Iterable[str], gezocht: str) -> Callable[[str], bool]:
    """
    Geeft een functie die test of een naam (vereniging/team) overeenkomt: exact
    (hoofdletterongevoelig) als die naam voorkomt, anders 'bevat'.
    """
    doel = normaliseer(gezocht)
    if any(normaliseer(w) == doel for w in waarden):
        return lambda w: normaliseer(w) == doel
    return lambda w: bool(doel) and doel in normaliseer(w)


def lopers_lijst(u: UitslagAchtig) -> list[str]:
    return [n for n in (u.lopers or "").split(", ") if n]


def namen_in_rij(u: UitslagAchtig) -> set[str]:
    """Genormaliseerde atleetnamen in een rij: de lopers bij een estafette, anders de atleet."""
    lopers = {normaliseer(n) for n in lopers_lijst(u)} if u.estafette else set()
    return lopers or {normaliseer(u.atleet)}


def filter_vereniging(uitslagen: list, vereniging: str) -> list:
    """
    Individuele uitslagen van atleten van de vereniging, plus estafettes waarin minstens één
    van die atleten liep (de estafetterij zelf noemt vaak een andere club of 'Onbekend').
    """
    past = naam_past([u.vereniging for u in uitslagen], vereniging)
    leden = {normaliseer(u.atleet) for u in uitslagen if not u.estafette and past(u.vereniging)}
    return [u for u in uitslagen if past(u.vereniging)
            or (u.estafette and leden & {normaliseer(n) for n in lopers_lijst(u)})]


def filter_team(uitslagen: list, team: str) -> list:
    """Alle uitslagen (individueel én estafettes) van één competitieteam, bv. 'Nijmegen Heren 1'."""
    past = naam_past([u.team for u in uitslagen], team)
    return [u for u in uitslagen if u.team and past(u.team)]


def filter_atleten(uitslagen: list, namen: list[str]) -> tuple[list, list[str]]:
    """
    Uitslagen van deze atleten, inclusief estafettes waarin ze liepen.
    Geeft (gevonden uitslagen, namen zonder uitslag) terug.
    """
    gezocht = {normaliseer(n): n for n in namen if clean(n)}
    gevonden, aanwezig = [], set()
    for u in uitslagen:
        treffers = namen_in_rij(u) & gezocht.keys()
        if treffers:
            gevonden.append(u)
            aanwezig |= treffers
    return gevonden, [n for k, n in gezocht.items() if k not in aanwezig]


# --------------------------------------------------------------------------- Importer

class Importer(ABC):
    """
    Basisklasse voor importers. Subklassen vullen de klasse-attributen in en implementeren
    parse(); ophalen, opnieuw proberen en opgeslagen bestanden inlezen gebeurt hier.
    """

    # --- in te vullen door subklassen
    bron: ClassVar[str] = ""                  # 'atletieknu' / 'seltec' (kolom 'bron' in de database)
    site: ClassVar[str] = ""                  # naam voor meldingen, bv. "atletiek.nu"
    url_patronen: ClassVar[tuple[str, ...]] = ()   # regexen; één match = can_handle

    # --- ophalen; per subklasse aan te passen
    headers: ClassVar[dict[str, str]] = HEADERS
    timeout: ClassVar[float] = 20             # seconden per verzoek
    pauze: ClassVar[float] = 0.0              # seconden wachten vóór elk vervolgverzoek
    max_pogingen: ClassVar[int] = 4
    eerste_wachttijd: ClassVar[float] = 5.0   # verdubbelt bij elke nieuwe poging
    opnieuw_bij_status: ClassVar[tuple[int, ...]] = (429, 500, 502, 503, 504)
    imiteer_browser: ClassVar[str | None] = None   # bv. "chrome": ophalen via curl_cffi

    _geregistreerd: ClassVar[list[type[Importer]]] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.bron:                          # tussenklassen zonder 'bron' niet registreren
            Importer._geregistreerd.append(cls)

    def __init__(self, log: Callable[..., None] | None = None):
        self.log = log or (lambda *a, **k: None)
        self._sessie: requests.Session | None = None
        self._aantal_verzoeken = 0

    # ----------------------------------------------------------------- interface

    @classmethod
    def can_handle(cls, url: str) -> bool:
        """True als deze importer de link (of id/pad) kan verwerken."""
        return any(re.search(p, url or "", re.I) for p in cls.url_patronen)

    @abstractmethod
    def parse(self, bron: str):
        """
        Importeer alles achter `bron` (URL, id, opgeslagen HTML-bestand of map) en geef de
        uitkomst terug. Wat dat precies is verschilt per importer; zie de subklasse.
        Gooit ImportFout als het niet lukt.
        """

    @classmethod
    def importers(cls) -> list[type[Importer]]:
        """Alle geregistreerde importerklassen, in volgorde van definitie."""
        return list(Importer._geregistreerd)

    # ----------------------------------------------------------------- ophalen

    @property
    def sessie(self):
        """requests.Session, of een curl_cffi-sessie als imiteer_browser is gezet."""
        if self._sessie is None:
            if self.imiteer_browser:
                try:
                    from curl_cffi import requests as curl_requests
                except ImportError as e:
                    raise ImportFout(
                        f"Voor {self.site} is het pakket curl_cffi nodig "
                        "(installeren met: pip install curl_cffi).") from e
                self._sessie = curl_requests.Session(impersonate=self.imiteer_browser)
                # Alleen de taal toevoegen: een eigen User-Agent zou niet passen bij de
                # Chrome-versie die curl_cffi nadoet, en juist dat verschil valt op.
                self._sessie.headers.update({"Accept-Language": self.headers["Accept-Language"]})
            else:
                self._sessie = requests.Session()
                self._sessie.headers.update(self.headers)
        return self._sessie

    def moet_wachten(self, resp) -> bool:
        """True als de site vraagt om rustiger aan te doen of tijdelijk faalt. Overschrijfbaar."""
        return resp.status_code in self.opnieuw_bij_status

    def controleer_pagina(self, html: str, url: str) -> None:
        """Hook: gooi ImportFout als de pagina geen echte inhoud is (bv. een browsercontrole)."""

    def haal_op(self, url: str) -> str:
        """
        Haal een pagina op. Wacht `pauze` seconden tussen verzoeken en probeert bij
        moet_wachten() steeds langer wachtend opnieuw, zodat er niets stilletjes ontbreekt.
        """
        if self._aantal_verzoeken and self.pauze:
            time.sleep(self.pauze)
        self._aantal_verzoeken += 1

        wacht = self.eerste_wachttijd
        for poging in range(1, self.max_pogingen + 1):
            sessie = self.sessie                  # kan zelf ImportFout geven (curl_cffi ontbreekt)
            try:
                resp = sessie.get(url, timeout=self.timeout)
            except Exception as e:                # requests- én curl_cffi-fouten
                raise ImportFout(f"Kan {self.site or url} niet bereiken: {e}") from e
            if not self.moet_wachten(resp):
                break
            if poging == self.max_pogingen:
                raise ImportFout(f"{self.site} blijft weigeren (status {resp.status_code}) voor {url}. "
                                 "Probeer het later opnieuw.")
            retry_after = resp.headers.get("Retry-After", "")
            pauze = float(retry_after) if retry_after.isdigit() else wacht
            print(f"  {self.site} vraagt om rustiger aan te doen - {pauze:.0f} s wachten...", file=sys.stderr)
            time.sleep(pauze)
            wacht *= 2

        if resp.status_code >= 400:
            raise ImportFout(f"{self.site} gaf fout {resp.status_code} voor {url}.")
        if not getattr(resp, "encoding", None):
            try:
                resp.encoding = "utf-8"
            except AttributeError:                # niet instelbaar bij elke bibliotheek
                pass
        html = resp.text
        self.controleer_pagina(html, url)
        return html

    # ----------------------------------------------------------------- opgeslagen pagina's

    @staticmethod
    def is_lokaal(bron: str) -> bool:
        """True als `bron` een bestaand bestand of map is (opgeslagen pagina's)."""
        try:
            pad = Path(bron)
            return pad.is_file() or pad.is_dir()
        except (OSError, ValueError):
            return False

    @staticmethod
    def lees_bestanden(bron: str) -> list[tuple[str, str]]:
        """
        Opgeslagen HTML: één bestand, of alle *.htm(l)-bestanden in een map (gesorteerd).
        Geeft [(file-URI, html), ...]; gooit ImportFout als de map geen HTML bevat.
        """
        pad = Path(bron)
        bestanden = sorted(pad.glob("*.htm*")) if pad.is_dir() else [pad]
        if not bestanden:
            raise ImportFout(f"Geen .html-bestanden gevonden in {pad}")
        return [(f.resolve().as_uri(), f.read_text(encoding="utf-8")) for f in bestanden]
