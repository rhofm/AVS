"""
Importeer het tijdschema van een wedstrijd op Seltec (uitslagen.atletiek.nl en andere Seltec LA-portals).

Bron: https://uitslagen.atletiek.nl/Competitions/Details/<id> ('Tijdschema'). Een meerdaagse
wedstrijd heeft per dag een eigen pagina (/Competitions/Details/<id>/<dag>, menu 'Dag 1',
'Dag 2', ...); die worden allemaal opgehaald. Per regel in de lijst (table.roundlisttimetable):
    tijd | onderdeel / ronde | categorieën / '(6 Series, 43 Atleten)' | status
Seltec toont geen eindtijden: de duur blijft onbekend. Een regel kan voor meer categorieën
tegelijk zijn ('U18M, U16J, U16M'); die blijft één regel.

Categorieën. Seltec gebruikt bij U18, U20, senioren en masters M = mannen en V = vrouwen,
maar bij U16 en jonger J = jongens en M = meisjes ('U18M' is een man, 'U16M' een meisje).
Daarom worden de codes vertaald naar een notatie zonder dubbelzinnigheid:
    U20M -> U20-M   U18V -> U18-V   U16J -> U16-M   U16M -> U16-V   SENV -> SEN-V   MASTERSM -> Masters-M
Andere tekst ('Junioren D U14 Meisjes') blijft zoals hij is.

Datum per dag: de pagina's noemen alleen 'Dag N'; de datum is de eerste dag uit de kop + (N - 1).

Gebruik:
    python seltec_tijdschema.py 19133
    python seltec_tijdschema.py https://uitslagen.atletiek.nl/Competitions/Details/19133
    python seltec_tijdschema.py opgeslagen_tijdschema.html --csv tijdschema.csv
    python seltec_tijdschema.py map_met_opgeslagen_dagen/

Vereist: pip install requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import asdict
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

try:                                    # als pakket: from importers import seltec_tijdschema
    from .atletieknu_tijdschema import TijdschemaRegel, _tijd
    from .base import ImportFout, clean, write_csv
    from .seltec import BASIS_URL, SeltecImporter, Wedstrijd, parse_wedstrijd, wedstrijd_id_uit_url
except ImportError:                     # als script: python seltec_tijdschema.py ...
    from atletieknu_tijdschema import TijdschemaRegel, _tijd  # type: ignore
    from base import ImportFout, clean, write_csv  # type: ignore
    from seltec import (BASIS_URL, SeltecImporter, Wedstrijd, parse_wedstrijd,  # type: ignore
                        wedstrijd_id_uit_url)

DETAILS_PAD = "/Competitions/Details/{id}"
DAG_RE = re.compile(r"/Competitions/Details/\d+/(\d+)")
CODE_RE = re.compile(r"(U\d{1,2}|SEN|MASTERS?)([MVJ])")          # 'U16J', 'SENV', 'MASTERSM'
CODE_OM_RE = re.compile(r"([MV])(SEN|U\d{1,2})")                  # 'MSEN', 'VSEN' (oude notatie)


# --------------------------------------------------------------------------- categorieën

def seltec_categorie(code: str) -> str:
    """Eén Seltec-code -> 'U16-V', 'U20-M', 'SEN-V', 'Masters-M'; onbekende tekst blijft gelijk."""
    c = clean(code)
    kaal = c.upper().replace(" ", "")
    if m := CODE_RE.fullmatch(kaal):
        leeftijd, letter = m.groups()
    elif m := CODE_OM_RE.fullmatch(kaal):
        letter, leeftijd = m.groups()
    else:
        return c
    jong = leeftijd.startswith("U") and int(leeftijd[1:]) <= 16
    if letter == "J":
        geslacht = "M"
    elif letter == "V":
        geslacht = "V"
    else:                                         # 'M': meisjes t/m U16, mannen vanaf U18
        geslacht = "V" if jong else "M"
    naam = "Masters" if leeftijd.startswith("MASTER") else leeftijd
    return f"{naam}-{geslacht}"


def categorieen(tekst: str) -> str:
    """'U18M, U16J, U16M' -> 'U18-M, U16-M, U16-V'."""
    return ", ".join(seltec_categorie(d) for d in clean(tekst).split(",") if d.strip())


# --------------------------------------------------------------------------- parsen

def _regels_tekst(td: Tag) -> list[str]:
    """De <div>-regels in een cel (onder de link), schoongemaakt; '&nbsp;' wordt ''."""
    a = td.find("a") or td
    return [clean(d.get_text().replace("\xa0", " ")) for d in a.find_all("div", recursive=False)]


def _dagnummer(soup: BeautifulSoup) -> int:
    """Het nummer van de getoonde dag (menu 'Dag N' met class 'selected'); 1 als er geen dagen zijn."""
    for li in soup.select("#EventMenuHeader li.selected a[href]"):
        if m := DAG_RE.search(li["href"]):
            return int(m.group(1))
    return 1


def dag_links(soup: BeautifulSoup) -> dict[int, str]:
    """Dagnummer -> pad van die dag, uit het menu ('Dag 1', 'Dag 2', ...)."""
    uit = {}
    for a in soup.select("#EventMenuHeader a[href]"):
        if m := DAG_RE.search(a["href"]):
            uit[int(m.group(1))] = a["href"]
    return uit


def _info(tekst: str) -> str:
    """'(6 Series, 43 Atleten)' -> '6 series, 43 atleten'."""
    return clean(tekst.strip().strip("()")).lower()


def parse_tijdschema(html: str, url: str = "") -> tuple[Wedstrijd, list[TijdschemaRegel], int, dict[int, str]]:
    """Wedstrijd, de regels van deze ene dagpagina, het nummer van deze dag en de links naar alle dagen."""
    soup = BeautifulSoup(html, "html.parser")
    tabel = soup.find("table", class_="roundlisttimetable")
    if tabel is None:
        raise ImportFout("Geen tijdschema gevonden op deze pagina (is het wel de Seltec-pagina 'Tijdschema'?).")
    wedstrijd = parse_wedstrijd(soup, url)
    if not wedstrijd.datum:
        raise ImportFout("Kan de datum van de wedstrijd niet lezen uit de kop van het tijdschema.")
    dag = _dagnummer(soup)
    datum = (date.fromisoformat(wedstrijd.datum) + timedelta(days=dag - 1)).isoformat()
    basis = f"{urlparse(url).scheme}://{urlparse(url).netloc}" if url.startswith("http") else BASIS_URL

    regels: list[TijdschemaRegel] = []
    for tr in tabel.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        tijd_cel, onderdeel_cel, cat_cel = (_regels_tekst(td) + ["", ""] for td in tds[:3])
        starttijd = _tijd(tijd_cel[0])
        onderdeel = onderdeel_cel[0]
        if not starttijd or not onderdeel:
            continue
        ronde = onderdeel_cel[1].lower()
        opmerking = [x for x in (tijd_cel[1], _info(cat_cel[1])) if x]
        if ronde == "meerkamp":                          # geen ronde, wel handig om te zien
            ronde = ""
            opmerking.insert(0, "meerkamp")
        link = tr.find("a", href=True)
        regels.append(TijdschemaRegel(
            datum=datum, starttijd=starttijd, eindtijd="", duur=None,
            onderdeel=onderdeel, onderdeel_code="",
            categorie=categorieen(cat_cel[0]), groep=None, ronde=ronde,
            opmerking=", ".join(opmerking),
            startlijst_url=urljoin(basis, link["href"]) if link else "",
        ))
    return wedstrijd, regels, dag, dag_links(soup)


# --------------------------------------------------------------------------- importer

def details_id(bron: str) -> str:
    """Wedstrijd-id uit een id of een Seltec-link ('/Details/19133/2' -> '19133')."""
    if str(bron).isdigit():
        return str(bron)
    return wedstrijd_id_uit_url(bron)


class SeltecTijdschemaImporter(SeltecImporter):
    """
    Tijdschema van een wedstrijd op Seltec. parse(bron) geeft (Wedstrijd, [TijdschemaRegel, ...]),
    alle dagen samen, op datum en tijd. Zelfde regels voor ophalen als de Seltec-uitslagen.
    """

    url_patronen = (r"(uitslagen\.atletiek\.nl|seltec)[^/]*/Competitions/Details/\d+",)
    timeout = 30

    def parse(self, bron: str) -> tuple[Wedstrijd, list[TijdschemaRegel]]:
        """
        Accepteert een wedstrijd-id, elke Seltec-link van de wedstrijd (tijdschema, uitslagen,
        deelnemers, onderdeellijst), een opgeslagen tijdschemapagina of een map met opgeslagen
        dagpagina's.
        """
        if self.is_lokaal(bron):
            wedstrijd, regels = None, []
            for uri, html in self.lees_bestanden(bron):
                w, rijen, _, _ = parse_tijdschema(html, uri)
                wedstrijd = wedstrijd or w
                regels += rijen
            return wedstrijd, _sorteer(regels)

        wid = details_id(bron)
        if not wid:
            raise ImportFout(f"Kan geen wedstrijd-id halen uit '{bron}'.")
        p = urlparse(str(bron))
        basis = f"{p.scheme or 'https'}://{p.netloc}" if p.netloc else BASIS_URL
        url = basis + DETAILS_PAD.format(id=wid)
        wedstrijd, regels, dag, dagen = parse_tijdschema(self.haal_op(url), url)
        for nr, pad in sorted(dagen.items()):
            if nr == dag:
                continue
            dag_url = urljoin(basis, pad)
            _, rijen, _, _ = parse_tijdschema(self.haal_op(dag_url), dag_url)
            regels += rijen
        regels = _sorteer(regels)
        self.log(f"{wedstrijd.naam} ({wedstrijd.plaats}, {wedstrijd.datum}) - "
                 f"{max(len(dagen), 1)} dag(en), {len(regels)} regels in het tijdschema")
        return wedstrijd, regels


def _sorteer(regels: list[TijdschemaRegel]) -> list[TijdschemaRegel]:
    """Op datum en tijd; dezelfde regel (zelfde onderdeellijst) uit twee bestanden telt één keer."""
    gezien, uit = set(), []
    for r in sorted(regels, key=lambda r: (r.datum, r.starttijd)):
        sleutel = (r.datum, r.starttijd, r.startlijst_url or (r.onderdeel, r.categorie, r.ronde))
        if sleutel not in gezien:
            gezien.add(sleutel)
            uit.append(r)
    return uit


def laad_tijdschema(bron: str, log=print) -> tuple[Wedstrijd, list[TijdschemaRegel]]:
    return SeltecTijdschemaImporter(log=log).parse(bron)


can_handle = SeltecTijdschemaImporter.can_handle


# --------------------------------------------------------------------------- script

def main() -> None:
    p = argparse.ArgumentParser(description="Tijdschema van een wedstrijd op Seltec (uitslagen.atletiek.nl).")
    p.add_argument("bron", help="wedstrijd-id, Seltec-link, opgeslagen HTML-bestand of map")
    p.add_argument("--csv", help="schrijf het tijdschema naar dit CSV-bestand")
    args = p.parse_args()
    try:
        wedstrijd, regels = laad_tijdschema(args.bron, log=lambda *a: print(*a, file=sys.stderr))
    except ImportFout as e:
        sys.exit(f"Fout: {e}")
    print(f"{wedstrijd.naam} - {wedstrijd.plaats}")
    for r in regels:
        ronde = f" ({r.ronde})" if r.ronde else ""
        print(f"{r.datum} {r.starttijd}  {r.onderdeel + ronde:<34} {r.categorie:<28} {r.opmerking}")
    if args.csv:
        write_csv(args.csv, [asdict(r) for r in regels])
        print(f"Opgeslagen: {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
