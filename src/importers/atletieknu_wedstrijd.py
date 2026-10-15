"""
Importeer de uitslagen van een wedstrijd op atletiek.nu voor een groep atleten
of voor alle atleten van een vereniging, en exporteer ze naar CSV/JSON.

Werkwijze: de uitslagenpagina van de wedstrijd linkt naar één pagina per onderdeel
(/wedstrijd/uitslagenonderdeel/<id>/<onderdeel>/). Die pagina's worden allemaal
opgehaald; elke rij in elke uitslagtabel wordt een Uitslag, daarna wordt gefilterd.

Gebruik:
    python atletieknu_wedstrijd.py 43465 --vereniging "Nijmegen Atletiek"
    python atletieknu_wedstrijd.py https://www.atletiek.nu/wedstrijd/uitslagen/43465/ \\
        --atleten "Anna Voorbeeld" "Bas van Proefstra" "Lotte Testerink"
    python atletieknu_wedstrijd.py 44999 --team "Nijmegen Heren 1"     # teamwedstrijd (incl. estafettes)
    python atletieknu_wedstrijd.py 43465 --atleten-bestand groep.txt   # één naam per regel
    python atletieknu_wedstrijd.py 43465 --alles                       # iedereen
    python atletieknu_wedstrijd.py opgeslagen_map/ --vereniging Nijmegen  # opgeslagen onderdeelpagina's
    python atletieknu_wedstrijd.py 43465 --vereniging Nijmegen --csv uitslagen.csv --json uitslagen.json

Vereist: pip install requests beautifulsoup4 curl_cffi
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
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup, Tag

try:                                    # als pakket: from src.importers import atletieknu_wedstrijd
    from .base import (Importer, ImportFout, clean, filter_atleten, filter_team,
                       filter_vereniging, lopers_lijst, to_number, write_csv)
except ImportError:                     # als script: python atletieknu_wedstrijd.py ...
    from base import (Importer, ImportFout, clean, filter_atleten, filter_team,  # type: ignore
                      filter_vereniging, lopers_lijst, to_number, write_csv)

BASIS_URL = "https://www.atletiek.nu"
UITSLAGEN_URL = BASIS_URL + "/wedstrijd/uitslagen/{id}/"

MAANDEN = {m: i for i, m in enumerate(
    ["januari", "februari", "maart", "april", "mei", "juni", "juli",
     "augustus", "september", "oktober", "november", "december"], start=1)}


@dataclass
class Wedstrijd:
    wedstrijd_id: str       # bv. "43465"
    naam: str               # bv. "Nazomermeerkamp 2026"
    datum: str              # ISO, eerste dag
    einddatum: str          # ISO, laatste dag (gelijk aan datum bij een eendaagse wedstrijd)
    plaats: str             # bv. "Venray"
    url: str


@dataclass
class Uitslag:
    atleet: str             # naam zoals op de site, bv. "Anna Voorbeeld"; bij een estafette de
                            # naam van het estafetteteam, bv. "Nijmegen Heren 1 (4x100m)"
    deelnemer_id: str       # id van de inschrijving op atletiek.nu (per wedstrijd, NIET het profiel-id)
    startnummer: str        # bv. "175"
    vereniging: str         # bv. "Nijmegen Atletiek"
    vereniging_id: str      # id van de vereniging binnen deze wedstrijd, bv. "346"
    team: str               # competitieteam, bv. "Nijmegen Heren 1" (leeg buiten teamwedstrijden)
    estafette: bool         # True = één rij voor het hele estafetteteam (geen individuele prestatie)
    lopers: str             # alleen bij estafettes: "Tim Proefmans, Anna Voorbeeld, ..."
    categorie: str          # bv. "Senioren Mannen" of "Masters Mannen 60+"
    onderdeel: str          # volledige naam, bv. "110 meter horden"
    onderdeel_code: str     # korte code van atletiek.nu, bv. "110mH"
    specificatie: str       # gewicht / hordehoogte, bv. "7,26kg", "106.7cm" (leeg als niets)
    ronde: str              # bv. "Finale", "Serie 2" (leeg als het niet uit de titel blijkt)
    positie: str            # plaats in de uitslag ("" bij DNS/DNF e.d.)
    prestatie: str          # zoals op de site: "11,44", "5:07,95", "DNF", "---"
    waarde: float | None    # seconden / meters / punten (None bij DNF, DNS, NM, ...)
    wind: str               # bv. "+0,8 m/s" (leeg als niet gemeten / niet van toepassing)
    punten: int | None      # punten volgens de site: meerkamppunten, of teampunten bij een
                            # teamwedstrijd (None als niet vermeld)
    record: str             # markering van de site, bv. "PB", "SB" (leeg als niets)
    pogingen: str           # technische nummers, bv. "- | 6,01 | 6,19" of "1.18 XXO | 1.21 XO"
    wedstrijd: str
    datum: str              # eerste wedstrijddag (atletiek.nu toont per onderdeel geen dag)
    plaats: str
    uitslag_url: str        # url van de onderdeelpagina


# --------------------------------------------------------------------------- helpers

# clean en to_number komen uit base.py.


def tooltip_delen(title: str) -> list[str]:
    """'100 meter<br />(in secondes)<br>+0,8m/s<br />765 punten ' -> ['100 meter', '(in secondes)', ...]"""
    return [clean(d) for d in re.split(r"<br\s*/?>", title or "", flags=re.I) if clean(d)]


def wind_uit(tekst: str) -> str:
    m = re.search(r"([+-]?\d+[.,]\d+)\s*m/s", tekst or "")
    return f"{m.group(1).replace('.', ',')} m/s" if m else ""


def punten_uit(tekst: str) -> int | None:
    m = re.search(r"(\d+)\s*punten", tekst or "")
    return int(m.group(1)) if m else None


def id_uit_url(url: str, deel: str) -> str:
    """Laatste id na /<deel>/: '.../atleet/main/2896591/' -> '2896591', '.../vereniging/43465/346/' -> '346'."""
    m = re.search(rf"/{deel}/(?:\d+/)?(\d+)/?", url or "")
    return m.group(1) if m else ""


def wedstrijd_id_uit_url(url: str) -> str:
    """'.../wedstrijd/uitslagen/43465/492691/' -> '43465' (ook voor /main/, /uitslagenonderdeel/, ...)."""
    m = re.search(r"/wedstrijd/[a-z]+/(\d+)", url or "")
    return m.group(1) if m else ""


def parse_datum(tekst: str) -> str:
    """'Zaterdag 29 augustus 2026' -> '2026-08-29' ('' als het niet lukt)."""
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", tekst.lower())
    if not m or m.group(2) not in MAANDEN:
        return ""
    return date(int(m.group(3)), MAANDEN[m.group(2)], int(m.group(1))).isoformat()


# --------------------------------------------------------------------------- wedstrijd

def parse_wedstrijd(html: str, url: str = "") -> Wedstrijd:
    """
    Kop van elke wedstrijdpagina:
      <div class="pageTitle">Nazomermeerkamp 2026<br>
        <span class="smalldetail">Venray, Zaterdag 29 augustus 2026 - Zondag 30 augustus 2026</span></div>
    """
    soup = BeautifulSoup(html, "html.parser")
    kop = soup.select_one("div.pageTitle")
    naam, detail = "", ""
    if kop:
        detail_el = kop.find("span", class_="smalldetail")
        detail = clean(detail_el.get_text()) if detail_el else ""
        if detail_el:
            detail_el.extract()
        naam = clean(kop.get_text())
    if not naam and soup.title:  # "Atletiek.nu - Nazomermeerkamp 2026 - Live uitslagen!"
        delen = clean(soup.title.get_text()).split(" - ")
        naam = delen[1] if len(delen) > 1 else ""

    plaats, _, datums = detail.partition(",")
    dagen = [parse_datum(d) for d in datums.split(" - ")] if datums else []
    dagen = [d for d in dagen if d]
    return Wedstrijd(
        wedstrijd_id=wedstrijd_id_uit_url(url),
        naam=naam,
        datum=dagen[0] if dagen else "",
        einddatum=dagen[-1] if dagen else "",
        plaats=clean(plaats),
        url=url,
    )


def onderdeel_links(html: str, wedstrijd_id: str) -> list[str]:
    """Alle links naar /wedstrijd/uitslagenonderdeel/<id>/<onderdeel>/ op de uitslagenpagina."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.select("a[href*='/wedstrijd/uitslagenonderdeel/']"):
        url = urljoin(BASIS_URL, a["href"]).split("#")[0].split("?")[0]
        if f"/uitslagenonderdeel/{wedstrijd_id}/" in url and url not in links:
            links.append(url)
    return links


