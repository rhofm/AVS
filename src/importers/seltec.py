"""
Importer voor wedstrijduitslagen van Seltec (uitslagen.atletiek.nl en andere Seltec LA-portals):
haal de uitslagen van een wedstrijd op voor een groep atleten of voor alle atleten van een
vereniging, en exporteer ze naar CSV/JSON.

Werkwijze: het uitslagenoverzicht van de wedstrijd (/Competitions/Resultoverview/<id>) bevat
álle uitslagen van alle onderdelen op één pagina. Die pagina wordt één keer opgehaald; elke
rij in elk onderdeelblok wordt een Uitslag, daarna wordt gefilterd.

Gebruik:
    python seltec.py 19133 --vereniging "Nijmegen Atletiek"
    python seltec.py https://uitslagen.atletiek.nl/Competitions/Resultoverview/19133 \\
        --atleten "Tim Proefmans" "Bas Proefmans" "Lotte Testerink"
    python seltec.py https://uitslagen.atletiek.nl/Competitions/CurrentList/982650/19133 --alles
                                                            # alleen dit ene onderdeel
    python seltec.py 19133 --atleten-bestand groep.txt      # één naam per regel
    python seltec.py 19133 --alles                          # iedereen
    python seltec.py opgeslagen.html --vereniging Nijmegen  # opgeslagen uitslagenoverzicht
    python seltec.py 19133 --vereniging Nijmegen --csv uitslagen.csv --json uitslagen.json

Vereist: pip install requests beautifulsoup4
"""

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

try:                                    # als pakket: from src.importers import seltec
    from .base import (Importer, ImportFout, clean, filter_atleten, filter_vereniging,
                       to_number, write_csv)
except ImportError:                     # als script: python seltec.py ...
    from base import (Importer, ImportFout, clean, filter_atleten, filter_vereniging,  # type: ignore
                      to_number, write_csv)

BASIS_URL = "https://uitslagen.atletiek.nl"
OVERZICHT_PAD = "/Competitions/Resultoverview/{id}"

