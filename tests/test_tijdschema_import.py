"""Tests voor de import van het tijdschema van atletiek.nu:
src/importers/atletieknu_tijdschema.py en src/wedstrijden/tijdschema_import.py.

Tegen opgeslagen, geanonimiseerde pagina's in fixtures/atletieknu_tijdschema/ (zie de
README daar); er wordt niets van internet gehaald. Werkt met pytest en los:
`python tests/test_tijdschema_import.py`.
"""

import contextlib
import io
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from db.init_db import init_db  # noqa: E402
from db.queries import Opslag, OpslagFout  # noqa: E402
from importers import detect  # noqa: E402
from importers.atletieknu_tijdschema import (AtletiekNuTijdschemaImporter, groep_uit,  # noqa: E402
                                             laad_tijdschema)
from importers.base import ImportFout  # noqa: E402
from models import Atleet, Inschrijving, Onderdeel, lees_categorie  # noqa: E402
from wedstrijden import chronoloog, planning  # noqa: E402
from wedstrijden.tijdschema_import import tijdschema_importeren, zoek_onderdeel  # noqa: E402

MAP = Path(__file__).resolve().parent / "fixtures" / "atletieknu_tijdschema"
MEERKAMP, TEAMS = MAP / "meerkamp.html", MAP / "teams.html"
TESTSLEUTEL = "77" * 32


def _verwacht(fout, fn) -> None:
    try:
        fn()
    except fout:
        return
    raise AssertionError(f"{fout.__name__} verwacht")


def _laad(pad):
    return laad_tijdschema(str(pad), log=lambda *a: None)


class NepImporter(AtletiekNuTijdschemaImporter):
    """Geeft een opgeslagen pagina terug in plaats van atletiek.nu op te halen."""

    def __init__(self, pagina: Path, inhoud: str | None = None):
        super().__init__()
        self.pagina, self.inhoud, self.opgehaald = pagina, inhoud, []

    def haal_op(self, url: str) -> str:
        self.opgehaald.append(url)
        html = self.inhoud if self.inhoud is not None else self.pagina.read_text(encoding="utf-8")
        self.controleer_pagina(html, url)
        return html


# ---------------------------------------------------------------- parsen

def test_meerkamp_twee_dagen_met_tijdlijn():
    w, regels = _laad(MEERKAMP)
    assert (w.naam, w.plaats, w.datum, w.einddatum) == ("Testmeerkamp 2026", "Proefdorp", "2026-08-29", "2026-08-30")
    assert len(regels) == 15
    assert [r.datum for r in regels].count("2026-08-29") == 9 and [r.datum for r in regels].count("2026-08-30") == 6
    assert [r.starttijd for r in regels] == sorted(r.starttijd for r in regels[:9]) + sorted(r.starttijd for r in regels[9:])
    r = next(r for r in regels if r.starttijd == "10:55")
    assert (r.onderdeel, r.onderdeel_code, r.categorie, r.groep, r.duur, r.eindtijd, r.opmerking) == (
        "80 meter horden", "80mH", "VU20+V Masters", None, 15, "11:10", "2 series")
    hoog = next(r for r in regels if r.starttijd == "11:05")
    assert (hoog.onderdeel, hoog.duur, hoog.opmerking) == ("Hoogspringen", 65, "hoog 1")
    assert next(r for r in regels if r.datum == "2026-08-30" and r.starttijd == "09:00").starttijd == "09:00"  # '9:00'
    zonder = next(r for r in regels if r.datum == "2026-08-30" and r.onderdeel_code == "80mH")
    assert (zonder.duur, zonder.eindtijd, zonder.opmerking) == (None, "", "")       # geen balk in de tijdlijn
    assert all(r.ronde == "" for r in regels)                                       # '2 series' is geen ronde
    assert all(r.startlijst_url.startswith("https://www.atletiek.nu/wedstrijd/startlijst/") for r in regels)