# --------------------------------------------------------------------------- uitslagtabellen
#
# Per categorie (en eventueel per ronde) een blok:
#   <div class="tab-pane" id="492696_12">
#     <h2>Senioren Mannen 100 meter</h2>
#     <table class="deelnemerstabel"> # | Naam | Vereniging | (Categorie) | (Gewicht) | (P1..P6) | Resultaat | (Wind) | (Punten)
# De kolommen verschillen per onderdeel én de cellen kloppen niet altijd met de koppen
# (bij hoogspringen staat er per hoogte een extra cel). Daarom herkennen we cellen aan hun
# inhoud in plaats van hun positie:
#   - naam:        <a href=".../atleet/main/<deelnemer_id>/">
#   - vereniging:  <a href=".../wedstrijd/vereniging/<wedstrijd>/<id>/">
#   - categorie:   <a href=".../wedstrijd/categorie/<wedstrijd>/<id>/">  (anders uit de <h2>)
#   - resultaat:   cel met <span class="sortData"> + <span class="tipped" title="Onderdeel<br>...">
#   - pogingen:    cellen met class "deelnemer-results-..." (werpen/springen)
#   - team:        <a href=".../team/main/<id>/"> (teamwedstrijden, bv. NSK Teams)
# Estafettes: de naam is een <a href=".../estafetteteam/main/<id>/"> en de lopers staan in
# <td class="visible-xlg"><span class="tipped" title="Volledige Naam">; dat wordt één Uitslag
# voor het hele team met de lopers in het veld 'lopers'.
# In een overzichtstabel met meerdere onderdelen (meerkamp, /uitslagen/<id>/all/) heeft een
# rij meerdere resultaatcellen; dan levert de rij één Uitslag per onderdeel op.

