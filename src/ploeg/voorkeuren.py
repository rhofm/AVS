"""Voorkeuren van atleten voor de ploegopstelling.

Twee niveaus (tabellen atleet_voorkeur en ploeg_voorkeur in personen.db):

- **vast, per atleet** (`atleet_voorkeur`): voor alle ploegen, op de naam van
  het onderdeel zonder specificatie ('800 meter', '80 meter horden',
  'Kogelstoten'), zodat hij in elke competitie en categorie geldt. In te stellen
  op de atletenpagina.
- **per ploeg** (`ploeg_voorkeur`): voor één wedstrijd, op de programmasleutel.
  Gaat voor de vaste voorkeur; 'neutraal' zet de vaste voorkeur voor deze ploeg uit.

`effectief()` geeft per (atleet, programmasleutel) wat geldt. Betekenis:

- `wil_niet`: de optimalisatie plant het nooit in; met de hand mag het wel, met
  een waarschuwing.
- `moet`: doet de atleet mee (in de groep waaruit de optimalisatie kiest), dan
  plant de optimalisatie het altijd in, als het voor die atleet kan (niet voor
  het andere geslacht, niet buiten het dagdeel). Te veel 'moet' (meer dan 3
  onderdelen, of tegelijk) geeft een duidelijke fout.
- `voorkeur`: na het eerste doel van de strategie (bij 'Zoveel mogelijk punten':
  de punten) zoveel mogelijk voorkeuren; dat kost dus geen punten, en een atleet
  mag op een voorkeursonderdeel ook als ze daar niet meetelt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from db.queries import Opslag
from models import NEUTRAAL, VOORKEUREN, Ploeg
from ploeg import regels as _regels
from ploeg.regels import RegelFout, Regelset
from ploeg.vergelijk import normaliseer


@dataclass(frozen=True, slots=True)
class Effectief:
    voorkeur: str                  # 'voorkeur', 'wil_niet' of 'moet'
    bron: str                      # 'atleet' (vaste voorkeur) of 'ploeg' (alleen deze ploeg)

    @property
    def tekst(self) -> str:
        return VOORKEUREN[self.voorkeur] + (" (vast)" if self.bron == "atleet" else "")


Voorkeuren = dict[tuple[str, str], Effectief]


def effectief(db: Opslag, regelset: Regelset, ploeg: Ploeg, atleten: Iterable[str]) -> Voorkeuren:
    """Wat er geldt voor deze atleten op het programma van deze ploeg."""
    sleutels = [r.sleutel for r in regelset.programma(ploeg.categorie, ploeg.programma)]
    per_ploeg = db.ploeg_voorkeuren(ploeg.id) if ploeg.id is not None else {}
    uit: Voorkeuren = {}
    for a in dict.fromkeys(atleten):
        vast = {normaliseer(n): v for n, v in db.atleet_voorkeuren(a).items()}
        for e in sleutels:
            p = per_ploeg.get((a, e))
            if p == NEUTRAAL:
                continue
            if p in VOORKEUREN:
                uit[(a, e)] = Effectief(p, "ploeg")
            elif (v := vast.get(normaliseer(regelset.onderdelen[e].naam))) in VOORKEUREN:
                uit[(a, e)] = Effectief(v, "atleet")
    return uit


# ============================================================
# Onderdelen voor de vaste voorkeuren
# ============================================================
GROEPEN = ("Lopen", "Horden en steeple", "Estafettes", "Springen", "Werpen", "Overig")
_GETAL = re.compile(r"\d+")


def _groep(naam: str, estafette: bool) -> str:
    n = naam.lower()
    if estafette:
        return "Estafettes"
    if "horden" in n or "steeple" in n:
        return "Horden en steeple"
    if "meter" in n:
        return "Lopen"
    if "springen" in n:
        return "Springen"
    if any(w in n for w in ("stoten", "werpen", "slingeren")):
        return "Werpen"
    return "Overig"


def onderdeelnamen() -> dict[str, list[str]]:
    """Alle onderdeelnamen uit de regelbestanden, per groep ('Lopen': ['60 meter', ...]).
    Regelbestanden die niet te lezen zijn, worden overgeslagen."""
    gezien: dict[str, tuple[str, str]] = {}
    for bestand in _regels.bestanden():
        try:
            rs = _regels.laad(bestand)
        except RegelFout:
            continue
        for info in rs.onderdelen.values():
            gezien.setdefault(normaliseer(info.naam), (info.naam, _groep(info.naam, info.is_estafette)))
    uit: dict[str, list[str]] = {g: [] for g in GROEPEN}
    for naam, groep in gezien.values():
        uit[groep].append(naam)
    for namen in uit.values():
        namen.sort(key=lambda n: ([int(g) for g in _GETAL.findall(n)] or [0], n.lower()))
    return {g: namen for g, namen in uit.items() if namen}


def lees_atleetformulier(form: Mapping, bekend: Iterable[str]) -> dict[str, str]:
    """Vaste voorkeuren uit het formulier: velden `vk|<onderdeelnaam>` = voorkeur of '' (geen).
    Alleen de namen in `bekend` (de namen op het formulier) worden gelezen."""
    uit = {}
    for naam in bekend:
        v = (form.get(f"vk|{naam}") or "").strip()
        if v in VOORKEUREN:
            uit[naam] = v
    return uit


def lees_ploegformulier(form: Mapping, atleten: Iterable[str], sleutels: Iterable[str]) -> dict[tuple[str, str], str]:
    """Ploegvoorkeuren uit het formulier: velden `vk|<master_id>|<sleutel>` = voorkeur, 'neutraal' of ''
    (= de vaste voorkeur geldt)."""
    sleutels = list(sleutels)
    uit = {}
    for a in atleten:
        for e in sleutels:
            v = (form.get(f"vk|{a}|{e}") or "").strip()
            if v in VOORKEUREN or v == NEUTRAAL:
                uit[(a, e)] = v
    return uit
