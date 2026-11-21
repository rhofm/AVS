"""
Een hele groep atleten in één keer toevoegen vanuit een CSV-bestand, inclusief
al hun prestaties van atletiek.nu.

Voor elke regel in de CSV:
  1. de atleet wordt gezocht of aangemaakt in personen.db
     (zelfde werkwijze als src/atleten/atleet_toevoegen_atletieknu.py);
  2. zijn profiel op atletiek.nu wordt opgehaald en alle prestaties gaan
     naar prestaties.db (onder het pseudoniem, zonder naam).
Opnieuw draaien is veilig: bestaande atleten en prestaties worden herkend en
niet dubbel opgeslagen. Mislukt een atleet (bijv. door een browsercontrole van
atletiek.nu), dan gaat de import door met de volgende; de pagina noemt de mislukte regels.

Het CSV-bestand (scheidingsteken ;)
-----------------------------------
Bij voorkeur met een kopregel. Herkende kolomnamen (hoofdletters/spaties maken niet uit):
    voornaam;tussenvoegsel;achternaam;geboortedatum;atletieknu
of met de naam in één kolom:
    naam;geboortedatum;atletieknu
Optioneel: geslacht (M/V/X, man/vrouw; oude 'jongen'/'meisje' blijft leesbaar), club en het licentienummer
van de Atletiekunie (kolom 'licentienummer', 'AU-licentie', 'licentie nr', ...).
In de atletiek.nu-kolom mag het nummer staan of de link naar het profiel.
Het licentienummer wordt alleen gelezen als er een kopregel is (zonder kopregel is
het niet van het atletiek.nu-nummer te onderscheiden). Een bestaande atleet krijgt
het nummer alleen als hij er nog geen heeft; hoort het nummer al bij een andere
atleet, dan wordt die regel niet geïmporteerd.
Geboortedatum: 25-03-2011, 25/03/2011, 2011-03-25 of alleen 2011.

Zonder kopregel wordt op inhoud gekeken: de kolom met het nummer is het
atletiek.nu-nummer, de kolom met een datum de geboortedatum; overige kolommen
zijn de naam (1 kolom: volledige naam, 2: voornaam;achternaam,
3: voornaam;tussenvoegsel;achternaam).

Een naam in één kolom wordt zo gesplitst: 'Jan de Vries' en 'Vries, Jan de'
-> voornaam 'Jan', tussenvoegsel 'de', achternaam 'Vries'. Zonder
tussenvoegsel is het laatste woord de achternaam ('Anne Marie Jansen'). Bij
dubbele achternamen zonder streepje gaat dat mis: gebruik dan aparte kolommen.

Vereist: pip install requests beautifulsoup4 curl_cffi sqlcipher3-wheels keyring
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from atleten.atleet_toevoegen_atletieknu import Uitkomst, voeg_toe
from db.queries import Opslag
from importers.atletieknu_prs import AtletiekNuPRImporter, atleet_id_uit
from importers.base import ImportFout
from models import Atleet

SCHEIDINGSTEKEN = ";"
STANDAARD_PAUZE = 3.0   # seconden tussen twee verzoeken aan atletiek.nu

TUSSENVOEGSELS = {
    "van", "de", "der", "den", "het", "'t", "t", "te", "ten", "ter", "in", "op", "aan",
    "bij", "onder", "over", "uit", "voor", "v", "vd", "v.d.", "d", "d'", "'s", "s",
    "la", "le", "les", "du", "da", "di", "dos", "del", "della", "von", "zu", "el", "al",
}

VELDEN = ("voornaam", "tussenvoegsel", "achternaam", "naam", "geboortedatum",
          "atletieknu_id", "geslacht", "club", "au_licentienummer")


# --------------------------------------------------------------------------- één CSV-regel

@dataclass
class Regel:
    """Eén atleet uit de CSV. `regelnummer` is het regelnummer in het bestand."""
    regelnummer: int
    voornaam: str = field(repr=False)
    achternaam: str = field(repr=False)
    atletieknu_id: str = field(repr=False)
    tussenvoegsel: str | None = field(default=None, repr=False)
    geboortedatum: str | None = field(default=None, repr=False)
    geslacht: str | None = None
    club: str | None = None
    au_licentienummer: str | None = field(default=None, repr=False)

    @property
    def naam(self) -> str:
        return Atleet(self.voornaam, self.achternaam, tussenvoegsel=self.tussenvoegsel).naam


@dataclass
class Leesresultaat:
    regels: list[Regel] = field(default_factory=list)
    fouten: list[tuple[int, str]] = field(default_factory=list)   # (regelnummer, melding)
    kopregel: list[str] | None = None
    kolommen: dict[str, int] = field(default_factory=dict)        # veld -> kolomindex


# --------------------------------------------------------------------------- waarden lezen

def lees_datum(tekst: str) -> str | None:
    """Geboortedatum als 'YYYY-MM-DD' of 'YYYY'. None als het geen datum is."""
    tekst = tekst.strip()
    if not tekst:
        return None
    if re.fullmatch(r"(19|20)\d\d", tekst):
        return tekst
    tekst = tekst.split(" ")[0].split("T")[0]           # '2011-03-25 00:00:00' uit Excel
    for formaat in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            d = datetime.strptime(tekst, formaat).date()
        except ValueError:
            continue
        if 1900 <= d.year <= date.today().year:
            return d.isoformat()
    return None


def lees_geslacht(tekst: str) -> str | None:
    t = tekst.strip().lower()
    if t in ("m", "man", "jongen", "j", "male", "heren", "h"):
        return "M"
    if t in ("v", "vrouw", "meisje", "f", "female", "w", "dames", "d"):
        return "V"
    if t == "x":
        return "X"
    return None


def lees_atletieknu_id(tekst: str) -> str:
    """Nummer uit '123456' of een profiel-link. '' als er geen nummer in staat."""
    tekst = tekst.strip()
    if re.fullmatch(r"\d+(\.0)?", tekst):               # Excel maakt er soms '123456.0' van
        return tekst.split(".")[0]
    return atleet_id_uit(tekst)


def lees_licentienummer(tekst: str) -> str | None:
    """AU-licentienummer: alleen cijfers, spaties weg ('12 34 567' -> '1234567'). None als leeg.

    Excel maakt van een nummer soms '1234567.0'. Iets anders dan cijfers geeft ValueError.
    """
    t = "".join(tekst.split())
    if re.fullmatch(r"\d+\.0", t):
        t = t[:-2]
    if not t:
        return None
    if not t.isdigit():
        raise ValueError(f"onbekend AU-licentienummer {tekst.strip()!r}; alleen cijfers.")
    return t


def splits_naam(volledig: str) -> tuple[str, str | None, str]:
    """'Jan de Vries' / 'Vries, Jan de' / 'de Vries, Jan' -> ('Jan', 'de', 'Vries')."""
    volledig = " ".join(volledig.split())
    if "," in volledig:
        achter, _, voor = (d.strip() for d in volledig.partition(","))
        achter_w, voor_w = achter.split(), voor.split()
        tv = []
        while len(achter_w) > 1 and achter_w[0].lower() in TUSSENVOEGSELS:   # 'de Vries, Jan'
            tv.append(achter_w.pop(0))
        while voor_w and len(voor_w) > 1 and voor_w[-1].lower() in TUSSENVOEGSELS:  # 'Vries, Jan de'
            tv.insert(0, voor_w.pop())
        if not voor_w or not achter_w:
            raise ValueError(f"Kan de naam {volledig!r} niet splitsen.")
        return " ".join(voor_w), (" ".join(tv) or None), " ".join(achter_w)

    woorden = volledig.split()
    if len(woorden) < 2:
        raise ValueError(f"Naam {volledig!r} heeft geen voor- én achternaam.")
    # Eerste tussenvoegsel na de voornaam, met daarna nog minstens één woord.
    for i in range(1, len(woorden) - 1):
        if woorden[i].lower() in TUSSENVOEGSELS:
            j = i
            while j < len(woorden) - 1 and woorden[j].lower() in TUSSENVOEGSELS:
                j += 1
            return " ".join(woorden[:i]), " ".join(woorden[i:j]), " ".join(woorden[j:])
    return " ".join(woorden[:-1]), None, woorden[-1]


# --------------------------------------------------------------------------- kolommen herkennen

def _sleutel(kop: str) -> str:
    return re.sub(r"[^a-z0-9]", "", kop.lower())


def veld_van_kop(kop: str) -> str | None:
    """Welk veld hoort bij deze kolomnaam? None als onbekend."""
    k = _sleutel(kop)
    if not k:
        return None
    # Vóór atletiek.nu: 'Atletiekunie licentienummer' bevat ook 'atletiek'.
    if "licentie" in k or "licence" in k or "license" in k or k in ("aunummer", "aunr", "knaunummer"):
        return "au_licentienummer"
    if "atletiek" in k or k in ("id", "nummer", "nr", "profiel", "link", "url", "anid", "atleetid"):
        return "atletieknu_id"
    if k.startswith("geb") or "birth" in k or k in ("dob", "geboren"):
        return "geboortedatum"
    if k in ("voornaam", "roepnaam", "firstname", "voornamen"):
        return "voornaam"
    if k.startswith("tussenv") or k in ("tv", "voorvoegsel", "prefix", "infix"):
        return "tussenvoegsel"
    if k in ("achternaam", "lastname", "familienaam", "surname"):
        return "achternaam"
    if k in ("naam", "name", "volledigenaam", "atleet", "atleetnaam", "fullname"):
        return "naam"
    if k in ("geslacht", "gender", "sekse", "mv"):
        return "geslacht"
    if k in ("club", "vereniging"):
        return "club"
    return None


def kolommen_uit_kop(kop: list[str]) -> dict[str, int]:
    kolommen: dict[str, int] = {}
    for i, cel in enumerate(kop):
        veld = veld_van_kop(cel)
        if veld and veld not in kolommen:
            kolommen[veld] = i
    return kolommen


def kolommen_uit_inhoud(rij: list[str]) -> dict[str, int]:
    """Zonder kopregel: kolommen raden aan de hand van de eerste regel."""
    kolommen: dict[str, int] = {}
    tekst = []
    for i, cel in enumerate(rij):
        cel = cel.strip()
        if not cel:
            continue
        if "geboortedatum" not in kolommen and lees_datum(cel) and not re.fullmatch(r"\d{5,}", cel):
            kolommen["geboortedatum"] = i
        elif "atletieknu_id" not in kolommen and lees_atletieknu_id(cel):
            kolommen["atletieknu_id"] = i
        elif "geslacht" not in kolommen and lees_geslacht(cel) and len(cel) <= 6:
            kolommen["geslacht"] = i
        else:
            tekst.append(i)
    namen = {1: ("naam",), 2: ("voornaam", "achternaam"),
             3: ("voornaam", "tussenvoegsel", "achternaam")}.get(len(tekst))
    if namen:
        kolommen.update(zip(namen, tekst))
    return kolommen


def is_kopregel(rij: list[str]) -> bool:
    """Een kopregel heeft herkenbare kolomnamen en geen atletiek.nu-nummer of datum."""
    if any(lees_atletieknu_id(c) or lees_datum(c) for c in rij):
        return False
    return len(kolommen_uit_kop(rij)) >= 2


# --------------------------------------------------------------------------- bestand lezen

def lees_tekst(pad: Path) -> str:
    """CSV uit Excel is vaak Windows-1252 i.p.v. UTF-8; probeer beide."""
    data = pad.read_bytes()
    for codering in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(codering)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def lees_csv(bron: Path | str, *, tekst: str | None = None) -> Leesresultaat:
    """Lees de CSV. `tekst` kan in plaats van een bestand worden meegegeven (tests)."""
    if tekst is None:
        tekst = lees_tekst(Path(bron))
    rijen = [(n, rij) for n, rij in enumerate(csv.reader(tekst.splitlines(), delimiter=SCHEIDINGSTEKEN), 1)
             if any(c.strip() for c in rij)]
    uit = Leesresultaat()
    if not rijen:
        uit.fouten.append((0, "Het bestand is leeg."))
        return uit

    if is_kopregel(rijen[0][1]):
        uit.kopregel = rijen[0][1]
        uit.kolommen = kolommen_uit_kop(uit.kopregel)
        rijen = rijen[1:]
    elif len(rijen[0][1]) == 1:
        uit.fouten.append((rijen[0][0], f"Maar één kolom gevonden. Is het scheidingsteken wel '{SCHEIDINGSTEKEN}'?"))
        return uit
    else:
        uit.kolommen = kolommen_uit_inhoud(rijen[0][1])

    k = uit.kolommen
    ontbreekt = []
    if "atletieknu_id" not in k:
        ontbreekt.append("atletiek.nu-nummer")
    if not ("naam" in k or ("voornaam" in k and "achternaam" in k)):
        ontbreekt.append("naam (of voornaam en achternaam)")
    if ontbreekt:
        uit.fouten.append((0, "Kolom(men) niet gevonden: " + ", ".join(ontbreekt) + ". "
                              "Zet bovenaan een kopregel, bv. 'voornaam;tussenvoegsel;achternaam;geboortedatum;atletieknu'."))
        return uit

    def cel(rij: list[str], veld: str) -> str:
        i = k.get(veld)
        return rij[i].strip() if i is not None and i < len(rij) else ""

    gezien: dict[str, int] = {}
    licenties: dict[str, int] = {}
    for n, rij in rijen:
        try:
            if "voornaam" in k and "achternaam" in k:
                voornaam, achternaam = cel(rij, "voornaam"), cel(rij, "achternaam")
                tussenvoegsel = cel(rij, "tussenvoegsel") or None
                if not voornaam or not achternaam:
                    raise ValueError("voor- of achternaam ontbreekt.")
            else:
                voornaam, tussenvoegsel, achternaam = splits_naam(cel(rij, "naam"))

            ruwe_id = cel(rij, "atletieknu_id")
            atletieknu_id = lees_atletieknu_id(ruwe_id)
            if not atletieknu_id:
                raise ValueError(f"geen atletiek.nu-nummer ({ruwe_id!r})." if ruwe_id
                                 else "atletiek.nu-nummer ontbreekt.")

            ruwe_datum = cel(rij, "geboortedatum")
            geboortedatum = lees_datum(ruwe_datum)
            if ruwe_datum and not geboortedatum:
                raise ValueError(f"onbekende geboortedatum {ruwe_datum!r}; gebruik bv. 25-03-2011.")

            ruw_geslacht = cel(rij, "geslacht")
            geslacht = lees_geslacht(ruw_geslacht)
            if ruw_geslacht and not geslacht:
                raise ValueError(f"onbekend geslacht {ruw_geslacht!r}; gebruik M, V of X.")

            licentie = lees_licentienummer(cel(rij, "au_licentienummer"))

            if atletieknu_id in gezien:
                raise ValueError(f"atletiek.nu-nummer {atletieknu_id} staat ook al op regel {gezien[atletieknu_id]}.")
            if licentie is not None and licentie in licenties:
                raise ValueError(f"AU-licentienummer {licentie} staat ook al op regel {licenties[licentie]}.")
            gezien[atletieknu_id] = n
            if licentie is not None:
                licenties[licentie] = n
        except ValueError as fout:
            uit.fouten.append((n, str(fout)))
            continue
        uit.regels.append(Regel(n, voornaam, achternaam, atletieknu_id, tussenvoegsel=tussenvoegsel,
                                geboortedatum=geboortedatum, geslacht=geslacht,
                                club=cel(rij, "club") or None, au_licentienummer=licentie))
    return uit


# --------------------------------------------------------------------------- importeren

class BevestigingNodig(Exception):
    """Er is een atleet met dezelfde naam zonder id en er kan niet gevraagd worden."""


@dataclass
class Verslag:
    gelukt: list[tuple[Regel, Uitkomst]] = field(default_factory=list)
    mislukt: list[tuple[Regel, str]] = field(default_factory=list)


def importeer_regels(db: Opslag, regels: list[Regel], *,
                     haal_html: Callable[[str], str],
                     bevestig: Callable[[Atleet], bool] | None = None,
                     log: Callable[[str], None] = print) -> Verslag:
    """Voeg alle regels toe. `haal_html(atletieknu_id)` levert de profielpagina.

    Een fout bij één atleet stopt de rest niet; die regel komt in verslag.mislukt.
    """
    verslag = Verslag()
    for nr, regel in enumerate(regels, 1):
        kop = f"[{nr}/{len(regels)}] {regel.naam}"
        try:
            _controleer_licentie(db, regel)
            html = haal_html(regel.atletieknu_id)
            u = voeg_toe(db, regel.voornaam, regel.achternaam, regel.atletieknu_id,
                         tussenvoegsel=regel.tussenvoegsel, html=html, bevestig=bevestig,
                         geboortedatum=regel.geboortedatum, geslacht=regel.geslacht, club=regel.club)
            _vul_lege_velden_aan(db, u.atleet, regel)
        except BevestigingNodig as fout:
            verslag.mislukt.append((regel, str(fout)))
            log(f"{kop}: overgeslagen - {fout}")
            continue
        except (ImportFout, ValueError) as fout:
            melding = str(fout).splitlines()[0]
            verslag.mislukt.append((regel, melding))
            log(f"{kop}: MISLUKT - {melding}")
            continue
        verslag.gelukt.append((regel, u))
        status = {"nieuw": "nieuwe atleet", "bestond": "bestond al",
                  "id_toegevoegd": "nummer toegevoegd aan bestaande atleet"}[u.status]
        log(f"{kop}: {status}; prestaties {u.nieuw} nieuw, {u.bekend} al bekend")
    return verslag


def _controleer_licentie(db: Opslag, regel: Regel) -> None:
    """ValueError als het licentienummer al bij een andere atleet hoort (vóór er iets wordt opgeslagen).

    'Een andere atleet' = een atleet met een ander of geen atletiek.nu-nummer. Bij hetzelfde
    nummer is het dezelfde persoon en is er niets aan de hand.
    """
    if regel.au_licentienummer is None:
        return
    eigenaar = db.atleet_op_au_licentienummer(regel.au_licentienummer)
    if eigenaar is not None and eigenaar.atletieknu_id != regel.atletieknu_id:
        raise ValueError(f"AU-licentienummer {regel.au_licentienummer} hoort al bij {eigenaar.naam}"
                         + (f" (atletiek.nu-nummer {eigenaar.atletieknu_id})." if eigenaar.atletieknu_id
                            else " (zonder atletiek.nu-nummer). Vul daar eerst het atletiek.nu-nummer in."))


def _vul_lege_velden_aan(db: Opslag, atleet: Atleet, regel: Regel) -> None:
    """Vul geboortedatum/geslacht/club/licentienummer aan als die bij de atleet nog leeg zijn
    (bij een nieuwe atleet: het licentienummer). Bestaande gegevens worden nooit overschreven."""
    veranderd = False
    for veld in ("geboortedatum", "geslacht", "club", "au_licentienummer"):
        waarde = getattr(regel, veld)
        if waarde and getattr(atleet, veld) is None:
            setattr(atleet, veld, waarde)
            veranderd = True
    if veranderd:
        db.atleet_opslaan(atleet)


def maak_haal_html(pauze: float = STANDAARD_PAUZE) -> Callable[[str], str]:
    """Haalt profielen van atletiek.nu op, met minstens `pauze` seconden tussen twee verzoeken."""
    importer = AtletiekNuPRImporter()
    vorige = [0.0]

    def haal(atletieknu_id: str) -> str:
        wachten = vorige[0] + pauze - time.monotonic()
        if wachten > 0:
            time.sleep(wachten)                 # atletiek.nu niet overbelasten
        try:
            return importer.laad_html(atletieknu_id)
        finally:
            vorige[0] = time.monotonic()
    return haal
