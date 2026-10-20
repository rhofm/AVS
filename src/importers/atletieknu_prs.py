"""
Export de persoonlijke records (PR's) én alle prestaties van een atleet op atletiek.nu
naar CSV/JSON.

Gebruik:
    python export_prs.py 123456                       # PR's -> prs.csv
    python export_prs.py 123456 --resultaten          # + alle prestaties -> resultaten.csv
    python export_prs.py https://www.atletiek.nu/atleet/profiel/123456/
    python export_prs.py profiel.html --resultaten    # parse een opgeslagen pagina
    python export_prs.py 123456 --resultaten mijn.csv --json alles.json

Vereist: pip install requests beautifulsoup4 curl_cffi
"""

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, Tag

try:                                    # als pakket: from src.importers import atletieknu_prs
    from .base import Importer, ImportFout, clean, to_number, write_csv
except ImportError:                     # als script: python atletieknu_prs.py ...
    from base import Importer, ImportFout, clean, to_number, write_csv  # type: ignore

PROFILE_URL = "https://www.atletiek.nu/atleet/profiel/{id}/"
# atletiek.nu gebruikt voor Nederland zowel "NLD" als "NED"; breid uit als je meer tegenkomt.
LAND_ALIASSEN = {"NED": "NLD"}


@dataclass
class PR:
    onderdeel: str          # bv. "Kogelstoten"
    specificatie: str       # bv. "5kg", "Handtijd", "Ontbrekende windmeting" (leeg als niets)
    prestatie: str          # zoals op de site: "1:25,11", "10,1h", "9,64"
    waarde: float | None    # prestatie als getal: seconden / meters / punten (None bij DNF e.d.)
    wind: str               # bv. "-0,3 m/s", "n/a" of leeg
    datum: str              # ISO-formaat: "2016-10-02"
    plaats: str             # bv. "Nijmegen"
    land: str               # bv. "NLD"
    wedstrijd: str          # naam van de wedstrijd (uit de wedstrijdenlijst op dezelfde pagina)
    belangrijk: bool        # False = rij die de site standaard verbergt ("notThatImportant")


@dataclass
class Resultaat:
    onderdeel: str          # volledige naam, bv. "400 meter horden"
    onderdeel_id: str       # interne id van atletiek.nu, bv. "155"
    specificatie: str       # bv. "76.2cm", "6kg" (leeg als het onderdeel er geen heeft)
    prestatie: str          # zoals op de site, incl. "DNF", "DNS", "DQ", ...
    waarde: float | None
    wind: str
    datum: str
    plaats: str
    land: str
    wedstrijd: str
    wedstrijd_url: str


# --------------------------------------------------------------------------- helpers

# clean en to_number komen uit base.py.


def parse_sortdata(td: Tag) -> tuple[str, str, str, str]:
    """<span class="sortData" data="20161002Nijmegen (NLD)"> -> (datum, plaats, land, ruwe sleutel)"""
    sort_el = td.find("span", class_="sortData") if td else None
    raw = sort_el.get("data", "") if sort_el else ""
    m = re.match(r"(\d{8})(.*?)(?:\s*\((\w+)\))?$", raw)
    if not m:
        return "", "", "", raw
    datum = datetime.strptime(m.group(1), "%Y%m%d").date().isoformat()
    land = (m.group(3) or "").upper()            # site mixt "NLD" en "Sui"/"Aho"
    land = LAND_ALIASSEN.get(land, land)
    return datum, clean(m.group(2)), land, raw


def header_names(table: Tag) -> list[str]:
    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        if ths:
            return [clean(th.get_text()) for th in ths]
    return []


def find_table(soup: BeautifulSoup, first_headers: list[str]) -> Tag | None:
    """
    De pagina gebruikt id="persoonlijkerecords" voor méérdere tabellen,
    daarom zoeken we op kolomkoppen.
    """
    for table in soup.find_all("table"):
        if header_names(table)[: len(first_headers)] == first_headers:
            return table
    return None


