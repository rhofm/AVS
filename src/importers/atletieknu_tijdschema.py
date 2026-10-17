"""
Importeer het tijdschema (chronoloog) van een wedstrijd op atletiek.nu.

Bron: https://www.atletiek.nu/wedstrijd/chronoloog/<id>/ . Die pagina heeft per dag:
  * een lijst (div#day<N>chronologischtab): tijd, startgroep (categorie) en onderdeel,
    met in grijs het aantal series ('2 series') of de plek ('hoog 1', 'ver 2');
  * soms een tijdlijn (div#day<N>visueeltab) met per onderdeel 'begin - eind'. Daaruit
    komt de duur; zonder tijdlijn blijft de duur onbekend.
Een regel in de lijst en een balk in de tijdlijn horen bij elkaar via dezelfde
startlijst-URL (/wedstrijd/startlijst/<startgroep>/<onderdeel>/).

'groep A' / 'groep B' in de startgroep wordt groep 1 / 2; de rest is de categorie
('Vrouwen groep A' -> categorie 'Vrouwen', groep 1). Regels zonder tijd ('n/a', bijv.
reserves) worden overgeslagen.

Gebruik:
    python atletieknu_tijdschema.py 43465
    python atletieknu_tijdschema.py https://www.atletiek.nu/wedstrijd/main/43465/
    python atletieknu_tijdschema.py opgeslagen_tijdschema.html --csv tijdschema.csv

Vereist: pip install requests beautifulsoup4 curl_cffi
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup, Tag

try:                                    # als pakket: from importers import atletieknu_tijdschema
    from .atletieknu_wedstrijd import (BASIS_URL, AtletiekNuWedstrijdImporter, Wedstrijd, parse_datum,
                                       parse_wedstrijd, wedstrijd_id_uit_url)
    from .base import ImportFout, clean, write_csv
except ImportError:                     # als script: python atletieknu_tijdschema.py ...
    from atletieknu_wedstrijd import (BASIS_URL, AtletiekNuWedstrijdImporter, Wedstrijd,  # type: ignore
                                      parse_datum, parse_wedstrijd, wedstrijd_id_uit_url)
    from base import ImportFout, clean, write_csv  # type: ignore

TIJDSCHEMA_URL = BASIS_URL + "/wedstrijd/chronoloog/{id}/"

TIJD_RE = re.compile(r"^(\d{1,2})[:.](\d{2})")
BALK_RE = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
URL_RE = re.compile(r"https?://[^\"'&]+/wedstrijd/startlijst/\d+/\d+/?")
GROEP_RE = re.compile(r"\s*\bgroep\s+([A-Z]|\d+)\b\s*", re.I)
SERIES_RE = re.compile(r"^\d+\s+series?$", re.I)                      # '2 series' = aantal, geen ronde
RONDE_RE = re.compile(r"\b(halve finale|kwartfinale|finale(?:\s+[A-Z])?|voorrondes?|series)\b", re.I)


@dataclass
class TijdschemaRegel:
    datum: str                  # ISO 'YYYY-MM-DD'
    starttijd: str              # 'HH:MM'
    eindtijd: str               # 'HH:MM' uit de tijdlijn; '' = onbekend
    duur: int | None            # minuten; None = onbekend
    onderdeel: str              # volledige naam, bijv. '80 meter horden'
    onderdeel_code: str         # code van atletiek.nu, bijv. '80mH'
    categorie: str              # startgroep zonder 'groep X', bijv. 'U16-V', 'Vrouwen'
    groep: int | None           # 'groep A' -> 1, 'groep B' -> 2; None = één groep
    ronde: str                  # 'finale', 'series', ... ('' als het niet in de naam staat)
    opmerking: str              # grijze regel: '2 series', 'hoog 1', ...
    startlijst_url: str


# --------------------------------------------------------------------------- hulpjes

def _tijd(tekst: str) -> str:
    """'9:00 ' -> '09:00'; '' als er geen tijd staat ('n/a')."""
    m = TIJD_RE.match(clean(tekst))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _minuten(begin: str, eind: str) -> int | None:
    b = datetime.strptime(begin, "%H:%M")
    e = datetime.strptime(eind, "%H:%M")
    if e < b:                                    # na middernacht
        e += timedelta(days=1)
    minuten = int((e - b).total_seconds() // 60)
    return minuten or None


def _naam_en_code(td: Tag) -> tuple[str, str]:
    """Uit een cel met <span class=visible-xs-inline>code</span><span class=hidden-xs>naam</span>."""
    a = td.find("a") or td
    kort = a.find("span", class_="visible-xs-inline")
    lang = a.find("span", class_="hidden-xs")
    if kort or lang:
        code = clean(kort.get_text()) if kort else ""
        naam = clean(lang.get_text()) if lang else code
        return naam or code, code or naam
    tekst = clean(a.get_text())
    return tekst, tekst


def _grijs(td: Tag) -> str:
    i = td.find("i")
    if not i:
        return ""
    lang = i.find("span", class_="hidden-xs")
    return clean((lang or i).get_text())


def groep_uit(startgroep: str) -> tuple[str, int | None]:
    """'Vrouwen groep A' -> ('Vrouwen', 1); 'Mannen groep 2' -> ('Mannen', 2); 'U16-V' -> ('U16-V', None)."""
    m = GROEP_RE.search(startgroep)
    if not m:
        return startgroep, None
    w = m.group(1)
    groep = int(w) if w.isdigit() else ord(w.upper()) - ord("A") + 1
    rest = clean(GROEP_RE.sub(" ", startgroep, count=1))
    return rest, groep


def _dag_datums(soup: BeautifulSoup, wedstrijd: Wedstrijd) -> dict[int, str]:
    """Dagnummer -> datum. Uit de kop van de tijdlijn als die er is, anders eerste dag + (N - 1)."""
    datums: dict[int, str] = {}
    for pane in soup.select("div[id^=day][id$=visueeltab]"):
        nr = re.match(r"day(\d+)", pane["id"])
        kop = pane.find("th", attrs={"colspan": True})
        if nr and kop:
            d = parse_datum(clean(kop.get_text()))
            if d:
                datums[int(nr.group(1))] = d
    if wedstrijd.datum:
        start = date.fromisoformat(wedstrijd.datum)
        for pane in soup.select("div[id^=day][id$=chronologischtab]"):
            nr = int(re.match(r"day(\d+)", pane["id"]).group(1))
            datums.setdefault(nr, (start + timedelta(days=nr - 1)).isoformat())
    return datums


def _tijdlijn(soup: BeautifulSoup) -> dict[str, tuple[str, str]]:
    """startlijst-URL -> (begin, eind) uit de balken van de tijdlijn."""
    uit = {}
    for balk in soup.select("div[id$=visueeltab] div.bar[title]"):
        url = URL_RE.search(balk.get("onclick", ""))
        tijden = BALK_RE.search(balk.get("title", ""))
        if url and tijden:
            uit[url.group(0)] = (_tijd(tijden.group(1)), _tijd(tijden.group(2)))
    return uit


# --------------------------------------------------------------------------- parsen

def parse_tijdschema(html: str, url: str = "") -> tuple[Wedstrijd, list[TijdschemaRegel]]:
    """Wedstrijd + alle regels van het tijdschema, op dag en tijd."""
    soup = BeautifulSoup(html, "html.parser")
    wedstrijd = parse_wedstrijd(html, url)
    panes = soup.select("div[id^=day][id$=chronologischtab]")
    if not panes:
        raise ImportFout("Geen tijdschema gevonden op deze pagina (is het wel de pagina 'Tijdschema'?).")
    datums = _dag_datums(soup, wedstrijd)
    balken = _tijdlijn(soup)

    regels: list[TijdschemaRegel] = []
    for pane in panes:
        dag = int(re.match(r"day(\d+)", pane["id"]).group(1))
        datum = datums.get(dag, "")
        tabel = pane.find("table", class_="chronoloogtabel")
        if tabel is None:
            continue
        for tr in tabel.select("tbody tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 3:
                continue
            starttijd = _tijd(tds[0].get_text())
            if not starttijd or not datum:
                continue                                         # 'n/a' (bijv. reserves)
            startgroep, _ = _naam_en_code(tds[1])
            categorie, groep = groep_uit(startgroep)
            onderdeel, code = _naam_en_code(tds[2])
            grijs = _grijs(tds[2])
            link = tr.find("a", href=True)
            startlijst = link["href"] if link else ""
            m = URL_RE.search(startlijst)
            begin_eind = balken.get(m.group(0)) if m else None
            eindtijd, duur = "", None
            if begin_eind and begin_eind[0] == starttijd:
                eindtijd, duur = begin_eind[1], _minuten(*begin_eind)
            ronde = ""
            if r := RONDE_RE.search(onderdeel):
                ronde = r.group(1).lower()
            elif grijs and not SERIES_RE.match(grijs) and RONDE_RE.fullmatch(grijs):
                ronde, grijs = grijs.lower(), ""
            regels.append(TijdschemaRegel(datum, starttijd, eindtijd, duur, onderdeel, code, categorie,
                                          groep, ronde, grijs, startlijst))
    regels.sort(key=lambda r: (r.datum, r.starttijd))
    return wedstrijd, regels


# --------------------------------------------------------------------------- importer

class AtletiekNuTijdschemaImporter(AtletiekNuWedstrijdImporter):
    """
    Tijdschema van een wedstrijd op atletiek.nu. parse(bron) geeft (Wedstrijd, [TijdschemaRegel, ...]).
    Ophalen zoals bij de uitslagen: met Chrome-imitatie en een pauze tussen verzoeken.
    """

    url_patronen = (r"atletiek\.nu/wedstrijd/chronoloog/\d+",)

    def controleer_pagina(self, html: str, url: str) -> None:
        if "Checking your browser" in html and "chronoloog" not in html and "pageTitle" not in html:
            raise ImportFout(
                f"atletiek.nu gaf een browsercontrole-pagina terug voor {url}.\n"
                "Open het tijdschema in je browser, sla het op (Ctrl+S, 'Alleen HTML') en importeer dat bestand.")

    def parse(self, bron: str) -> tuple[Wedstrijd, list[TijdschemaRegel]]:
        """
        Accepteert een wedstrijd-id, een wedstrijd-URL van atletiek.nu (elke pagina van de
        wedstrijd: main, uitslagen, chronoloog, ...) of een opgeslagen HTML-bestand.
        """
        if self.is_lokaal(bron):
            url, html = self.lees_bestanden(bron)[0]
            return parse_tijdschema(html, url)
        wid = bron if str(bron).isdigit() else wedstrijd_id_uit_url(bron)
        if not wid:
            raise ImportFout(f"Kan geen wedstrijd-id halen uit '{bron}'.")
        url = TIJDSCHEMA_URL.format(id=wid)
        wedstrijd, regels = parse_tijdschema(self.haal_op(url), url)
        self.log(f"{wedstrijd.naam} ({wedstrijd.plaats}, {wedstrijd.datum}) - {len(regels)} regels in het tijdschema")
        return wedstrijd, regels


def laad_tijdschema(bron: str, log=print) -> tuple[Wedstrijd, list[TijdschemaRegel]]:
    return AtletiekNuTijdschemaImporter(log=log).parse(bron)


can_handle = AtletiekNuTijdschemaImporter.can_handle


# --------------------------------------------------------------------------- script

def main() -> None:
    p = argparse.ArgumentParser(description="Tijdschema (chronoloog) van een wedstrijd op atletiek.nu.")
    p.add_argument("bron", help="wedstrijd-id, link naar de wedstrijd, of opgeslagen HTML-bestand")
    p.add_argument("--csv", help="schrijf het tijdschema naar dit CSV-bestand")
    args = p.parse_args()
    try:
        wedstrijd, regels = laad_tijdschema(args.bron, log=lambda *a: print(*a, file=sys.stderr))
    except ImportFout as e:
        sys.exit(f"Fout: {e}")
    print(f"{wedstrijd.naam} - {wedstrijd.plaats}")
    for r in regels:
        tijd = f"{r.starttijd}-{r.eindtijd}" if r.eindtijd else r.starttijd
        groep = f" groep {r.groep}" if r.groep else ""
        print(f"{r.datum} {tijd:<11} {r.onderdeel:<24} {r.categorie}{groep}  {r.opmerking}")
    if args.csv:
        write_csv(args.csv, [asdict(r) for r in regels])
        print(f"Opgeslagen: {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