SPEC_RE = re.compile(r"^\d+(?:[.,]\d+)?\s*(?:kg|gr|gram|g|cm|m)$", re.I)   # "7.26kg", "600gr", "76.2cm"
RESERVE_RE = re.compile(r"reserve", re.I)   # onderdeel "Reserve atleet" (code "Resv") overslaan
RONDE_RE = re.compile(
    r"\b(halve finale|kwartfinale|finale(?:\s+[a-z])?|series?(?:\s+\d+)?|voorrondes?(?:\s+\d+)?)\b", re.I)


def is_poging(td: Tag) -> bool:
    return any(c.startswith("deelnemer-results") for c in (td.get("class") or []))


def resultaat_cellen(tds: list[Tag]) -> list[tuple[Tag, Tag]]:
    """(td, tooltip-span) voor elke cel met een eindresultaat."""
    out = []
    for td in tds:
        if is_poging(td) or not td.find("span", class_="sortData"):
            continue
        tip = td.find("span", class_="tipped", title=True)
        if tip:
            out.append((td, tip))
    return out


def pogingen_tekst(tds: list[Tag]) -> str:
    delen = []
    for td in tds:
        if not is_poging(td):
            continue
        tip = td.find("span", class_="tipped")
        if tip:                                       # werpen / verspringen: "6,01"
            delen.append(clean(tip.get_text()) or "-")
        else:                                         # hoogspringen: title="1.18<br>XXO"
            hoogte, *rest = tooltip_delen(td.get("title", "")) or [""]
            pogingen = clean(td.get_text())
            if pogingen and pogingen != "-":
                delen.append(f"{hoogte} {pogingen}".strip())
    return " | ".join(delen)


def lopers_uit(tds: list[Tag]) -> list[str]:
    """Volledige namen van de lopers van een estafetteteam, in looprichting."""
    namen = [clean(s.get("title", "")) for td in tds if "visible-xlg" in (td.get("class") or [])
             for s in td.find_all("span", class_="tipped")]
    if not any(namen):  # reserve: tooltip "<b>4x100m</b><br>-1: Lotte Testerink<br>-1: ..."
        td = next((td for td in tds if "<br" in td.get("title", "") and ":" in td.get("title", "")), None)
        delen = tooltip_delen(td.get("title", "")) if td else []
        namen = [clean(re.sub(r"^-?\d+:\s*", "", d)) for d in delen[1:]]
    return [n for n in namen if n]