def meet_lookup(soup: BeautifulSoup) -> dict[str, tuple[str, str]]:
    """Wedstrijdenlijst ('Wedstrijd | Datum') -> {sortData-sleutel: (naam, url)}."""
    table = find_table(soup, ["Wedstrijd", "Datum"])
    lookup: dict[str, tuple[str, str]] = {}
    if not table:
        return lookup
    for tr in table.select("tbody > tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        a = tds[0].find("a")
        naam = clean(tds[0].get_text())
        url = a.get("href", "") if a else ""
        key = parse_sortdata(tds[1])[3]
        # Zelfde dag + plaats kan meerdere keren voorkomen (bv. "Onbekende wedstrijdnaam" naast
        # de echte naam, of een vertaalde naam). Houd de eerste échte naam aan.
        if key in lookup and not lookup[key][0].lower().startswith("onbekende"):
            continue
        lookup[key] = (naam, url)
    return lookup


# --------------------------------------------------------------------------- PR's

def parse_pr_row(tr: Tag, meets: dict) -> PR | None:
    tds = tr.find_all("td", recursive=False)
    if len(tds) < 3:
        return None
    event_td, perf_td, meet_td = tds[:3]

    spec_el = event_td.find("span", class_="subtext")
    specificatie = clean(spec_el.get_text()) if spec_el else ""
    if spec_el:
        spec_el.extract()

    wind_el = perf_td.find("span", class_="subtext")
    wind = clean(wind_el.get_text()) if wind_el else ""
    if wind_el:
        wind_el.extract()
    prestatie = clean(perf_td.get_text())

    datum, plaats, land, key = parse_sortdata(meet_td)
    return PR(
        onderdeel=clean(event_td.get_text()),
        specificatie=specificatie,
        prestatie=prestatie,
        waarde=to_number(prestatie),
        wind=wind,
        datum=datum,
        plaats=plaats,
        land=land,
        wedstrijd=meets.get(key, ("", ""))[0],
        belangrijk="notThatImportant" not in (tr.get("class") or []),
    )


def parse_prs(html: str) -> list[PR]:
    soup = BeautifulSoup(html, "html.parser")
    table = find_table(soup, ["Onderdeel", "Record"])
    if not table:
        raise ValueError("Geen PR-tabel gevonden (kolommen 'Onderdeel' / 'Record').")
    meets = meet_lookup(soup)
    rows = table.find("tbody").find_all("tr", recursive=False)
    return [pr for pr in (parse_pr_row(tr, meets) for tr in rows) if pr]


# --------------------------------------------------------------------------- alle prestaties
#
# Onder de grafieken staat per onderdeel een tab-pane:
#   <div id="graphTabs">
#     <div class="tab-pane" id="155">                     <- id = onderdeel-id
#       Specificatie: <a class="specification-selector" data-target="specification-container-16-155">76.2cm</a>
#       <div class="specification-container specification-container-16-155">
#         <table> Prestatie | (Wind) | Verschil | Wedstrijd </table>
#       </div>
#       <script> ...highcharts({ title: { text: '400 meter horden' } ... }) </script>
#     </div>
# Bij werponderdelen is er per gewicht een container, plus een "Alles"-container
# (id met "-all-") die alles herhaalt; die slaan we over om dubbelingen te voorkomen.
# Zonder specificaties staat de tabel direct in de pane.
# De tabellen bevatten ook resultaten die niet in de grafiek staan (DNF e.d.).

TITLE_RE = re.compile(r"title:\s*\{\s*text:\s*'((?:[^'\\]|\\.)*)'")


def event_name(pane: Tag, nav_names: dict[str, str]) -> str:
    script = pane.find("script")
    if script and script.string:
        m = TITLE_RE.search(script.string)
        if m:
            return m.group(1).replace("\\'", "'")
    return nav_names.get(pane.get("id", ""), pane.get("id", ""))  # fallback: "Kogel", "400mH", ...


def parse_result_table(table: Tag, base: dict, meets: dict) -> list[Resultaat]:
    cols = header_names(table)
    idx = {name: i for i, name in enumerate(cols)}
    if "Prestatie" not in idx or "Wedstrijd" not in idx:
        return []
    out = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != len(cols):
            continue
        prestatie = clean(tds[idx["Prestatie"]].get_text())
        wind = clean(tds[idx["Wind"]].get_text()) if "Wind" in idx else ""
        datum, plaats, land, key = parse_sortdata(tds[idx["Wedstrijd"]])
        naam, url = meets.get(key, ("", ""))
        out.append(Resultaat(**base, prestatie=prestatie, waarde=to_number(prestatie), wind=wind,
                             datum=datum, plaats=plaats, land=land, wedstrijd=naam, wedstrijd_url=url))
    return out


def parse_results(html: str) -> list[Resultaat]:
    """
    Alle prestaties van het profiel. Heeft atletiek.nu te weinig uitslagen voor grafieken
    ('Te weinig uitslagen'), dan ontbreekt div#graphTabs en komen de prestaties uit de
    PR-tabel (zie resultaten_uit_prs). ValueError als het geen profielpagina is.
    """
    soup = BeautifulSoup(html, "html.parser")
    graph = soup.find(id="graphTabs")
    if not graph:
        if find_table(soup, ["Onderdeel", "Record"]) or soup.find(id="records"):
            return resultaten_uit_prs(soup)
        raise ValueError("Geen profielpagina: geen grafieken en geen PR-tabel gevonden.")
    meets = meet_lookup(soup)
    nav_names = {a["data-tabtarget"]: clean(a.get_text())
                 for a in soup.select("#graphTabButtons a[data-tabtarget]")}

    results: list[Resultaat] = []
    for pane in graph.find_all("div", class_="tab-pane", recursive=False):
        base = {"onderdeel": event_name(pane, nav_names), "onderdeel_id": pane.get("id", "")}
        spec_names = {a.get("data-target"): clean(a.get_text())
                      for a in pane.select("a.specification-selector")}
        containers = pane.find_all("div", class_="specification-container")
        if containers:
            for box in containers:
                target = next((c for c in box["class"] if c.startswith("specification-container-")), "")
                if "-all-" in target:
                    continue  # "Alles" = dubbel
                for table in box.find_all("table"):
                    results += parse_result_table(
                        table, {**base, "specificatie": spec_names.get(target, "")}, meets)
        else:
            for table in pane.find_all("table"):
                results += parse_result_table(table, {**base, "specificatie": ""}, meets)
    return results


# In de PR-tabel staat onder het onderdeel een gewicht of hoogte ('3kg', '500gr', '76.2cm'),
# maar ook een opmerking als 'Handtijd' of 'Ontbrekende windmeting'. Alleen het eerste is een
# specificatie zoals in de grafiektabellen; een handtijd zie je al aan de 'h' in '10,1h'.
SPECIFICATIE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:kg|gr|g|cm|m)", re.IGNORECASE)


