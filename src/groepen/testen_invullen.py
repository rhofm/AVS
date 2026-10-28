"""Testresultaten van een hele groep in één keer invullen (pagina 'Testresultaten invullen' van een groep).

De trainer kiest een testsjabloon en ziet daarna alle atleten van de groep met hun laatste resultaat en
lege velden, één per onderdeel van de test. Eén formulier, één datum. Atleten waarvan niets is
ingevuld worden overgeslagen. Klopt de invoer van één atleet niet, dan wordt er van niemand iets
opgeslagen en staat de fout bij de betreffende atleet; de rest van de invoer blijft in het formulier staan.

Geen SQL: alles via `Opslag`. Het uitrekenen en opslaan zelf gebruikt dezelfde regels als op de
pagina van één atleet (`testen.resultaten`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping

from atleten.landingspagina import categorie_code, leeftijdscategorie
from db.queries import Opslag, OpslagFout
from instellingen import naam_tekst
from models import Atleet, Groep, Testresultaat
from testen import resultaten
from testen.sjabloon import Bibliotheek, Sjabloon

VELD_PREFIX = "waarde-"


def veldnaam(master_id: str, deel: int) -> str:
    return f"{VELD_PREFIX}{master_id}-{deel}"


class GroepInvoerFout(OpslagFout):
    """Invoer die niet klopt. `fouten` = {master_id: uitleg}; `algemeen` = een fout die niet bij één atleet hoort."""

    def __init__(self, fouten: dict[str, str] | None = None, algemeen: str | None = None):
        self.fouten = fouten or {}
        self.algemeen = algemeen
        tekst = algemeen or f"De invoer van {len(self.fouten)} atleet{'en' if len(self.fouten) != 1 else ''} klopt niet."
        super().__init__(tekst)


@dataclass
class InvulRij:
    atleet: Atleet
    categorie: str | None                          # leeftijdscategorie (U14, ...)
    laatste: resultaten.ResultaatRegel | None      # laatste resultaat op deze test
    invoer: list[str]                              # wat er in elk veld staat (leeg = niets)
    fout: str | None = None

    @property
    def categorie_code(self) -> str | None:
        return categorie_code(self.categorie, self.atleet.geslacht)


@dataclass
class InvulPagina:
    groep: Groep
    bibliotheek: Bibliotheek
    sjabloon: Sjabloon | None                      # None = nog niets gekozen
    rijen: list[InvulRij] = field(default_factory=list)
    vandaag: date = field(default_factory=date.today)

    @property
    def met_laatste(self) -> int:
        return sum(1 for r in self.rijen if r.laatste)


def _leden(db: Opslag, groep: Groep, vandaag: date) -> list[tuple[Atleet, str | None]]:
    uit = []
    for mid in groep.leden:
        a = db.atleet(mid)
        if a is not None:
            uit.append((a, leeftijdscategorie(a, vandaag)))
    uit.sort(key=lambda x: naam_tekst(x[0]))
    return uit


def invulpagina(db: Opslag, groep: Groep, bibliotheek: Bibliotheek, slug: str | None = None, *,
                formulier: Mapping[str, str] | None = None, fouten: Mapping[str, str] | None = None,
                peildatum: date | None = None) -> InvulPagina:
    """De keuzelijst en, bij een gekozen sjabloon, de atleten met hun laatste resultaat en lege (of teruggezette) velden.

    Een onbekend sjabloon in `slug` geeft een OpslagFout.
    """
    vandaag = peildatum or date.today()
    if not slug:
        return InvulPagina(groep, bibliotheek, None, vandaag=vandaag)
    bron = bibliotheek.vind(slug)
    if bron is None:
        raise OpslagFout(f"Testsjabloon {slug!r} bestaat niet.")
    s = bron.sjabloon
    test = db.test_op_sjabloon(s.slug)
    rijen = []
    for a, cat in _leden(db, groep, vandaag):
        regels = resultaten.resultaatregels(db, a.master_id, bibliotheek=bibliotheek, test_id=test.id) if test else []
        invoer = [(formulier or {}).get(veldnaam(a.master_id, i), "") for i in range(len(s.onderdelen))]
        rijen.append(InvulRij(a, cat, regels[0] if regels else None, invoer, (fouten or {}).get(a.master_id)))
    return InvulPagina(groep, bibliotheek, s, rijen, vandaag)


def resultaten_opslaan(db: Opslag, groep: Groep, s: Sjabloon, formulier: Mapping[str, str], datum: date) -> int:
    """Verwerk het formulier. Geeft het aantal opgeslagen resultaten.

    Velden heten 'waarde-<master_id>-<i>'. Alleen leden van de groep tellen; een veld van iemand die
    er niet in zit is een fout en dan wordt er niets opgeslagen. Een atleet met alleen lege velden
    wordt overgeslagen. Eerst wordt alle invoer gecontroleerd; pas als alles klopt wordt er opgeslagen.
    """
    for veld in formulier:
        if veld.startswith(VELD_PREFIX) and veld[len(VELD_PREFIX):].rpartition("-")[0] not in groep.leden:
            raise GroepInvoerFout(algemeen="Een van de atleten zit niet (meer) in deze groep.")
    klaar: list[tuple[str, tuple]] = []
    fouten: dict[str, str] = {}
    for mid in groep.leden:
        invoer = [str(formulier.get(veldnaam(mid, i), "")).strip() for i in range(len(s.onderdelen))]
        if not any(invoer):
            continue
        try:
            klaar.append((mid, resultaten.uitrekenen(s, datum, invoer)))
        except OpslagFout as e:
            fouten[mid] = str(e)
    if fouten:
        raise GroepInvoerFout(fouten)
    if not klaar:
        raise GroepInvoerFout(algemeen="Er is niets ingevuld.")
    test = resultaten.test_voor_sjabloon(db, s)
    for mid, (hoofd, score, delen) in klaar:
        db.testresultaat_opslaan(Testresultaat(mid, test.id, datum, hoofd, None, score=score, delen=delen))
    return len(klaar)