def team_uit(tr: Tag) -> str:
    """<a href=".../team/main/136760/"><span class="visible-xs-inline">X</span><span class="hidden-xs">X</span></a>"""
    team_a = tr.select_one("a[href*='/team/main/']")
    if not team_a:
        return ""
    deel = team_a.select_one("span.hidden-xs") or team_a
    return clean(deel.get_text())


def parse_rij(tr: Tag, kop: str, code: str, wedstrijd: Wedstrijd, url: str,
              th_onderdelen: list[str]) -> list[Uitslag]:
    tds = tr.find_all("td", recursive=False)
    naam_a = tr.select_one("a[href*='/atleet/main/']") or tr.select_one("a[href*='/estafetteteam/']")
    if not naam_a:
        return []
    estafette = "/estafetteteam/" in naam_a.get("href", "")
    lopers = ", ".join(lopers_uit(tds)) if estafette else ""
    # Lange namen staan niet als tekst in de link maar als
    #   <span class="visible-xs-inline">R. van den...naamhoeve</span><span class="hidden-xs">Volledige Naam</span>
    volledig = naam_a.find("span", class_="hidden-xs", recursive=False)
    volledig = clean(volledig.get_text()) if volledig else ""
    for detail in naam_a.find_all("span"):            # "Nijmegen - 76.2cm" (alleen op mobiel)
        detail.extract()
    naam = clean(naam_a.get_text()) or volledig

    ver_a = tr.select_one("a[href*='/wedstrijd/vereniging/']")
    cat_a = tr.select_one("a[href*='/wedstrijd/categorie/']")
    pos_b = tds[0].find("b") if tds else None
    nummer = re.match(r"\s*(\d+)\.", tr.get("data-athlete", ""))
    spec = next((clean(td.get_text()) for td in tds
                 if not td.find(["a", "span"]) and SPEC_RE.match(clean(td.get_text()))), "")
    wind_cel = next((clean(td.get_text()) for td in tds
                     if re.fullmatch(r"[+-]?\d+[.,]\d+\s*m/s", clean(td.get_text()))), "")

    cellen = resultaat_cellen(tds)
    uitslagen = []
    for i, (td, tip) in enumerate(cellen):
        delen = tooltip_delen(tip.get("title", ""))
        onderdeel = delen[0] if delen else (th_onderdelen[i] if i < len(th_onderdelen) else code)
        if RESERVE_RE.match(onderdeel):                # "Reserve atleet" (teamwedstrijden): geen uitslag
            continue
        title = tip.get("title", "")
        mark = td.find("span", class_="recordMark")
        prestatie = clean(tip.get_text())

        categorie = clean(cat_a.get_text()) if cat_a else clean(
            re.sub(re.escape(onderdeel) + r".*$", "", kop, flags=re.I))
        ronde = RONDE_RE.search(kop)

        uitslagen.append(Uitslag(
            atleet=naam,
            deelnemer_id=tr.get("data-deelnemer_id", "") or id_uit_url(naam_a.get("href", ""), "main"),
            startnummer=nummer.group(1) if nummer else "",
            vereniging=clean(ver_a.get_text()) if ver_a else "",
            vereniging_id=id_uit_url(ver_a.get("href", ""), "vereniging") if ver_a else "",
            team=team_uit(tr),
            estafette=estafette,
            lopers=lopers,
            categorie=categorie,
            onderdeel=onderdeel,
            onderdeel_code=code if len(cellen) == 1 else "",
            specificatie=spec if len(cellen) == 1 else "",
            ronde=ronde.group(1).capitalize() if ronde else "",
            positie=clean(pos_b.get_text()) if (pos_b and len(cellen) == 1) else "",
            prestatie=prestatie,
            waarde=to_number(prestatie),
            wind=wind_uit(title) or (wind_cel.replace("  ", " ") if len(cellen) == 1 else ""),
            punten=punten_uit(title),
            record=clean(mark.get_text()) if mark else "",
            pogingen=pogingen_tekst(tds) if len(cellen) == 1 else "",
            wedstrijd=wedstrijd.naam,
            datum=wedstrijd.datum,
            plaats=wedstrijd.plaats,
            uitslag_url=url,
        ))
    return uitslagen