def resultaten_uit_prs(soup: BeautifulSoup) -> list[Resultaat]:
    """
    Prestaties uit de PR-tabel, voor profielen zonder grafieken. Bij zo weinig uitslagen zijn de
    PR's alle prestaties die de pagina toont. Het onderdeel-id staat niet in de PR-tabel (leeg).
    Dezelfde prestatie staat soms twee keer in de tabel (met en zonder 'Ontbrekende
    windmeting'); die wordt één resultaat.
    """
    table = find_table(soup, ["Onderdeel", "Record"])
    if not table or not table.find("tbody"):
        return []
    meets = meet_lookup(soup)
    results: list[Resultaat] = []
    gezien: set[tuple[str, str, str, str]] = set()
    for tr in table.find("tbody").find_all("tr", recursive=False):
        pr = parse_pr_row(tr, meets)
        if pr is None:
            continue
        spec = pr.specificatie if SPECIFICATIE_RE.fullmatch(pr.specificatie) else ""
        sleutel = (pr.onderdeel, spec, pr.prestatie, pr.datum)
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        key = parse_sortdata(tr.find_all("td", recursive=False)[2])[3]
        results.append(Resultaat(
            onderdeel=pr.onderdeel, onderdeel_id="", specificatie=spec, prestatie=pr.prestatie,
            waarde=pr.waarde, wind=pr.wind, datum=pr.datum, plaats=pr.plaats, land=pr.land,
            wedstrijd=pr.wedstrijd, wedstrijd_url=meets.get(key, ("", ""))[1]))
    return results


# --------------------------------------------------------------------------- importer