def test_teams_groepen_en_reserves():
    w, regels = _laad(TEAMS)
    assert (w.naam, w.datum) == ("Test Teamwedstrijd 2026", "2026-09-19")
    assert len(regels) == 7 and not any("Reserve" in r.onderdeel for r in regels)  # 'n/a' valt weg
    hoog = [(r.starttijd, r.categorie, r.groep) for r in regels if r.onderdeel == "Hoogspringen"]
    assert hoog == [("11:46", "Vrouwen", 1), ("14:46", "Vrouwen", 2)]
    assert [(r.categorie, r.groep) for r in regels if r.onderdeel_code == "Ver"] == [("Mannen", 1), ("Mannen", 2)]
    assert all(r.duur is None for r in regels)                                      # geen tijdlijn op deze pagina


def test_hulpjes():
    assert groep_uit("Vrouwen groep A") == ("Vrouwen", 1)
    assert groep_uit("Mannen groep 2") == ("Mannen", 2)
    assert groep_uit("U16-V") == ("U16-V", None)
    for tekst, verwacht in (("U16-V", ("U16", "V")), ("SEN-M", ("Senior", "M")), ("Msen", ("Senior", "M")),
                            ("VU20+V Masters", ("U20", "V")), ("MU20 + M Masters", ("U20", "M")),
                            ("MU16", ("U16", "V")), ("JU14", ("U14", "M")), ("Vrouwen", ("Senior", "V"))):
        assert lees_categorie(tekst) == verwacht, tekst
    o = [Onderdeel("80m horden", "tijd", True), Onderdeel("Verspringen", "afstand", False),
         Onderdeel("100m", "tijd", True), Onderdeel("4x100m", "tijd", True)]
    assert zoek_onderdeel(o, "80 meter horden", "80mH").naam == "80m horden"
    assert zoek_onderdeel(o, "Verspringen", "Ver").naam == "Verspringen"
    assert zoek_onderdeel(o, "100 meter", "100m").naam == "100m"
    assert zoek_onderdeel(o, "4 x 100 meter", "4x100m").naam == "4x100m"
    assert zoek_onderdeel(o, "Hoogspringen", "Hoog") is None


def test_links_en_detectie():
    for url in ("https://www.atletiek.nu/wedstrijd/chronoloog/90001/",
                "https://atletiek.nu/wedstrijd/chronoloog/90001"):
        assert AtletiekNuTijdschemaImporter.can_handle(url)
        assert isinstance(detect.kies_importer(url), AtletiekNuTijdschemaImporter)
    assert not AtletiekNuTijdschemaImporter.can_handle("https://www.atletiek.nu/wedstrijd/uitslagen/90001/")
    assert not isinstance(detect.kies_importer("https://www.atletiek.nu/wedstrijd/main/90001/"),
                          AtletiekNuTijdschemaImporter)
    # Elke link naar de wedstrijd (of alleen het id) haalt het tijdschema op.
    for bron in ("90001", "https://www.atletiek.nu/wedstrijd/main/90001/",
                 "https://www.atletiek.nu/wedstrijd/uitslagen/90001/"):
        imp = NepImporter(MEERKAMP)
        assert len(imp.parse(bron)[1]) == 15
        assert imp.opgehaald == ["https://www.atletiek.nu/wedstrijd/chronoloog/90001/"]
    _verwacht(ImportFout, lambda: NepImporter(MEERKAMP).parse("https://www.atletiek.nu/kalender/"))
    _verwacht(ImportFout, lambda: NepImporter(MEERKAMP, "<html><body>Checking your browser</body></html>").parse("1"))
    _verwacht(ImportFout, lambda: NepImporter(MEERKAMP, "<html><body><p>Leeg</p></body></html>").parse("1"))


# ---------------------------------------------------------------- in de database

@contextlib.contextmanager
def opslag():
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            yield db