def parse_onderdeel_pagina(html: str, url: str, wedstrijd: Wedstrijd) -> list[Uitslag]:
    soup = BeautifulSoup(html, "html.parser")
    if "/uitslagenonderdeel/" not in url:            # opgeslagen pagina: code uit de kruimelnavigatie
        kruimel = soup.select("#menubottom a[href*='/uitslagenonderdeel/']")
        url = urljoin(BASIS_URL, kruimel[-1]["href"]) if kruimel else url
    code = unquote(url.rstrip("/").rsplit("/", 1)[-1]) if "/uitslagenonderdeel/" in url else ""
    uitslagen: list[Uitslag] = []
    for table in soup.select("table.deelnemerstabel"):
        kop_el = table.find_previous(["h2", "h3"])
        kop = clean(kop_el.get_text()) if kop_el else ""
        # onderdeelnamen uit de kolomkoppen (fallback als een tooltip ontbreekt)
        th_onderdelen = [th.get("title", "") for th in table.select("thead th")
                         if any(c.startswith("sortInitialOrder") for c in th.get("class") or [])
                         and "pogingencol" not in " ".join(th.get("class") or [])
                         and "punten totaal" not in th.get("title", "").lower()]
        body = table.find("tbody") or table
        for tr in body.find_all("tr", recursive=False):
            uitslagen += parse_rij(tr, kop, code, wedstrijd, url, th_onderdelen)
    return uitslagen


# --------------------------------------------------------------------------- filteren
# filter_vereniging, filter_team en filter_atleten komen uit base.py.


# --------------------------------------------------------------------------- importer

TE_VEEL_RE = re.compile(r"<title>\s*Too many requests", re.I)


class AtletiekNuWedstrijdImporter(Importer):
    """
    Wedstrijduitslagen van atletiek.nu. parse(bron) geeft (Wedstrijd, [Uitslag, ...]) terug,
    ongefilterd; filter daarna met filter_vereniging / filter_team / filter_atleten.
    """

    bron = "atletieknu"
    site = "atletiek.nu"
    url_patronen = (r"atletiek\.nu/wedstrijd/(uitslagen|uitslagenonderdeel|main)/\d+",)
    pauze = 1.0               # atletiek.nu blokkeert tijdelijk bij te veel snelle verzoeken
    imiteer_browser = "chrome"  # atletiek.nu blokkeert de Python-bibliotheek requests
    max_pogingen = 6
    opnieuw_bij_status = (429,)

    def moet_wachten(self, resp: requests.Response) -> bool:
        # Na ±10 snelle verzoeken een 'Too many requests'-pagina, soms met status 200!
        return super().moet_wachten(resp) or bool(TE_VEEL_RE.search(resp.text))

    def controleer_pagina(self, html: str, url: str) -> None:
        # atletiek.nu toont soms een "Checking your browser"-pagina aan scripts.
        if "Checking your browser" in html and "deelnemerstabel" not in html and "pageTitle" not in html:
            raise ImportFout(
                f"atletiek.nu gaf een browsercontrole-pagina terug voor {url}.\n"
                "Open de onderdeelpagina's in je browser, sla ze op (Ctrl+S, 'Alleen HTML') in één map\n"
                "en importeer die map.")

    def parse(self, bron: str) -> tuple[Wedstrijd, list[Uitslag]]:
        """
        Accepteert een wedstrijd-id, een wedstrijd-URL, een URL van één onderdeelpagina,
        een opgeslagen HTML-bestand of een map met opgeslagen HTML-bestanden.
        """
        if self.is_lokaal(bron):
            paginas = self.lees_bestanden(bron)
            wedstrijd = parse_wedstrijd(paginas[0][1])
            uitslagen = []
            for url, html in paginas:
                uitslagen += parse_onderdeel_pagina(html, url, wedstrijd)
            return wedstrijd, uitslagen

        if "/uitslagenonderdeel/" in bron:            # één onderdeel
            url = bron.split("#")[0]
            html = self.haal_op(url)
            wedstrijd = parse_wedstrijd(html, url)
            return wedstrijd, parse_onderdeel_pagina(html, url, wedstrijd)

        wid = bron if bron.isdigit() else wedstrijd_id_uit_url(bron)
        if not wid:
            raise ImportFout(f"Kan geen wedstrijd-id halen uit '{bron}'.")
        url = UITSLAGEN_URL.format(id=wid)
        html = self.haal_op(url)
        wedstrijd = parse_wedstrijd(html, url)
        links = onderdeel_links(html, wid)
        if not links:
            raise ImportFout("Geen onderdelen gevonden op de uitslagenpagina (nog geen uitslagen?).")

        self.log(f"{wedstrijd.naam} ({wedstrijd.plaats}, {wedstrijd.datum}) - {len(links)} onderdelen ophalen...")
        uitslagen: list[Uitslag] = []
        for link in links:
            uitslagen += parse_onderdeel_pagina(self.haal_op(link), link, wedstrijd)
        return wedstrijd, uitslagen


