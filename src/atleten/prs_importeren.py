"""PR's van één atleet bijwerken vanaf atletiek.nu (knop 'PR's ophalen' op de atletenpagina).

Haalt het atletiek.nu-profiel op via het nummer dat al bij de atleet staat
(`atleet.atletieknu_id`), en slaat alle prestaties op met
`atleten.importeer_atletieknu.importeer`. De PR's volgen daarna vanzelf uit de
view `pr`. Opnieuw ophalen is veilig: prestaties die er al staan worden
overgeslagen.

Het ophalen zelf (`haal_html(atletieknu_id) -> html`) wordt meegegeven, zodat
tests een opgeslagen, geanonimiseerde pagina kunnen gebruiken. Netwerkfouten
worden een `ImportFout` met een begrijpelijke melding. Geen SQL: alles via `Opslag`.
Er wordt niets gelogd of bewaard van de pagina zelf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from db.queries import Opslag, OpslagFout
from importers.atletieknu_prs import atleet_id_uit, parse_results
from importers.base import ImportFout

from .importeer_atletieknu import importeer

__all__ = ["GeenNummer", "PRImport", "prs_importeren"]


class GeenNummer(OpslagFout):
    """De atleet heeft (nog) geen atletiek.nu-nummer."""


@dataclass
class PRImport:
    nieuw: int                         # nieuwe prestaties
    bekend: int                        # stonden er al
    overgeslagen: int                  # DNF, DNS e.d.
    nieuwe_prs: list[str] = field(default_factory=list)    # onderdelen met een nieuw of beter PR

    @property
    def tekst(self) -> str:
        """Melding voor bovenaan de atletenpagina."""
        if not self.nieuw:
            return "PR's opgehaald van atletiek.nu: geen nieuwe prestaties."
        delen = [f"PR's opgehaald van atletiek.nu: {self.nieuw} nieuwe "
                 f"{'prestaties' if self.nieuw != 1 else 'prestatie'}"]
        if self.nieuwe_prs:
            n = len(self.nieuwe_prs)
            woord = "nieuw PR" if n == 1 else "nieuwe PR's"
            delen.append(f"{n} {woord} ({', '.join(self.nieuwe_prs)})")
        else:
            delen.append("geen nieuwe PR's")
        return ", ".join(delen) + "."


def prs_importeren(db: Opslag, master_id: str, haal_html: Callable[[str], str]) -> PRImport:
    """Haal het atletiek.nu-profiel van de atleet op en sla de prestaties op.

    Fouten: OpslagFout (atleet bestaat niet), GeenNummer (geen atletiek.nu-nummer),
    ImportFout (niet bereikbaar, verkeerde of onleesbare pagina). Bij een fout is er niets opgeslagen.
    """
    atleet = db.atleet(master_id)
    if atleet is None:
        raise OpslagFout(f"Atleet {master_id} bestaat niet.")
    nummer = (atleet.atletieknu_id or "").strip()
    if not nummer:
        raise GeenNummer(f"Bij {atleet.voornaam} staat nog geen atletiek.nu-nummer. "
                         "Vul het in bij 'Gegevens aanpassen'.")
    try:
        html = haal_html(nummer)
    except ImportFout:
        raise
    except Exception as e:                      # noqa: BLE001 – geen verbinding, time-out, ...
        raise ImportFout("atletiek.nu is niet bereikbaar (geen internet of de site reageert niet). "
                         "Probeer het later opnieuw.") from e
    in_pagina = atleet_id_uit("", html)
    if in_pagina and in_pagina != nummer:
        raise ImportFout(f"atletiek.nu gaf een ander profiel terug ({in_pagina} in plaats van {nummer}). "
                         "Er is niets opgeslagen.")
    try:
        resultaten = parse_results(html)
    except ValueError as e:
        raise ImportFout(f"De pagina van atletiek.nu is niet te lezen als profiel van {nummer}. "
                         "Klopt het nummer?") from e

    voor = {pr.onderdeel_id: pr.waarde for pr in db.prs(master_id)}
    nieuw, bekend, overgeslagen = importeer(db, master_id, resultaten)
    beter = [pr.onderdeel_id for pr in db.prs(master_id) if voor.get(pr.onderdeel_id) != pr.waarde]
    namen = sorted((o.naam for o in (db.onderdeel(i) for i in beter) if o is not None), key=str.lower)
    return PRImport(nieuw, bekend, overgeslagen, namen)
