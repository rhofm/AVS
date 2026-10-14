"""
Export de persoonlijke records (PR's) én alle prestaties van een atleet op atletiek.nu
naar CSV/JSON.

Gebruik:
    python export_prs.py 123456                       # PR's -> prs.csv
    python export_prs.py 123456 --resultaten          # + alle prestaties -> resultaten.csv
    python export_prs.py https://www.atletiek.nu/atleet/profiel/123456/
    python export_prs.py profiel.html --resultaten    # parse een opgeslagen pagina
    python export_prs.py 123456 --resultaten mijn.csv --json alles.json

Vereist: pip install requests beautifulsoup4
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

PROFILE_URL = "https://www.atletiek.nu/atleet/profiel/{id}/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}
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

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def to_number(prestatie: str) -> float | None:
    """'1:54,71' -> 114.71 | '1.02:03,4' -> 3723.4 | '10,1h' -> 10.1 | '3785' -> 3785 | 'DNF' -> None"""
    s = prestatie.strip().rstrip("hH").strip().replace(",", ".")
    if not re.fullmatch(r"\d[\d.:]*", s):
        return None
    try:
        if ":" in s:
            head, sec = s.rsplit(":", 1)
            if "." in head:                       # uren: "1.02:03.4"
                h, m = head.split(".", 1)
                return round(int(h) * 3600 + int(m) * 60 + float(sec), 3)
            return round(int(head) * 60 + float(sec), 3)
        return float(s)
    except ValueError:
        return None


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
    soup = BeautifulSoup(html, "html.parser")
    graph = soup.find(id="graphTabs")
    if not graph:
        raise ValueError("Geen grafieken/prestaties gevonden (div#graphTabs ontbreekt).")
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


# --------------------------------------------------------------------------- uitvoer

def write_csv(path: str, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # -sig: opent goed in Excel
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


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

    html = load_html(args.bron)

    prs = parse_prs(html)
    if args.alleen_belangrijk:
        prs = [p for p in prs if p.belangrijk]
    pr_rows = [asdict(p) for p in prs]
    write_csv(args.csv, pr_rows)

    for p in prs:
        spec = f" ({p.specificatie})" if p.specificatie else ""
        wind = f" [{p.wind}]" if p.wind else ""
        print(f"{p.onderdeel + spec:<36} {p.prestatie:>9}{wind:<12} {p.datum}  {p.plaats}")
    print(f"\n{len(prs)} PR's geschreven naar {args.csv}")

    res_rows = []
    if args.resultaten:
        results = parse_results(html)
        res_rows = [asdict(r) for r in results]
        write_csv(args.resultaten, res_rows)
        print("\nPrestaties per onderdeel:")
        for (ond, spec), n in Counter((r.onderdeel, r.specificatie) for r in results).items():
            print(f"  {ond + (f' ({spec})' if spec else ''):<36} {n:>4}")
        print(f"{len(results)} prestaties geschreven naar {args.resultaten}")

    if args.json:
        data = {"prs": pr_rows, "resultaten": res_rows} if args.resultaten else {"prs": pr_rows}
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON geschreven naar {args.json}")


def load_html(source: str) -> str:
    """Accepteert een atleet-id, een profiel-URL of een pad naar een opgeslagen HTML-bestand."""
    path = Path(source)
    if path.is_file():
        return path.read_text(encoding="utf-8")

    url = PROFILE_URL.format(id=source) if source.isdigit() else source.split("#")[0]
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # atletiek.nu toont soms een "Checking your browser"-pagina aan scripts.
    if "Checking your browser" in html and "persoonlijkerecords" not in html:
        sys.exit(
            "atletiek.nu gaf een browsercontrole-pagina terug i.p.v. het profiel.\n"
            "Open het profiel in je browser, sla het op (Ctrl+S, 'Alleen HTML') en draai:\n"
            "    python export_prs.py pad/naar/profiel.html --resultaten"
        )
    return html


if __name__ == "__main__":
    main()