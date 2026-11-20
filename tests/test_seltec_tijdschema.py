"""Tests voor de import van het tijdschema van Seltec:
src/importers/seltec_tijdschema.py, en de Seltec-kant van src/wedstrijden/tijdschema_import.py.

Tegen opgeslagen, geanonimiseerde pagina's in fixtures/seltec_tijdschema/ (zie de README daar);
er wordt niets van internet gehaald.
"""

import shutil
import tempfile
from datetime import date
from pathlib import Path

from db.queries import OpslagFout
from importers import detect, seltec
from importers.base import ImportFout
from importers.seltec_tijdschema import (SeltecTijdschemaImporter, categorieen, laad_tijdschema,
                                         seltec_categorie)
from models import Atleet, Inschrijving, Onderdeel, ProgrammaOnderdeel, lees_categorie
from wedstrijden import chronoloog, planning
from wedstrijden.tijdschema_import import site_van, tijdschema_importeren
from hulp import opslag, verwacht as _verwacht

MAP = Path(__file__).resolve().parent / "fixtures" / "seltec_tijdschema"
NK1, NK2, CLUB = MAP / "nk_dag1.html", MAP / "nk_dag2.html", MAP / "club.html"
ATLETIEKNU = Path(__file__).resolve().parent / "fixtures" / "atletieknu_tijdschema" / "teams.html"
BASIS = "https://uitslagen.atletiek.nl/Competitions/Details/"


def _tekst(pad: Path) -> str:
    return pad.read_text(encoding="utf-8")


def _dag3() -> str:
    """Dag 2 nog eens, maar dan als 'Dag 3' (de fixtures hebben geen eigen derde dag)."""
    html = _tekst(NK2)
    html = html.replace('<li class="button selected"><a href="/Competitions/Details/19133/2">',
                        '<li class="button"><a href="/Competitions/Details/19133/2">')
    return html.replace('<li class="button"><a href="/Competitions/Details/19133/3">',
                        '<li class="button selected"><a href="/Competitions/Details/19133/3">')


class NepImporter(SeltecTijdschemaImporter):
    """Geeft opgeslagen pagina's terug in plaats van Seltec op te halen."""

    def __init__(self, paginas: dict[str, str]):
        super().__init__()
        self.paginas, self.opgehaald = paginas, []

    def haal_op(self, url: str) -> str:
        self.opgehaald.append(url)
        if url not in self.paginas:
            raise ImportFout(f"Seltec gaf fout 404 voor {url}.")
        return self.paginas[url]


def nk() -> NepImporter:
    return NepImporter({BASIS + "19133": _tekst(NK1), BASIS + "19133/2": _tekst(NK2), BASIS + "19133/3": _dag3()})


def club() -> NepImporter:
    return NepImporter({BASIS + "21085": _tekst(CLUB)})


# ---------------------------------------------------------------- categorieën

def test_categorieen():
    for code, verwacht in (("U20M", "U20-M"), ("U20V", "U20-V"), ("U18M", "U18-M"), ("U18V", "U18-V"),
                           ("U16M", "U16-V"), ("U16J", "U16-M"), ("U8M", "U8-V"), ("u14j", "U14-M"),
                           ("SENM", "SEN-M"), ("SENV", "SEN-V"), ("MSEN", "SEN-M"), ("VSEN", "SEN-V"),
                           ("MASTERSM", "Masters-M"), ("MASTERSV", "Masters-V"),
                           ("Junioren D U14 Meisjes", "Junioren D U14 Meisjes")):
        assert seltec_categorie(code) == verwacht, code
    assert categorieen("U18M, U16J, U16M") == "U18-M, U16-M, U16-V"
    for tekst, verwacht in (("U16-V", ("U16", "V")), ("U18-M", ("U18", "M")), ("SEN-V", ("Senior", "V")),
                            ("Masters-M", ("Masters", "M"))):
        assert lees_categorie(tekst) == verwacht, tekst