def test_importeren_in_database():
    with opslag() as db:
        for naam, eenheid, lager in (("80m horden", "tijd", True), ("100m horden", "tijd", True),
                                     ("Hoogspringen", "hoogte", False), ("Verspringen", "afstand", False)):
            db.onderdeel_opslaan(Onderdeel(naam, eenheid, lager))
        w = planning.plan_wedstrijd(db, "Testmeerkamp", date(2026, 8, 29), "Proefdorp",
                                    "https://www.atletiek.nu/wedstrijd/main/90001/")
        imp = NepImporter(MEERKAMP)
        v = tijdschema_importeren(db, w.id, importer=imp)            # link van de wedstrijd zelf
        assert imp.opgehaald == ["https://www.atletiek.nu/wedstrijd/chronoloog/90001/"]
        assert (v.aantal, v.gekoppeld, v.zonder_duur) == (15, 10, 2)   # zo 9:15 MU20: geen balk
        assert v.niet_gekoppeld == ["60 meter horden", "100 meter", "110 meter horden", "Discuswerpen"]
        assert v.waarschuwingen == [] and "15 regels" in v.tekst and "Discuswerpen" in v.tekst

        prog = db.programma(w.id)
        r = next(p for p in prog if p.starttijd == "11:40" and p.naam == "80 meter horden")
        assert (r.categorie, r.duur, r.eindtijd, r.opmerking) == ("U16-V", 15, "11:55", "3 series")
        assert r.onderdeel_id == db.onderdeel("80m horden").id
        assert next(p for p in prog if p.naam == "Discuswerpen").onderdeel_id is None   # wel als tekst

        # Persoonlijk schema op basis van het geïmporteerde tijdschema.
        anna = db.atleet_opslaan(Atleet("Anna", "Aalbers", geslacht="V", geboortedatum="2012-03-01"))   # U16 in 2026
        db.inschrijving_opslaan(Inschrijving(anna.master_id, w.id, db.onderdeel("80m horden").id))
        db.inschrijving_opslaan(Inschrijving(anna.master_id, w.id, db.onderdeel("Hoogspringen").id))
        schema = chronoloog.persoonlijk_schema(db, w.id, anna.master_id)
        assert [(s.regel.starttijd, s.regel.naam) for s in schema] == [("11:40", "80 meter horden")]   # Hoog is SEN-V/VU20

        # Opnieuw importeren vervangt; een fout laat het oude tijdschema staan.
        assert tijdschema_importeren(db, w.id, importer=NepImporter(MEERKAMP)).aantal == 15
        assert len(db.programma(w.id)) == 15
        _verwacht(OpslagFout, lambda: tijdschema_importeren(
            db, w.id, importer=NepImporter(MEERKAMP, "<html><body>Checking your browser</body></html>")))
        assert len(db.programma(w.id)) == 15


def test_importeren_randgevallen():
    with opslag() as db:
        zonder_link = planning.plan_wedstrijd(db, "Handmatig", date(2026, 9, 19))
        _verwacht(OpslagFout, lambda: tijdschema_importeren(db, zonder_link.id, importer=NepImporter(TEAMS)))
        _verwacht(OpslagFout, lambda: tijdschema_importeren(db, zonder_link.id, "https://www.seltec.nl/x",
                                                            importer=NepImporter(TEAMS)))
        _verwacht(OpslagFout, lambda: tijdschema_importeren(db, 999, "1", importer=NepImporter(TEAMS)))
        # Opgeslagen bestand als bron; groepen komen mee; andere datum geeft een waarschuwing.
        v = tijdschema_importeren(db, zonder_link.id, str(TEAMS))
        assert v.aantal == 7 and v.waarschuwingen == [] and v.zonder_duur == 7
        assert [(p.categorie, p.groep) for p in db.programma(zonder_link.id) if p.naam == "Hoogspringen"] == [
            ("Vrouwen", 1), ("Vrouwen", 2)]
        ander = planning.plan_wedstrijd(db, "Andere dag", date(2026, 10, 3))
        v = tijdschema_importeren(db, ander.id, str(TEAMS))
        assert v.waarschuwingen and "Klopt de link?" in v.tekst


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for naam, fn in tests:
        fn()
        print(f"ok  {naam}")
    print(f"{len(tests)} tests geslaagd")
