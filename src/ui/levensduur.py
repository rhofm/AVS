"""Levensduur: AVS stopt vanzelf als er geen pagina meer open is.

De browser meldt niet dat een tabblad dicht gaat, dus elke pagina laat zelf van zich horen
(script in basis.html):

- bij het laden en daarna elke HARTSLAG seconden: POST /levend  (met een id per pagina)
- bij het verlaten (tabblad dicht, of naar een andere pagina): POST /weg  (navigator.sendBeacon)

De Bewaker houdt per pagina-id bij wanneer die voor het laatst van zich liet horen en stopt
de server als:
  * er geen pagina meer open is en er WEG_WACHTTIJD seconden niets meer gebeurde
    (naar een andere pagina gaan = /weg van de oude, /levend van de nieuwe binnen een paar seconden);
  * of een pagina TIJDLIMIET seconden niets liet horen (browser gecrasht of /weg kwam niet aan).
    Ruim gekozen: browsers knijpen timers in achtergrondtabbladen af tot eens per minuut;
  * of er na het starten binnen EERSTE_PAGINA seconden nooit een pagina kwam
    (dan draait AVS anders onzichtbaar door, want er is geen venster meer).

Slaapstand: tijdens de slaap komt er geen hartslag. Ziet de bewaker na het wakker worden een
gat in zijn eigen klok, dan telt iedereen weer als 'net gezien' in plaats van AVS te stoppen.

Stoppen gebeurt nooit midden in een verzoek: de server handelt één verzoek tegelijk af
en stopt pas na het lopende verzoek (werkzeug: server.shutdown()).
"""

from __future__ import annotations

import threading
import time
from typing import Callable

HARTSLAG = 15            # s tussen twee /levend van een open pagina (script in basis.html)
TIJDLIMIET = 150         # s zonder /levend: die pagina telt als dicht
WEG_WACHTTIJD = 8        # s na het laatste teken als er geen pagina meer open is
EERSTE_PAGINA = 300      # s na het starten om de eerste pagina te openen
CONTROLE = 1.0           # s tussen twee controles
SLAAP_GAT = 30           # s: een controle die zoveel te laat is, betekent: de computer sliep


class Bewaker:
    """Houdt open pagina's bij en roept `stop` aan als er geen meer zijn (één keer)."""

    def __init__(self, stop: Callable[[], None], klok: Callable[[], float] = time.monotonic,
                 wandklok: Callable[[], float] = time.time):
        self._stop = stop
        self._klok, self._wandklok = klok, wandklok
        self._slot = threading.Lock()
        self._paginas: dict[str, float] = {}          # pagina-id -> laatst gezien (klok)
        self._gestart = klok()
        self._laatste_teken = self._gestart           # laatste verzoek van welke pagina dan ook
        self._ooit_pagina = False
        self._gestopt = False
        self._vorige_controle = (klok(), wandklok())
        self.reden: str | None = None                 # waarom gestopt (voor tests en de console)

    # ---------------- tekens van de pagina's ----------------
    def levend(self, pagina: str | None) -> None:
        """Een pagina is (nog) open."""
        with self._slot:
            nu = self._klok()
            self._laatste_teken = nu
            if pagina:
                self._paginas[pagina[:64]] = nu
                self._ooit_pagina = True

    def weg(self, pagina: str | None) -> None:
        """Een pagina wordt verlaten (tabblad dicht of naar een andere pagina)."""
        with self._slot:
            self._laatste_teken = self._klok()
            if pagina:
                self._paginas.pop(pagina[:64], None)

    def verzoek(self) -> None:
        """Elk ander verzoek (een pagina laden, opslaan) telt ook als teken van leven."""
        with self._slot:
            self._laatste_teken = self._klok()

    @property
    def open_paginas(self) -> int:
        with self._slot:
            return len(self._paginas)

    # ---------------- beslissen ----------------
    def controleer(self) -> bool:
        """Eén controle; True als AVS nu gestopt is (of al was)."""
        with self._slot:
            if self._gestopt:
                return True
            nu, wand = self._klok(), self._wandklok()
            vorige, vorige_wand = self._vorige_controle
            self._vorige_controle = (nu, wand)
            # Slaapstand: de klok van de bewaker zelf maakte een sprong. Niemand kon iets laten
            # horen, dus niet stoppen: iedereen telt als net gezien.
            if max(nu - vorige, wand - vorige_wand) > SLAAP_GAT:
                for p in self._paginas:
                    self._paginas[p] = nu
                self._laatste_teken = nu
                return False

            for p, gezien in list(self._paginas.items()):
                if nu - gezien > TIJDLIMIET:
                    del self._paginas[p]

            reden = None
            if self._paginas:
                reden = None
            elif self._ooit_pagina:
                if nu - self._laatste_teken >= WEG_WACHTTIJD:
                    reden = "geen pagina meer open"
            elif nu - self._gestart >= EERSTE_PAGINA and nu - self._laatste_teken >= WEG_WACHTTIJD:
                reden = "geen pagina geopend na het starten"
            if reden is None:
                return False
            self._gestopt, self.reden = True, reden
        self._stop()
        return True

    def stop_nu(self, reden: str = "afgesloten via de knop") -> None:
        """Direct stoppen ('AVS afsluiten')."""
        with self._slot:
            if self._gestopt:
                return
            self._gestopt, self.reden = True, reden
        self._stop()

    def draai(self, wacht: Callable[[float], None] = time.sleep) -> None:
        """Blijf controleren tot er gestopt is (in een eigen thread)."""
        while not self.controleer():
            wacht(CONTROLE)

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.draai, name="avs-bewaker", daemon=True)
        t.start()
        return t