class AtletiekNuPRImporter(Importer):
    """
    PR's en alle prestaties van één atleet op atletiek.nu.
    parse(bron) geeft (atletieknu_id, [PR, ...], [Resultaat, ...]) terug.
    """

    bron = "atletieknu"
    site = "atletiek.nu"
    url_patronen = (r"atletiek\.nu/atleet/profiel/\d+",)
    imiteer_browser = "chrome"  # atletiek.nu blokkeert de Python-bibliotheek requests

    def controleer_pagina(self, html: str, url: str) -> None:
        # atletiek.nu toont soms een "Checking your browser"-pagina aan scripts.
        if "Checking your browser" in html and "persoonlijkerecords" not in html:
            raise ImportFout(
                "atletiek.nu gaf een browsercontrole-pagina terug i.p.v. het profiel.\n"
                "Open het profiel in je browser, sla het op (Ctrl+S, 'Alleen HTML') en importeer dat bestand.")

    def laad_html(self, bron: str) -> str:
        """Accepteert een atleet-id, een profiel-URL of een pad naar een opgeslagen HTML-bestand."""
        if self.is_lokaal(bron):
            return self.lees_bestanden(bron)[0][1]
        url = PROFILE_URL.format(id=bron) if bron.isdigit() else bron.split("#")[0]
        return self.haal_op(url)

    def parse(self, bron: str) -> tuple[str, list[PR], list[Resultaat]]:
        html = self.laad_html(bron)
        return atleet_id_uit(bron, html), parse_prs(html), parse_results(html)


def atleet_id_uit(bron: str, html: str = "") -> str:
    """atletiek.nu-profiel-id uit een id, URL of (opgeslagen) pagina; '' als onbekend."""
    if bron.isdigit():
        return bron
    m = re.search(r"/atleet/profiel/(\d+)", bron) or re.search(r"/atleet/profiel/(\d+)", html or "")
    return m.group(1) if m else ""


# Functie-interface, voor scripts en bestaande code.

can_handle = AtletiekNuPRImporter.can_handle


def parse(url: str) -> tuple[str, list[PR], list[Resultaat]]:
    """(atletieknu_id, PR's, alle prestaties) van het profiel achter de link."""
    return AtletiekNuPRImporter().parse(url)


def load_html(source: str) -> str:
    return AtletiekNuPRImporter().laad_html(source)


# --------------------------------------------------------------------------- uitvoer

def main() -> None:
    ap = argparse.ArgumentParser(description="Exporteer PR's en prestaties van atletiek.nu")
    ap.add_argument("bron", help="atleet-id, profiel-URL of opgeslagen HTML-bestand")
    ap.add_argument("--csv", default="prs.csv", help="pad voor PR-CSV (standaard prs.csv)")
    ap.add_argument("--resultaten", nargs="?", const="resultaten.csv", metavar="CSV",
                    help="exporteer ook alle prestaties (standaard naar resultaten.csv)")
    ap.add_argument("--json", help="optioneel pad voor JSON-uitvoer {'prs': [...], 'resultaten': [...]}")
    ap.add_argument("--alleen-belangrijk", action="store_true",
                    help="alleen de PR-rijen die de site standaard toont")
    args = ap.parse_args()

    try:
        html = load_html(args.bron)
    except ImportFout as fout:
        sys.exit(str(fout))

    prs = parse_prs(html)
    if args.alleen_belangrijk:
        prs = [p for p in prs if p.belangrijk]
    pr_rows = [asdict(p) for p in prs]
    write_csv(args.csv, pr_rows, PR.__dataclass_fields__)

    for p in prs:
        spec = f" ({p.specificatie})" if p.specificatie else ""
        wind = f" [{p.wind}]" if p.wind else ""
        print(f"{p.onderdeel + spec:<36} {p.prestatie:>9}{wind:<12} {p.datum}  {p.plaats}")
    print(f"\n{len(prs)} PR's geschreven naar {args.csv}")

    res_rows = []
    if args.resultaten:
        results = parse_results(html)
        res_rows = [asdict(r) for r in results]
        write_csv(args.resultaten, res_rows, Resultaat.__dataclass_fields__)
        print("\nPrestaties per onderdeel:")
        for (ond, spec), n in Counter((r.onderdeel, r.specificatie) for r in results).items():
            print(f"  {ond + (f' ({spec})' if spec else ''):<36} {n:>4}")
        print(f"{len(results)} prestaties geschreven naar {args.resultaten}")

    if args.json:
        data = {"prs": pr_rows, "resultaten": res_rows} if args.resultaten else {"prs": pr_rows}
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON geschreven naar {args.json}")


if __name__ == "__main__":
    main()