MAANDEN_KORT = {m: i for i, m in enumerate(
    ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"], start=1)}
MAANDEN_KORT.update({"mar": 3, "may": 5, "oct": 10})   # Engelstalige portals


@dataclass
class Wedstrijd:
    wedstrijd_id: str       # Seltec competition-id, bv. "19133"
    naam: str               # bv. "ASICS NK U18 & U20"
    datum: str              # ISO, eerste dag
    einddatum: str          # ISO, laatste dag (gelijk aan datum bij een eendaagse wedstrijd)
    plaats: str             # bv. "Utrecht"
    url: str


@dataclass
class Uitslag:
    # Zelfde velden als atletieknu_wedstrijd.Uitslag (zodat beide importers dezelfde CSV geven),
    # aangevuld met wat Seltec extra toont: geboortejaar, kwalificatie en opmerking.
    atleet: str             # naam zoals op de site, bv. "Tim Proefmans" (zonder toevoeging als "[GK]")
    deelnemer_id: str       # Seltec data-id van de rij (GUID, per uitslag, NIET per atleet)
    startnummer: str        # bv. "647"
    vereniging: str         # bv. "Nijmegen Atletiek"
    vereniging_id: str      # Seltec toont geen verenigings-id: altijd ""
    team: str               # Seltec kent geen competitieteams: altijd ""
    estafette: bool         # True = één rij voor het hele estafetteteam
    lopers: str             # alleen bij estafettes, als Seltec ze toont
    categorie: str          # Seltec-code, bv. "U18M", "U20V", "MSEN"
    onderdeel: str          # bv. "100 m", "Hink-stap-springen", "110 m horden"
    onderdeel_code: str     # Seltec lijst-id van dit onderdeel/deze ronde, bv. "982650"
    specificatie: str       # gewicht / hordehoogte als die in de titel staat (meestal leeg)
    ronde: str              # bv. "Series", "Halve finales", "Finale", "Kwalificatie"
    positie: str            # plaats in de uitslag van deze ronde ("" bij DNS/DNF e.d.)
    prestatie: str          # zoals op de site: "11,74", "4:19,57", "DNF", "nm."
    waarde: float | None    # seconden / meters / punten (None bij DNF, DNS, DQ, nm., ...)
    wind: str               # bv. "+0,8 m/s" (leeg als niet gemeten / niet van toepassing)
    punten: int | None      # meerkamppunten als Seltec ze toont (anders None)
    record: str             # bv. "PB", "SB", "=PB", "CR,DL" (leeg als niets)
    pogingen: str           # technische nummers: "5,29 (+1,2) | x | 5,11 (+0,4)" of "1,46 O | 1,51 XO"
    wedstrijd: str
    datum: str              # dag van dit onderdeel (Seltec toont per onderdeel een datum)
    plaats: str
    uitslag_url: str        # url van de onderdeellijst (/Competitions/CurrentList/<lijst>/<wedstrijd>)
    geboortejaar: str       # bv. "2009" ("" als niet vermeld)
    kwalificatie: str       # "Q", "q", "q+", "v" (vrijgesteld/afgemeld) of ""
    opmerking: str          # overige info van de site, bv. "TR16.8 (false start)", "GK"


# --------------------------------------------------------------------------- helpers

# clean en to_number komen uit base.py.

def wind_tekst(tekst: str) -> str:
    """'(+1,5)' / '+2,1' -> '+1,5 m/s' ('' als er geen windgetal in staat)."""
    m = re.search(r"([+-]?\d+[.,]\d+)", tekst or "")
    return f"{m.group(1).replace('.', ',')} m/s" if m else ""


def parse_datum_kort(tekst: str) -> str:
    """'18.09.2026 14:00 ...' -> '2026-09-18' ('' als het niet lukt)."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", tekst or "")
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat() if m else ""


def wedstrijd_id_uit_url(url: str) -> str:
    """
    '/Competitions/Resultoverview/19133'      -> '19133'
    '/Competitions/CurrentList/982650/19133'  -> '19133'  (laatste getal = wedstrijd)
    '/Competitions/Details/19133/2'           -> '19133'  (tijdschema van dag 2)
    """
    m = (re.search(r"/Competitions/Details/(\d+)", url or "")
         or re.search(r"/Competitions/[A-Za-z]+/(?:\d+/)?(\d+)", url or ""))
    return m.group(1) if m else ""


def lijst_id_uit_url(url: str) -> str:
    """'/Competitions/CurrentList/982650/19133' -> '982650' (anders '')."""
    m = re.search(r"/Competitions/CurrentList/(\d+)/\d+", url or "")
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- wedstrijd
#
# Kop van het uitslagenoverzicht:
#   <h1 ...><div style="flex: 1;">18 - 20 sep 2026 ASICS NK U18 &amp; U20 - Utrecht</div>...</h1>
# Varianten: "20 sep 2026 Naam - Plaats" (één dag), "30 sep - 2 okt 2026 Naam - Plaats".

KOP_DATUM_RE = re.compile(
    r"^(?P<d1>\d{1,2})(?:\s+(?P<m1>[a-z]{3})[a-z]*)?(?:\s+(?P<j1>\d{4}))?"
    r"(?:\s*-\s*(?P<d2>\d{1,2})\s+(?P<m2>[a-z]{3})[a-z]*\s+(?P<j2>\d{4}))?\s+(?P<rest>.*)$",
    re.I)


def _maak_datum(dag: str, maand: str, jaar: str) -> str:
    try:
        return date(int(jaar), MAANDEN_KORT[maand.lower()], int(dag)).isoformat()
    except (KeyError, ValueError, TypeError):
        return ""


def parse_wedstrijd(soup: BeautifulSoup, url: str = "", blok_datums: list[str] | None = None) -> Wedstrijd:
    kop = soup.find("h1")
    tekst = clean(kop.get_text()) if kop else ""
    naam, plaats, dagen = tekst, "", []

    m = KOP_DATUM_RE.match(tekst)
    if m:
        rest = m.group("rest")
        if m.group("d2"):                         # meerdaags
            j1 = m.group("j1") or m.group("j2")
            m1 = m.group("m1") or m.group("m2")
            dagen = [_maak_datum(m.group("d1"), m1, j1), _maak_datum(m.group("d2"), m.group("m2"), m.group("j2"))]
        elif m.group("m1") and m.group("j1"):     # eendaags
            dagen = [_maak_datum(m.group("d1"), m.group("m1"), m.group("j1"))]
        else:
            rest = tekst
        naam, sep, plaats = rest.rpartition(" - ")
        if not sep:
            naam, plaats = rest, ""

    # De datums per onderdeel zijn betrouwbaarder dan de kop (en werken ook als de kop afwijkt).
    dagen = sorted(d for d in (blok_datums or []) if d) or [d for d in dagen if d]
    if not naam and soup.title:
        naam = clean(soup.title.get_text()).split(" - SELTEC")[0]
    return Wedstrijd(
        wedstrijd_id=wedstrijd_id_uit_url(url),
        naam=clean(naam),
        datum=dagen[0] if dagen else "",
        einddatum=dagen[-1] if dagen else "",
        plaats=clean(plaats),
        url=url,
    )


# --------------------------------------------------------------------------- uitslagblokken
#
# Per onderdeel en ronde een kop en een blok:
#   <div class="listheader">
#     <div class="leftheader"><a href="/Competitions/CurrentList/982650/19133">100 m U18M Series</a></div>
#     <div>18.09.2026 14:00 Officieel Resultaat 14:30:14</div>
#   </div>
#   <div class="runblock classblock c-U18M">
#     <div class="blockname"> ... <div class="rightwind">Wind: I:+2,1, II:+0,6, m/s</div></div>
#     <div class="blocktable">
#       <div class="blockheader"> ... kolomkoppen (bij technische nummers: P1..P6 of de hoogtes) </div>
#       <div class="entryline" data-id="<guid>">
#         col-1: rang / startnummer       col-2: naam / vereniging      col-3: nat. / geboortejaar
#         col-4: resultaat / (wind)       col-5: Q, q, v                col-6: "3./II" (plaats/serie)
#         col-detailresult (0..n):  pogingen, met class "bestTry" voor de beste
#         col-4: categorie                col-last: info (PB, SB, TR16.8 ...)
#       </div>
# De kolommen worden herkend aan hun class, niet aan hun positie.

SPEC_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:kg|gr|gram|g|cm)\b", re.I)   # "5kg", "600gr", "91,4cm"
RONDE_RE = re.compile(
    r"\b(halve finales?|kwartfinales?|finales?(?:\s+[a-z])?|series?(?:\s+\d+)?|voorrondes?(?:\s+\d+)?|"
    r"kwalificatie|heats?|semi[- ]?finals?|finals?|qualification)\b\s*$", re.I)
ESTAFETTE_RE = re.compile(r"\d\s*[x×]\s*\d", re.I)                         # "4x100 m", "4 x 400m"
RECORD_RE = re.compile(r"^=?(?:PB|SB|PR|NR|NJR|CR|CB|ER|WR|DL|WL|EL|MR|AR|ECR|NIR|NJIR)$", re.I)
NAAM_TAG_RE = re.compile(r"\s*\[([^\]]+)\]\s*")                            # "Pim van 't Proefhuis [GK]"
HOOGTE_RE = re.compile(r"^\d[.,]\d{2}$")                                   # kolomkop "1,46"


def eerste(el: Tag | None, klasse: str = "firstline") -> str:
    if el is None:
        return ""
    sub = el.find("div", class_=klasse)
    return clean(sub.get_text()) if sub else ""


def wind_per_serie(blocknaam: Tag | None) -> dict[str, str]:
    """'Wind: I:+2,1, II:+0,6, m/s' -> {'I': '+2,1 m/s', 'II': '+0,6 m/s'}; 'Wind: +1,2 m/s' -> {'': ...}"""
    tekst = clean(blocknaam.select_one(".rightwind").get_text()) if blocknaam and blocknaam.select_one(".rightwind") else ""
    if not tekst:
        return {}
    per_serie = {s: wind_tekst(w) for s, w in re.findall(r"\b([IVXL]+)\s*:\s*([+-]?\d+[.,]\d+)", tekst)}
    if per_serie:
        return per_serie
    w = wind_tekst(tekst)
    return {"": w} if w else {}


def splits_titel(titel: str, categorie: str) -> tuple[str, str, str]:
    """
    '100 m U18M Halve finales' (categorie 'U18M') -> ('100 m', 'Halve finales', '')
    'Kogelstoten U18V 3kg Finale'                 -> ('Kogelstoten', 'Finale', '3kg')
    """
    titel = clean(titel)
    ronde = ""
    m = RONDE_RE.search(titel)
    if m:
        ronde, titel = clean(m.group(1)), clean(titel[:m.start()])
    if categorie:
        titel = clean(re.sub(rf"\s*\b{re.escape(categorie)}\b\s*", " ", titel))
    spec_m = SPEC_RE.search(titel)
    spec = ""
    if spec_m:
        spec = spec_m.group(0).replace(" ", "")
        titel = clean(titel[:spec_m.start()] + titel[spec_m.end():])
    return titel, ronde[:1].upper() + ronde[1:], spec


def pogingen_tekst(entry: Tag, koppen: list[str]) -> str:
    delen = []
    for i, td in enumerate(entry.find_all("div", class_="col-detailresult", recursive=False)):
        regels = [clean(d.get_text()) for d in td.find_all("div", recursive=False)]
        poging, wind = (regels + ["", ""])[:2]
        if not poging:
            continue
        kop = koppen[i] if i < len(koppen) else ""
        if HOOGTE_RE.match(kop):                  # hoog / polsstok: "1,51 XO"
            if poging != "-":
                delen.append(f"{kop} {poging}")
        else:                                     # werpen / springen: "7,25 (+1,5)"
            delen.append(f"{poging} {wind}".strip() if wind else poging)
    return " | ".join(delen)


def info_splitsen(info: str, naam_tags: list[str]) -> tuple[str, str]:
    """'PB - TR17.3.3 lane infringement' -> ('PB', 'TR17.3.3 lane infringement'); 'CR,DL' -> ('CR,DL', '')"""
    record, overig = [], []
    for deel in re.split(r"\s+-\s+", info):
        tokens = [t.strip() for t in deel.split(",")]
        if deel and all(RECORD_RE.match(t) for t in tokens):
            record.append(",".join(tokens))
        elif deel:
            overig.append(deel)
    return ", ".join(record), " - ".join(naam_tags + overig)


def parse_rij(entry: Tag, ctx: dict) -> Uitslag | None:
    kol = {c: [] for c in ("col-1", "col-2", "col-3", "col-4", "col-5", "col-6", "col-last")}
    for div in entry.find_all("div", recursive=False):
        for c in div.get("class") or []:
            if c in kol:
                kol[c].append(div)
    if not kol["col-2"]:
        return None

    naam_ruw = eerste(kol["col-2"][0])
    naam_tags = NAAM_TAG_RE.findall(naam_ruw)
    naam = clean(NAAM_TAG_RE.sub(" ", naam_ruw))
    if not naam:
        return None
    prestatie = eerste(kol["col-4"][0]) if kol["col-4"] else ""
    wind_onder = eerste(kol["col-4"][0], "secondline") if kol["col-4"] else ""
    categorie = (eerste(kol["col-4"][1]) if len(kol["col-4"]) > 1 else "") or ctx["categorie"]
    plaats_serie = eerste(kol["col-6"][0]) if kol["col-6"] else ""          # "1./VI"
    serie = plaats_serie.split("/", 1)[1].strip() if "/" in plaats_serie else ""
    record, opmerking = info_splitsen(eerste(kol["col-last"][0]) if kol["col-last"] else "", naam_tags)

    wind = wind_tekst(wind_onder) or ctx["wind"].get(serie, "") or ctx["wind"].get("", "")
    positie = eerste(kol["col-1"][0]) if kol["col-1"] else ""

    return Uitslag(
        atleet=naam,
        deelnemer_id=entry.get("data-id", ""),
        startnummer=eerste(kol["col-1"][0], "secondline") if kol["col-1"] else "",
        vereniging=eerste(kol["col-2"][0], "secondline"),
        vereniging_id="",
        team="",
        estafette=ctx["estafette"],
        lopers="",
        categorie=categorie,
        onderdeel=ctx["onderdeel"],
        onderdeel_code=ctx["lijst_id"],
        specificatie=ctx["specificatie"],
        ronde=ctx["ronde"],
        positie=positie if re.fullmatch(r"\d+", positie) else "",
        prestatie=prestatie,
        waarde=to_number(prestatie),
        wind=wind if to_number(prestatie) is not None else "",
        punten=None,
        record=record,
        pogingen=pogingen_tekst(entry, ctx["koppen"]),
        wedstrijd=ctx["wedstrijd"].naam,
        datum=ctx["datum"] or ctx["wedstrijd"].datum,
        plaats=ctx["wedstrijd"].plaats,
        uitslag_url=ctx["url"],
        geboortejaar=eerste(kol["col-3"][0], "secondline") if kol["col-3"] else "",
        kwalificatie=eerste(kol["col-5"][0]) if kol["col-5"] else "",
        opmerking=opmerking,
    )


def blokken(soup: BeautifulSoup) -> list[tuple[Tag, Tag]]:
    """(listheader, runblock) paren; een listheader kan meerdere blokken hebben (bv. per serie)."""
    paren, kop = [], None
    for el in soup.select("div.listheader, div.classblock, div.runblock"):
        if "listheader" in (el.get("class") or []):
            kop = el
        elif kop is not None and el.find("div", class_="entryline"):
            paren.append((kop, el))
    return paren


def parse_overzicht(html: str, url: str = "", alleen_lijst: str = "") -> tuple[Wedstrijd, list[Uitslag]]:
    """Alle uitslagen uit een Seltec uitslagenoverzicht (of een opgeslagen kopie ervan)."""
    soup = BeautifulSoup(html, "html.parser")
    paren = blokken(soup)
    blok_datums = [parse_datum_kort(clean(kop.get_text())) for kop, _ in paren]
    wedstrijd = parse_wedstrijd(soup, url, blok_datums)
    basis = f"{urlparse(url).scheme}://{urlparse(url).netloc}" if url.startswith("http") else BASIS_URL

    uitslagen: list[Uitslag] = []
    for kop, blok in paren:
        link = kop.select_one(".leftheader a") or kop.find("a")
        titel = clean(link.get_text()) if link else clean(kop.get_text())
        href = urljoin(basis, link["href"]) if link and link.get("href") else url
        lijst_id = lijst_id_uit_url(href)
        if alleen_lijst and lijst_id != alleen_lijst:
            continue
        cat_klasse = next((c[2:] for c in blok.get("class") or [] if c.startswith("c-")), "")
        onderdeel, ronde, spec = splits_titel(titel, cat_klasse)
        header = blok.find("div", class_="blockheader")
        koppen = [clean(d.get_text()) for d in header.find_all("div", class_="col-detailresult")] if header else []
        ctx = {
            "wedstrijd": wedstrijd, "url": href, "lijst_id": lijst_id,
            "onderdeel": onderdeel, "ronde": ronde, "specificatie": spec,
            "categorie": cat_klasse, "estafette": bool(ESTAFETTE_RE.search(onderdeel)),
            "datum": parse_datum_kort(clean(kop.get_text())),
            "wind": wind_per_serie(blok.find("div", class_="blockname")),
            "koppen": koppen,
        }
        for entry in blok.find_all("div", class_="entryline"):
            u = parse_rij(entry, ctx)
            if u:
                uitslagen.append(u)
    return wedstrijd, uitslagen


# --------------------------------------------------------------------------- filteren
# filter_vereniging en filter_atleten komen uit base.py (Seltec kent geen teams).


# --------------------------------------------------------------------------- importer

def overzicht_url(bron: str) -> str:
    """Wedstrijd-id of willekeurige Seltec-wedstrijd-URL -> URL van het uitslagenoverzicht."""
    if bron.isdigit():
        return BASIS_URL + OVERZICHT_PAD.format(id=bron)
    wid = wedstrijd_id_uit_url(bron)
    if not wid:
        raise ImportFout(f"Kan geen wedstrijd-id halen uit '{bron}'.")
    p = urlparse(bron)
    basis = f"{p.scheme or 'https'}://{p.netloc}" if p.netloc else BASIS_URL
    return basis + OVERZICHT_PAD.format(id=wid)


class SeltecImporter(Importer):
    """
    Wedstrijduitslagen van Seltec. parse(bron) geeft (Wedstrijd, [Uitslag, ...]) terug, ongefilterd;
    filter daarna met filter_vereniging / filter_atleten.
    """

    bron = "seltec"
    site = "Seltec"
    url_patronen = (
        r"(uitslagen\.atletiek\.nl|seltec)[^/]*/Competitions/"
        r"(Resultoverview|CurrentList|Details|Competitoroverview)/",
    )
    timeout = 60                          # het overzicht kan enkele MB's zijn
    max_pogingen = 4

    def parse(self, bron: str) -> tuple[Wedstrijd, list[Uitslag]]:
        """
        Accepteert een wedstrijd-id, een Seltec-URL (uitslagenoverzicht, tijdschema, deelnemerslijst of
        één onderdeellijst), een opgeslagen HTML-bestand van het uitslagenoverzicht of een map daarmee.
        Bij een onderdeellijst-URL (/CurrentList/<lijst>/<wedstrijd>) komt alleen dat onderdeel terug.
        """
        if self.is_lokaal(bron):
            wedstrijd, uitslagen, gezien = None, [], set()
            for uri, html in self.lees_bestanden(bron):
                w, rijen = parse_overzicht(html, uri)
                wedstrijd = wedstrijd or w
                for u in rijen:                   # dubbele blokken over bestanden heen overslaan
                    if (u.deelnemer_id, u.onderdeel_code) not in gezien:
                        gezien.add((u.deelnemer_id, u.onderdeel_code))
                        uitslagen.append(u)
            return wedstrijd, uitslagen

        url = overzicht_url(bron)
        wedstrijd, uitslagen = parse_overzicht(self.haal_op(url), url, alleen_lijst=lijst_id_uit_url(bron))
        self.log(f"{wedstrijd.naam} ({wedstrijd.plaats}, {wedstrijd.datum}) - "
                 f"{len({u.onderdeel_code for u in uitslagen})} onderdeellijsten, {len(uitslagen)} uitslagen")
        return wedstrijd, uitslagen


# Functie-interface (zoals vóór de klasse), voor scripts en bestaande code.

def laad_uitslagen(bron: str, log=print) -> tuple[Wedstrijd, list[Uitslag]]:
    return SeltecImporter(log=log).parse(bron)


can_handle = SeltecImporter.can_handle


def parse(url: str) -> tuple[Wedstrijd, list[Uitslag]]:
    """Alle uitslagen van de wedstrijd (ongefilterd); filter daarna met filter_vereniging/filter_atleten."""
    return SeltecImporter().parse(url)


# --------------------------------------------------------------------------- uitvoer

def print_overzicht(uitslagen: list[Uitslag]) -> None:
    per_atleet: dict[str, list[Uitslag]] = {}
    for u in uitslagen:
        per_atleet.setdefault(u.atleet, []).append(u)
    for naam, rijen in per_atleet.items():
        print(f"\n{naam} - {rijen[0].vereniging} - {rijen[0].categorie}")
        for u in rijen:
            titel = f"{u.onderdeel} {u.ronde}".strip() + (f" ({u.specificatie})" if u.specificatie else "")
            wind = f" [{u.wind}]" if u.wind else ""
            extra = "  ".join(x for x in (u.kwalificatie, u.record) if x)
            pos = f"#{u.positie}" if u.positie else ""
            print(f"  {titel:<36} {u.prestatie:>9}{wind:<12} {pos:<4} {extra}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Importeer wedstrijduitslagen van Seltec (uitslagen.atletiek.nl)")
    ap.add_argument("bron", help="wedstrijd-id, Seltec-URL, onderdeellijst-URL, HTML-bestand of map")
    wie = ap.add_mutually_exclusive_group(required=True)
    wie.add_argument("--vereniging", help="alle atleten van deze vereniging, bv. 'Nijmegen Atletiek'")
    wie.add_argument("--atleten", nargs="+", metavar="NAAM", help="namen van atleten (tussen aanhalingstekens)")
    wie.add_argument("--atleten-bestand", metavar="TXT", help="tekstbestand met één atleetnaam per regel")
    wie.add_argument("--alles", action="store_true", help="alle uitslagen, zonder filter")
    ap.add_argument("--csv", default="uitslagen.csv", help="pad voor CSV (standaard uitslagen.csv)")
    ap.add_argument("--json", help="optioneel pad voor JSON-uitvoer {'wedstrijd': {...}, 'uitslagen': [...]}")
    args = ap.parse_args()

    try:
        wedstrijd, alle = laad_uitslagen(args.bron)
    except ImportFout as fout:
        sys.exit(str(fout))
    if not alle:
        sys.exit("Geen uitslagen gevonden (nog geen uitslagen gepubliceerd?).")

    if args.alles:
        uitslagen = alle
    elif args.vereniging:
        uitslagen = filter_vereniging(alle, args.vereniging)
        if not uitslagen:
            clubs = sorted({u.vereniging for u in alle if u.vereniging})
            tips = difflib.get_close_matches(args.vereniging, clubs, n=5, cutoff=0.3)
            sys.exit(f"Geen atleten van '{args.vereniging}' gevonden."
                     + (f" Bedoel je: {', '.join(tips)}?" if tips else f"\nVerenigingen: {', '.join(clubs)}"))
    else:
        namen = args.atleten or Path(args.atleten_bestand).read_text(encoding="utf-8").splitlines()
        uitslagen, ontbrekend = filter_atleten(alle, namen)
        for naam in ontbrekend:
            tips = difflib.get_close_matches(naam, sorted({u.atleet for u in alle}), n=3, cutoff=0.6)
            print(f"Let op: geen uitslagen voor '{naam}'" + (f" (bedoel je {', '.join(tips)}?)" if tips else ""))

    rows = [asdict(u) for u in uitslagen]
    write_csv(args.csv, rows, Uitslag.__dataclass_fields__)
    print_overzicht(uitslagen)

    print(f"\n{wedstrijd.naam} - {wedstrijd.plaats} - {wedstrijd.datum}"
          + (f" t/m {wedstrijd.einddatum}" if wedstrijd.einddatum != wedstrijd.datum else ""))
    print("Uitslagen per onderdeel:")
    for (ond, spec), n in Counter((u.onderdeel, u.specificatie) for u in uitslagen).items():
        print(f"  {ond + (f' ({spec})' if spec else ''):<32} {n:>4}")
    n_atleten = len({u.atleet for u in uitslagen if not u.estafette})
    print(f"{len(uitslagen)} uitslagen van {n_atleten} atleten geschreven naar {args.csv}")

    if args.json:
        data = {"wedstrijd": asdict(wedstrijd), "uitslagen": rows}
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON geschreven naar {args.json}")


if __name__ == "__main__":
    main()
