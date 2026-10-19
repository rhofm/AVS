"""Een groep atleten importeren vanuit de app (pagina 'Groep importeren', /importeren/groep).

De trainer vult een tabel in (of plakt een lijst uit Excel): per atleet voornaam,
tussenvoegsel, achternaam, geboortedatum, geslacht, het atletiek.nu-nummer of
de profiel-link, en (optioneel) het AU-licentienummer. Daarvan maakt `maak_csv()` dezelfde CSV als die voor
`groepen/atleten_uit_csv.py`, zodat precies dezelfde controles en dezelfde import
gebruikt worden (`lees_csv` + `importeer_regels`). De CSV bestaat alleen in het
geheugen: er wordt niets met namen of geboortedata naar schijf geschreven.

Daarna komen alle gelukte atleten in een groep:
  * een bestaande groep: ze worden toegevoegd aan de leden (wie er al in zat blijft);
  * een nieuwe groep: die wordt aangemaakt met precies deze atleten.
Een nieuwe atleet krijgt zo ook meteen de trainingsdagen van de groep in zijn
trainingsschema (via `groepen.groep`).

Volgorde, zodat er bij een fout zo weinig mogelijk half gebeurt:
  1. tabel controleren (alle regels) – fout = niets geïmporteerd;
  2. groepkeuze controleren (bestaat de groep / is de nieuwe naam vrij) – fout = niets geïmporteerd;
  3. per atleet het profiel ophalen en importeren; een fout bij één atleet stopt de rest niet;
  4. de gelukte atleten in de groep zetten.

Opnieuw importeren is veilig: bestaande atleten (zelfde atletiek.nu-nummer) en
prestaties worden herkend en niet dubbel opgeslagen. Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping

from atleten.atleet_toevoegen_atletieknu import Uitkomst
from db.queries import Opslag, OpslagFout
from groepen import groep as groepsbeheer
from groepen.atleten_uit_csv import (SCHEIDINGSTEKEN, BevestigingNodig, Leesresultaat, importeer_regels,
                                     lees_csv)
from importers.base import ImportFout
from models import Atleet, Groep

# (veldnaam in formulier en CSV-kop, kop in de tabel, verplicht)
KOLOMMEN: tuple[tuple[str, str, bool], ...] = (
    ("voornaam", "Voornaam", True),
    ("tussenvoegsel", "Tussenv.", False),
    ("achternaam", "Achternaam", True),
    ("geboortedatum", "Geboortedatum", False),
    ("geslacht", "M/V", False),
    ("atletieknu", "atletiek.nu-nummer of link", True),
    ("au_licentienummer", "AU-licentie", False),        # als laatste: oude plak-volgorde blijft werken
)
VELDEN = tuple(k for k, _, _ in KOLOMMEN)

LEGE_RIJEN = 8        # lege regels op een nieuwe pagina
RIJEN_ERBIJ = 5       # 'Regels toevoegen' zonder JavaScript
MAX_RIJEN = 300       # meer regels in één keer is vast een vergissing (en duurt erg lang)

Dubbel = Literal["overslaan", "zelfde", "nieuw"]
DUBBEL_KEUZES: tuple[tuple[str, str, str], ...] = (
    ("overslaan", "Overslaan en melden",
     "Die atleet wordt niet geïmporteerd; je ziet daarna wie het was en kunt het opnieuw proberen."),
    ("zelfde", "Het is dezelfde persoon",
     "De bestaande atleet krijgt het atletiek.nu-nummer en de prestaties."),
    ("nieuw", "Altijd een nieuwe atleet maken",
     "Ook als er al iemand met dezelfde naam is."),
)


class TabelFout(OpslagFout):
    """De tabel klopt niet. `fouten`: {rij-index (0 = eerste ingevulde regel): melding};
    `algemeen`: fout die niet bij één regel hoort."""

    def __init__(self, fouten: dict[int, str], algemeen: str | None = None):
        self.fouten = fouten
        self.algemeen = algemeen
        n = len(fouten)
        super().__init__(algemeen or f"{n} {'regel klopt' if n == 1 else 'regels kloppen'} nog niet; "
                                     "zie de rode meldingen in de tabel.")


# --------------------------------------------------------------------------- tabel

Rij = dict[str, str]


def lege_rij() -> Rij:
    return {v: "" for v in VELDEN}


def is_leeg(rij: Rij) -> bool:
    return not any(rij.get(v, "").strip() for v in VELDEN)


def rijen_uit_formulier(formulier) -> list[Rij]:
    """De ingevulde regels uit het formulier (velden komen per kolom als lijst binnen).
    Lege regels vallen weg; spaties aan begin en eind ook."""
    kolommen = {v: formulier.getlist(v) for v in VELDEN}
    aantal = max((len(w) for w in kolommen.values()), default=0)
    rijen = []
    for i in range(aantal):
        rij = {v: " ".join((kolommen[v][i] if i < len(kolommen[v]) else "").split()) for v in VELDEN}
        if not is_leeg(rij):
            rijen.append(rij)
    return rijen


def aangevuld(rijen: list[Rij], minimaal: int = LEGE_RIJEN, erbij: int = 2) -> list[Rij]:
    """Regels voor het formulier: de ingevulde plus een paar lege, minstens `minimaal`."""
    uit = [dict(r) for r in rijen]
    uit += [lege_rij() for _ in range(max(erbij, minimaal - len(uit)))]
    return uit


def maak_csv(rijen: list[Rij]) -> str:
    """De tabel als CSV-tekst (met kopregel, scheidingsteken ;) voor atleten_uit_csv.lees_csv.
    Alleen in het geheugen; csv.writer zet aanhalingstekens om waarden met ; of ".
    """
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=SCHEIDINGSTEKEN, lineterminator="\n")
    w.writerow(VELDEN)
    for r in rijen:
        w.writerow([r.get(v, "") for v in VELDEN])
    return buf.getvalue()


def controleer(rijen: list[Rij]) -> Leesresultaat:
    """Lees de tabel zoals een CSV. Fout (TabelFout) als er geen regels zijn of als een regel niet klopt."""
    if not rijen:
        raise TabelFout({}, "Vul minstens één atleet in.")
    if len(rijen) > MAX_RIJEN:
        raise TabelFout({}, f"Te veel regels ({len(rijen)}); importeer maximaal {MAX_RIJEN} atleten tegelijk.")
    lees = lees_csv("tabel", tekst=maak_csv(rijen))
    fouten: dict[int, str] = {}
    algemeen = None
    for regelnummer, melding in lees.fouten:
        if regelnummer >= 2:                       # regel 1 is de kopregel
            fouten[regelnummer - 2] = _netjes(melding)
        else:
            algemeen = melding
    if fouten or algemeen:
        raise TabelFout(fouten, algemeen)
    return lees


def _netjes(melding: str) -> str:
    """'voor- of achternaam ontbreekt.' -> 'Voor- of achternaam ontbreekt.'; regelnummers uit de CSV
    ('staat ook al op regel 3') worden regels in de tabel ('regel 2')."""
    melding = re.sub(r"op regel (\d+)", lambda m: f"op regel {int(m.group(1)) - 1}", melding)
    return melding[:1].upper() + melding[1:]


# --------------------------------------------------------------------------- groepkeuze

@dataclass
class Groepkeuze:
    soort: Literal["bestaand", "nieuw"] = "bestaand"
    groep_id: int | None = None
    naam: str = ""
    seizoen: str = ""


def lees_groepkeuze(formulier: Mapping[str, str]) -> Groepkeuze:
    soort = "nieuw" if formulier.get("groepsoort") == "nieuw" else "bestaand"
    groep = (formulier.get("groep_id") or "").strip()
    return Groepkeuze(soort, int(groep) if groep.isdigit() else None,
                      " ".join((formulier.get("groepnaam") or "").split()),
                      " ".join((formulier.get("seizoen") or "").split()))


def controleer_groepkeuze(db: Opslag, k: Groepkeuze) -> Groep | None:
    """Bestaande groep: die groep (fout als hij niet bestaat). Nieuwe groep: None (fout bij
    een lege naam of een naam die in dat seizoen al bestaat)."""
    if k.soort == "bestaand":
        g = db.groep(k.groep_id) if k.groep_id is not None else None
        if g is None:
            raise OpslagFout("Kies de groep waar de atleten in komen.")
        return g
    groepsbeheer._controleer_gegevens(db, k.naam, k.seizoen)    # zelfde regels als 'Nieuwe groep'
    return None


# --------------------------------------------------------------------------- importeren

@dataclass
class Regeluitkomst:
    index: int                  # rij in de tabel (0 = eerste ingevulde regel)
    rij: Rij
    uitkomst: Uitkomst | None = None
    reden: str | None = None    # bij mislukt

    @property
    def gelukt(self) -> bool:
        return self.uitkomst is not None

    @property
    def status(self) -> str:
        if self.uitkomst is None:
            return "Niet geïmporteerd"
        return {"nieuw": "Nieuwe atleet", "bestond": "Stond er al",
                "id_toegevoegd": "Nummer toegevoegd aan bestaande atleet"}[self.uitkomst.status]


@dataclass
class Resultaat:
    regels: list[Regeluitkomst] = field(default_factory=list)
    groep: Groep | None = None
    groep_nieuw: bool = False
    in_groep_erbij: list[Atleet] = field(default_factory=list)    # nieuw in de groep gekomen
    al_in_groep: int = 0                                          # zaten er al in

    @property
    def gelukt(self) -> list[Regeluitkomst]:
        return [r for r in self.regels if r.gelukt]

    @property
    def mislukt(self) -> list[Regeluitkomst]:
        return [r for r in self.regels if not r.gelukt]

    @property
    def nieuwe_atleten(self) -> int:
        return sum(1 for r in self.gelukt if r.uitkomst.status == "nieuw")

    @property
    def nieuwe_prestaties(self) -> int:
        return sum(r.uitkomst.nieuw for r in self.gelukt)

    @property
    def tekst(self) -> str:
        """Korte samenvatting voor bovenaan de pagina (zonder namen)."""
        n = len(self.gelukt)
        zinnen = [f"{n} van de {len(self.regels)} {'atleet' if len(self.regels) == 1 else 'atleten'} "
                  f"geïmporteerd ({self.nieuwe_atleten} nieuw, {self.nieuwe_prestaties} nieuwe prestaties)."]
        if self.groep is not None:
            if self.groep_nieuw:
                zinnen.append(f"Groep {self.groep.naam} aangemaakt met {len(self.in_groep_erbij)} "
                              f"{'atleet' if len(self.in_groep_erbij) == 1 else 'atleten'}.")
            else:
                zin = f"{len(self.in_groep_erbij)} toegevoegd aan groep {self.groep.naam}"
                if self.al_in_groep:
                    zin += f" ({self.al_in_groep} zat{'' if self.al_in_groep == 1 else 'en'} er al in)"
                zinnen.append(zin + ".")
        elif n == 0:
            zinnen.append("Er is geen groep aangemaakt of gewijzigd.")
        if self.mislukt:
            zinnen.append(f"{len(self.mislukt)} niet gelukt: die regels staan hieronder weer in de tabel.")
        return " ".join(zinnen)


def maak_bevestig(dubbel: str) -> Callable[[Atleet], bool] | None:
    """Wat te doen als er al een atleet met dezelfde naam is zonder atletiek.nu-nummer."""
    if dubbel == "zelfde":
        return lambda _kandidaat: True
    if dubbel == "nieuw":
        return None                                  # voeg_toe maakt dan een nieuwe atleet

    def overslaan(kandidaat: Atleet) -> bool:
        raise BevestigingNodig(f"er bestaat al een atleet {kandidaat.naam} zonder atletiek.nu-nummer. "
                               "Kies bij 'Zelfde naam' wat er moet gebeuren en importeer deze regel opnieuw.")
    return overslaan


def veilig_ophalen(haal_html: Callable[[str], str]) -> Callable[[str], str]:
    """Netwerkfouten e.d. worden een ImportFout, zodat één atleet de rest niet stopt."""
    def haal(atletieknu_id: str) -> str:
        try:
            return haal_html(atletieknu_id)
        except ImportFout:
            raise
        except Exception as e:                      # noqa: BLE001 – geen verbinding, time-out, ...
            raise ImportFout("atletiek.nu is niet bereikbaar (geen internet of de site reageert niet). "
                             "Probeer het later opnieuw.") from e
    return haal


def importeren(db: Opslag, rijen: list[Rij], keuze: Groepkeuze, *,
               haal_html: Callable[[str], str], dubbel: str = "overslaan") -> Resultaat:
    """Controleer de tabel en de groepkeuze, importeer alle atleten en zet de gelukte in de groep.

    TabelFout / OpslagFout als de tabel of de groepkeuze niet klopt; dan is er niets veranderd.
    """
    lees = controleer(rijen)
    groep = controleer_groepkeuze(db, keuze)

    verslag = importeer_regels(db, lees.regels, haal_html=veilig_ophalen(haal_html),
                               bevestig=maak_bevestig(dubbel), log=lambda _: None)
    per_regel: dict[int, Regeluitkomst] = {}
    for regel, u in verslag.gelukt:
        i = regel.regelnummer - 2
        per_regel[i] = Regeluitkomst(i, rijen[i], uitkomst=u)
    for regel, reden in verslag.mislukt:
        i = regel.regelnummer - 2
        per_regel[i] = Regeluitkomst(i, rijen[i], reden=_netjes(reden))
    res = Resultaat([per_regel[i] for i in sorted(per_regel)])

    ids = list(dict.fromkeys(r.uitkomst.atleet.master_id for r in res.gelukt))
    if not ids:
        return res
    if groep is None:
        res.groep = groepsbeheer.groep_aanmaken(db, keuze.naam, keuze.seizoen, ids)
        res.groep_nieuw = True
        res.in_groep_erbij = [db.atleet(m) for m in ids]
    else:
        al = set(groep.leden)
        w = groepsbeheer.leden_opslaan(db, groep.id, [*groep.leden, *(m for m in ids if m not in al)])
        res.groep = db.groep(groep.id)
        res.in_groep_erbij = w.toegevoegd
        res.al_in_groep = sum(1 for m in ids if m in al)
    return res
