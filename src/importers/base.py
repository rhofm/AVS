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
ImportFout gegooid, met een melding die de UI direct aan de gebruiker toont.
"""

from __future__ import annotations

import re
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, ClassVar

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}


#: Wat atletiek.nu in plaats van de pagina toont aan programma's die hij niet vertrouwt.
BROWSERCONTROLE = "Checking your browser"


class ImportFout(Exception):
    """Importeren lukt niet; de tekst is bedoeld voor de gebruiker."""


# --------------------------------------------------------------------------- hulpfuncties

def clean(text: str) -> str:
    """Witruimte (ook harde spaties) samenvoegen tot enkele spaties en afknippen."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


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

    # --- browsercontrole (controleer_pagina): tekst die alleen op een echte pagina staat, en
    #     wat de trainer dan kan doen. Leeg = niet controleren.
    echte_inhoud: ClassVar[tuple[str, ...]] = ()
    browsercontrole_uitleg: ClassVar[str] = (
        "Open de pagina in je browser, sla hem op (Ctrl+S, 'Alleen HTML') en importeer dat bestand.")

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
        """ImportFout als de site een browsercontrole gaf in plaats van de pagina: dan staat
        BROWSERCONTROLE erop en geen van `echte_inhoud`. Overschrijfbaar voor andere controles."""
        if self.echte_inhoud and BROWSERCONTROLE in html and not any(t in html for t in self.echte_inhoud):
            raise ImportFout(f"{self.site} gaf een browsercontrole-pagina terug voor {url}.\n"
                             f"{self.browsercontrole_uitleg}")

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
            pauze = float(retry_after) if retry_after.isdecimal() else wacht
            print(f"  {self.site} vraagt om rustiger aan te doen - {pauze:.0f} s wachten...", file=sys.stderr)
            time.sleep(pauze)
            wacht *= 2

        if resp.status_code == 403:
            raise ImportFout(f"{self.site} weigert AVS (fout 403) voor {url}. Meestal is dit een tijdelijke blokkade "
                             "na veel verzoeken kort achter elkaar: wacht een tijdje, of gebruik de opgeslagen pagina.\n"
                             f"{self.browsercontrole_uitleg}")
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
