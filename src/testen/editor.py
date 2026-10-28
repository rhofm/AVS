"""Het sjabloonformulier: een testsjabloon samenstellen en bewerken zonder JavaScript.

Het formulier wordt na elke knop (rij toevoegen, rij verwijderen, 'Bijwerken' na het kiezen van het
aantal parameters) opnieuw opgebouwd uit wat er is getypt. Daarom is een `Concept` mild: het
bewaart de ruwe tekst en klaagt pas bij `naar_sjabloon()` (de knop Opslaan).

Velden in het formulier (rij i, parameter j, beide vanaf 0):

    naam, slug, totaal (vinkje), totaal_getoond (verborgen: was het vinkje zichtbaar?)
    onderdeel-naam-i, onderdeel-soort-i, onderdeel-formule-i, onderdeel-aantal-i, onderdeel-par-i-j
    actie = bijwerken | rij-toevoegen | weg-i | opslaan
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from .sjabloon import MAX_ONDERDELEN, MAX_PARAMETERS, SOORTEN, Onderdeel, Sjabloon, SjabloonFout


@dataclass
class EditorOnderdeel:
    naam: str = ""
    soort: str = "tijd"
    formule: str = ""
    aantal: int = 0
    parameters: list[str] = field(default_factory=list)       # ruwe tekst, altijd `aantal` lang


@dataclass
class Concept:
    naam: str = ""
    onderdelen: list[EditorOnderdeel] = field(default_factory=lambda: [EditorOnderdeel()])
    totaal_optellen: bool = True
    totaal_getoond: bool = False                               # was het vinkje al zichtbaar in het formulier?
    slug: str = ""

    @property
    def totaal_mogelijk(self) -> bool:
        return sum(1 for o in self.onderdelen if o.formule.strip()) >= 2


def concept_uit_sjabloon(s: Sjabloon) -> Concept:
    c = Concept(s.naam, [EditorOnderdeel(o.naam, o.soort, o.formule, len(o.parameters),
                                         [_tekst(x) for x in o.parameters]) for o in s.onderdelen],
                s.totaal_optellen, True, s.slug)
    return c


def _tekst(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x).replace(".", ",")


def _rijnummers(form: Mapping[str, str]) -> list[int]:
    return sorted({int(m.group(1)) for k in form if (m := re.fullmatch(r"onderdeel-naam-(\d+)", k))})


def concept_uit_formulier(form: Mapping[str, str]) -> Concept:
    """Wat er in het formulier staat, zonder te controleren."""
    rijen = []
    for i in _rijnummers(form)[:MAX_ONDERDELEN]:
        try:
            aantal = max(0, min(MAX_PARAMETERS, int(form.get(f"onderdeel-aantal-{i}", "0") or 0)))
        except ValueError:
            aantal = 0
        soort = form.get(f"onderdeel-soort-{i}", "tijd")
        rijen.append(EditorOnderdeel(
            form.get(f"onderdeel-naam-{i}", ""), soort if soort in SOORTEN else "tijd",
            form.get(f"onderdeel-formule-{i}", ""), aantal,
            [form.get(f"onderdeel-par-{i}-{j}", "") for j in range(aantal)]))
    return Concept(form.get("naam", ""), rijen or [EditorOnderdeel()], "totaal" in form,
                   form.get("totaal_getoond") == "1", form.get("slug", ""))


def pas_toe(c: Concept, actie: str) -> Concept:
    """Voer een knop uit (rij toevoegen/verwijderen of bijwerken) en maak het concept weer kloppend."""
    if actie == "rij-toevoegen" and len(c.onderdelen) < MAX_ONDERDELEN:
        c.onderdelen.append(EditorOnderdeel())
    elif (m := re.fullmatch(r"weg-(\d+)", actie or "")) and len(c.onderdelen) > 1 and int(m.group(1)) < len(c.onderdelen):
        del c.onderdelen[int(m.group(1))]
    return normaliseer(c)


def normaliseer(c: Concept) -> Concept:
    """Parameterlijsten even lang als het gekozen aantal, en het totaalvinkje op zijn plek."""
    for o in c.onderdelen:
        o.aantal = max(0, min(MAX_PARAMETERS, o.aantal))
        o.parameters = (o.parameters + [""] * o.aantal)[:o.aantal]
    if c.totaal_mogelijk and not c.totaal_getoond:
        c.totaal_optellen = True                              # vinkje verschijnt: standaard aan
    c.totaal_getoond = c.totaal_mogelijk
    return c


def naar_sjabloon(c: Concept) -> Sjabloon:
    """Het concept als sjabloon. SjabloonFout met alle punten die niet kloppen."""
    problemen: list[str] = []
    onderdelen = []
    for i, o in enumerate(c.onderdelen, start=1):
        waarden: list[float] = []
        if o.formule.strip():
            for j, t in enumerate(o.parameters[:o.aantal], start=1):
                try:
                    if not t.strip():
                        raise ValueError
                    waarden.append(float(t.strip().replace(",", ".")))
                except ValueError:
                    problemen.append(f"Onderdeel {i}: vul een getal in voor C{j}.")
        onderdelen.append(Onderdeel(o.naam.strip(), o.soort, o.formule.strip(), waarden))
    s = Sjabloon(c.naam.strip(), onderdelen, c.totaal_optellen, c.slug)
    problemen += [p for p in s.problemen() if p not in problemen]
    if problemen:
        raise SjabloonFout(problemen)
    return s