# Functie-interface (zoals vóór de klasse), voor scripts en bestaande code.

def laad_uitslagen(bron: str, log=print) -> tuple[Wedstrijd, list[Uitslag]]:
    return AtletiekNuWedstrijdImporter(log=log).parse(bron)


can_handle = AtletiekNuWedstrijdImporter.can_handle


def parse(url: str) -> tuple[Wedstrijd, list[Uitslag]]:
    """Alle uitslagen van de wedstrijd (ongefilterd); filter daarna met filter_vereniging/filter_atleten."""
    return AtletiekNuWedstrijdImporter().parse(url)


# --------------------------------------------------------------------------- uitvoer

def print_overzicht(uitslagen: list[Uitslag]) -> None:
    per_atleet: dict[str, list[Uitslag]] = {}
    for u in uitslagen:
        if not u.estafette:
            per_atleet.setdefault(u.atleet, []).append(u)
    for naam, rijen in per_atleet.items():
        team = f" - {rijen[0].team}" if rijen[0].team else ""
        print(f"\n{naam} - {rijen[0].vereniging} - {rijen[0].categorie}{team}")
        for u in rijen:
            spec = f" ({u.specificatie})" if u.specificatie else ""
            wind = f" [{u.wind}]" if u.wind else ""
            extra = f"  {u.record}" if u.record else ""
            pos = f"#{u.positie}" if u.positie else ""
            print(f"  {u.onderdeel + spec:<32} {u.prestatie:>9}{wind:<12} {pos:<4}{extra}")

    estafettes = [u for u in uitslagen if u.estafette]
    if estafettes:
        print("\nEstafettes")
        for u in estafettes:
            pos = f"#{u.positie}" if u.positie else ""
            print(f"  {u.atleet:<32} {u.prestatie:>9}             {pos}")
            print(f"    lopers: {u.lopers or '(onbekend)'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Importeer wedstrijduitslagen van atletiek.nu")
    ap.add_argument("bron", help="wedstrijd-id, uitslagen-URL, onderdeel-URL, HTML-bestand of map")
    wie = ap.add_mutually_exclusive_group(required=True)
    wie.add_argument("--vereniging", help="alle atleten van deze vereniging, bv. 'Nijmegen Atletiek'")
    wie.add_argument("--team", help="alle uitslagen van één competitieteam, bv. 'Nijmegen Heren 1'")
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
        sys.exit("Geen uitslagen gevonden.")

    if args.alles:
        uitslagen = alle
    elif args.vereniging:
        uitslagen = filter_vereniging(alle, args.vereniging)
        if not uitslagen:
            clubs = sorted({u.vereniging for u in alle if u.vereniging})
            tips = difflib.get_close_matches(args.vereniging, clubs, n=5, cutoff=0.3)
            sys.exit(f"Geen atleten van '{args.vereniging}' gevonden."
                     + (f" Bedoel je: {', '.join(tips)}?" if tips else f"\nVerenigingen: {', '.join(clubs)}"))
    elif args.team:
        uitslagen = filter_team(alle, args.team)
        if not uitslagen:
            teams = sorted({u.team for u in alle if u.team})
            if not teams:
                sys.exit("Deze wedstrijd heeft geen teams (alleen bij teamwedstrijden zoals competities).")
            tips = difflib.get_close_matches(args.team, teams, n=5, cutoff=0.3)
            sys.exit(f"Geen team '{args.team}' gevonden."
                     + (f" Bedoel je: {', '.join(tips)}?" if tips else f"\nTeams: {', '.join(teams)}"))
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
    n_estafettes = sum(u.estafette for u in uitslagen)
    print(f"{len(uitslagen)} uitslagen van {n_atleten} atleten"
          + (f" (waarvan {n_estafettes} estafettes)" if n_estafettes else "")
          + f" geschreven naar {args.csv}")

    if args.json:
        data = {"wedstrijd": asdict(wedstrijd), "uitslagen": rows}
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON geschreven naar {args.json}")


if __name__ == "__main__":
    main()