def test_past_bij_meer_categorieen():
    def regel(cat):
        return ProgrammaOnderdeel(1, date(2026, 10, 10), "12:30", onderdeel_tekst="Verspringen", categorie=cat)

    ver = regel("U18-M, U16-M, U16-V, U14-M, U14-V")
    assert chronoloog.past_bij(ver, "U16", "V") is True
    assert chronoloog.past_bij(ver, "U18", "M") is True
    assert chronoloog.past_bij(ver, "U18", "V") is False
    assert chronoloog.past_bij(ver, "U12", "M") is False
    assert chronoloog.past_bij(ver, "U16", "X") is None          # geslacht onbekend: zelf kijken
    assert chronoloog.past_bij(ver, None, "V") is None           # geboortedatum onbekend
    lang = regel("SEN-M, SEN-V, Masters-M, Masters-V")
    assert chronoloog.past_bij(lang, "U16", "V") is False and chronoloog.past_bij(lang, "Senior", "V") is True
    assert chronoloog.past_bij(regel("Junioren D U14 Meisjes, U12-V"), "U14", "V") is True


# ---------------------------------------------------------------- parsen

def test_nk_drie_dagen():
    imp = nk()
    w, regels = imp.parse("19133")
    assert imp.opgehaald == [BASIS + "19133", BASIS + "19133/2", BASIS + "19133/3"]
    assert (w.naam, w.plaats, w.datum, w.einddatum) == (
        "Test Kampioenschappen U18 & U20", "Teststad", "2026-09-18", "2026-09-20")
    per_dag = {d: [r for r in regels if r.datum == d] for d in ("2026-09-18", "2026-09-19", "2026-09-20")}
    assert [len(v) for v in per_dag.values()] == [8, 6, 6] and len(regels) == 20
    assert regels == sorted(regels, key=lambda r: (r.datum, r.starttijd))
    eerste = regels[0]
    assert (eerste.starttijd, eerste.onderdeel, eerste.ronde, eerste.categorie, eerste.opmerking) == (
        "14:00", "100 m", "series", "U20-M", "6 series, 43 atleten")
    assert eerste.startlijst_url == "https://uitslagen.atletiek.nl/Competitions/CurrentList/982708/19133"
    assert (eerste.duur, eerste.eindtijd, eerste.groep, eerste.onderdeel_code) == (None, "", None, "")
    assert [r.categorie for r in per_dag["2026-09-18"] if r.onderdeel == "100 m"] == ["U20-M", "U18-M", "U18-V"]
    ver = per_dag["2026-09-19"][0]
    assert (ver.starttijd, ver.onderdeel, ver.ronde, ver.opmerking) == (
        "11:00", "Verspringen", "kwalificatie", "2 groepen, 27 atleten")


def test_club_meerkamp_en_lijsten():
    w, regels = laad_tijdschema(str(CLUB), log=lambda *a: None)
    assert (w.naam, w.plaats, w.datum) == ("Testclubkampioenschappen 2026", "Proefdorp", "2026-10-10")
    assert len(regels) == 8 and {r.datum for r in regels} == {"2026-10-10"}
    drie = regels[0]
    assert (drie.onderdeel, drie.ronde, drie.categorie, drie.opmerking) == (
        "3000 m", "timed heats", "SEN-M, SEN-V, Masters-M, Masters-V", "1 serie, 8 atleten")
    honderd = next(r for r in regels if r.onderdeel == "100 m")
    assert (honderd.ronde, honderd.categorie, honderd.opmerking) == ("", "U18-M, U16-M", "meerkamp, 1 serie, 4 atleten")
    assert next(r for r in regels if r.onderdeel == "80 m").categorie == "U16-V, U14-M"
    assert next(r for r in regels if r.onderdeel == "60m").categorie == "Junioren D U14 Meisjes"


def test_links_en_bestanden():
    assert seltec.wedstrijd_id_uit_url(BASIS + "19133/2") == "19133"
    assert seltec.overzicht_url(BASIS + "19133/2") == "https://uitslagen.atletiek.nl/Competitions/Resultoverview/19133"
    assert SeltecTijdschemaImporter.can_handle(BASIS + "19133")
    assert not SeltecTijdschemaImporter.can_handle("https://uitslagen.atletiek.nl/Competitions/Resultoverview/19133")
    # De algemene detectie houdt Seltec-links bij de uitslagen-importer (zoals voorheen).
    assert type(detect.kies_importer(BASIS + "19133")) is seltec.SeltecImporter
    # Elke link naar de wedstrijd haalt het tijdschema op, alle dagen.
    for bron in ("https://uitslagen.atletiek.nl/Competitions/Resultoverview/19133",
                 "https://uitslagen.atletiek.nl/Competitions/CurrentList/982708/19133", BASIS + "19133/2"):
        imp = nk()
        assert len(imp.parse(bron)[1]) == 20 and imp.opgehaald[0] == BASIS + "19133"
    # Een map met opgeslagen dagen; dezelfde dag twee keer telt één keer.
    with tempfile.TemporaryDirectory() as tmp:
        for i, pad in enumerate((NK1, NK2, NK2)):
            shutil.copy(pad, Path(tmp) / f"dag{i}.html")
        w, regels = laad_tijdschema(tmp, log=lambda *a: None)
        assert len(regels) == 14 and w.naam == "Test Kampioenschappen U18 & U20"
    _verwacht(ImportFout, lambda: nk().parse("https://uitslagen.atletiek.nl/Competitions/Past"))
    _verwacht(ImportFout, lambda: NepImporter({BASIS + "1": "<html><body><h1>Leeg</h1></body></html>"}).parse("1"))
    _verwacht(ImportFout, lambda: NepImporter({}).parse("1"))                   # 'resource cannot be found'


# ---------------------------------------------------------------- in de database


def test_importeren_in_database():
    with opslag() as db:
        for naam, eenheid, lager in (("100m", "tijd", True), ("80m", "tijd", True),
                                     ("Hoogspringen", "hoogte", False), ("Verspringen", "afstand", False)):
            db.onderdeel_opslaan(Onderdeel(naam, eenheid, lager))
        w = planning.plan_wedstrijd(db, "Clubkampioenschappen", date(2026, 10, 10), "Proefdorp", BASIS + "21085")
        assert w.bron == "seltec"
        assert site_van("21085", w) == "seltec" and site_van(str(CLUB)) == "seltec"
        assert site_van(str(ATLETIEKNU)) == "atletieknu" and site_van("21085") == "atletieknu"
        _verwacht(OpslagFout, lambda: site_van("https://www.seltec.nl/x"))

        imp = club()
        v = tijdschema_importeren(db, w.id, importer=imp)              # link van de wedstrijd zelf
        assert imp.opgehaald == [BASIS + "21085"]
        assert (v.aantal, v.gekoppeld, v.zonder_duur, v.waarschuwingen) == (8, 4, 8, [])
        assert v.niet_gekoppeld == ["3000 m", "Kogelstoten", "60m", "Speerwerpen"]

        prog = db.programma(w.id)
        ver = next(p for p in prog if p.naam == "Verspringen")
        assert (ver.categorie, ver.ronde, ver.opmerking, ver.onderdeel_id) == (
            "U18-M, U16-M, U16-V, U14-M, U14-V", "", "meerkamp, 1 groep, 17 atleten", db.onderdeel("Verspringen").id)

        # Persoonlijk schema: een meisje U16 (Seltec 'U16M') doet 80 m en verspringen, niet de 100 m (U18M = mannen).
        lisa = db.atleet_opslaan(Atleet("Lisa", "Proefmans", geslacht="V", geboortedatum="2011-05-01"))   # U16 in 2026
        for naam in ("100m", "80m", "Hoogspringen", "Verspringen"):
            db.inschrijving_opslaan(Inschrijving(lisa.master_id, w.id, db.onderdeel(naam).id))
        schema = chronoloog.persoonlijk_schema(db, w.id, lisa.master_id)
        assert [(s.regel.starttijd, s.regel.naam) for s in schema] == [("12:10", "80 m"), ("12:30", "Verspringen")]

        # Ook met een opgeslagen bestand, zonder importer: de site volgt uit de inhoud.
        assert tijdschema_importeren(db, w.id, str(CLUB)).aantal == 8 and len(db.programma(w.id)) == 8
