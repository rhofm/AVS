"""Het tijdschema van atletiek.nu of Seltec in de database zetten (prestaties.db: wedstrijd_programma).

    verslag = tijdschema_importeren(db, wedstrijd_id)                 # link van de wedstrijd zelf
    verslag = tijdschema_importeren(db, wedstrijd_id, "https://www.atletiek.nu/wedstrijd/main/45678/")
    verslag = tijdschema_importeren(db, wedstrijd_id, "https://uitslagen.atletiek.nl/Competitions/Details/19133")
    print(verslag.tekst)

Welke site het is, volgt uit de link (of uit de inhoud van een opgeslagen bestand); bij
alleen een nummer uit de link van de wedstrijd zelf (anders atletiek.nu).

Het hele tijdschema van de wedstrijd wordt vervangen (alles of niets): een nieuwe
versie importeren is dus gewoon nog een keer importeren.

Onderdelen worden gekoppeld aan de onderdelenlijst op naam of code ('80 meter horden',
'80mH' en '80m horden' zijn hetzelfde). Een onderdeel dat niet in de lijst staat,
komt er wel in als tekst, maar zonder koppeling: het telt dan niet mee voor het
persoonlijke schema. Het verslag noemt die onderdelen, zodat je ze kunt toevoegen
en opnieuw kunt importeren. Er worden nooit zelf onderdelen aangemaakt (de eenheid
en of lager beter is, weet de importer niet).

Geen SQL: alles via `Opslag`.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from db.queries import Opslag, OpslagFout
from importers.atletieknu_tijdschema import AtletiekNuTijdschemaImporter, TijdschemaRegel
from importers.base import Importer, ImportFout
from importers.seltec_tijdschema import SeltecTijdschemaImporter
from models import Onderdeel, ProgrammaOnderdeel, Wedstrijd

from .planning import bron_uit_link, normaliseer_link


def _sleutel(naam: str) -> str:
    """'80 meter horden' / '80mH' / '80m horden' -> '80mh'; 'Verspringen' -> 'verspringen'."""
    t = naam.lower().replace(",", ".")
    t = re.sub(r"(\d)\s*(meter|m)\b", r"\1m", t)
    t = re.sub(r"\bhorden\b", "h", t)
    t = re.sub(r"\bsteeple(chase)?\b", "sc", t)
    return re.sub(r"[\s\-]+", "", t)


def zoek_onderdeel(onderdelen: list[Onderdeel], naam: str, code: str = "") -> Onderdeel | None:
    """Het onderdeel uit de lijst met deze naam of code; None als er geen (of meer dan één) past."""
    gezocht = {_sleutel(x) for x in (naam, code) if x}
    treffers = [o for o in onderdelen if _sleutel(o.naam) in gezocht]
    return treffers[0] if len(treffers) == 1 else None


@dataclass
class ImportVerslag:
    wedstrijd_id: int
    aantal: int
    gekoppeld: int
    niet_gekoppeld: list[str] = field(default_factory=list)   # onderdeelnamen zonder koppeling
    zonder_duur: int = 0
    waarschuwingen: list[str] = field(default_factory=list)

    @property
    def tekst(self) -> str:
        delen = [f"Tijdschema geïmporteerd: {self.aantal} regels."]
        if self.niet_gekoppeld:
            delen.append(f"Niet in de onderdelenlijst (niet gekoppeld): {', '.join(self.niet_gekoppeld)}.")
        if self.zonder_duur:
            delen.append(f"{self.zonder_duur} regels zonder duur (atletiek.nu gaf geen eindtijd).")
        return " ".join([*delen, *self.waarschuwingen])


def naar_programma(wedstrijd_id: int, regels: list[TijdschemaRegel],
                   onderdelen: list[Onderdeel]) -> tuple[list[ProgrammaOnderdeel], list[str]]:
    """Regels van atletiek.nu -> regels voor wedstrijd_programma, en de namen die niet te koppelen waren."""
    uit, los = [], []
    for r in regels:
        o = zoek_onderdeel(onderdelen, r.onderdeel, r.onderdeel_code)
        if o is None and r.onderdeel not in los:
            los.append(r.onderdeel)
        uit.append(ProgrammaOnderdeel(
            wedstrijd_id, date.fromisoformat(r.datum), r.starttijd,
            onderdeel_id=o.id if o else None, onderdeel_tekst=r.onderdeel,
            categorie=r.categorie or None, ronde=r.ronde, groep=r.groep, duur=r.duur,
            opmerking=r.opmerking or None,
        ))
    return uit, los


def site_van(bron: str, wedstrijd: Wedstrijd | None = None) -> str:
    """'atletieknu' of 'seltec' voor een link, id of opgeslagen bestand; OpslagFout als het geen van beide is."""
    tekst = str(bron).lower()
    if Importer.is_lokaal(bron):
        html = Importer.lees_bestanden(bron)[0][1]
        return "seltec" if "roundlisttimetable" in html else "atletieknu"
    if tekst.isdigit():
        return "seltec" if wedstrijd and bron_uit_link(wedstrijd.bron_url) == "seltec" else "atletieknu"
    if "atletiek.nu/wedstrijd/" in tekst:
        return "atletieknu"
    if ("uitslagen.atletiek.nl" in tekst or "seltec" in tekst) and "/competitions/" in tekst:
        return "seltec"
    raise OpslagFout("Dit is geen link naar een wedstrijd op atletiek.nu of Seltec.")


def _ophalen(bron: str, wedstrijd: Wedstrijd | None = None,
             importer: Importer | None = None) -> tuple[object, list[TijdschemaRegel]]:
    """(wedstrijd zoals de site hem geeft, regels). OpslagFout bij een onbekende link of een leeg tijdschema."""
    site = site_van(bron, wedstrijd)
    importer = importer or (SeltecTijdschemaImporter() if site == "seltec" else AtletiekNuTijdschemaImporter())
    try:
        bron_wedstrijd, regels = importer.parse(bron)
    except ImportFout as e:
        raise OpslagFout(str(e)) from None
    if not regels:
        raise OpslagFout("Het tijdschema op de site is (nog) leeg; er is niets veranderd.")
    return bron_wedstrijd, regels


def _opslaan(db: Opslag, w: Wedstrijd, bron_wedstrijd, regels: list[TijdschemaRegel]) -> ImportVerslag:
    """Regels koppelen aan de onderdelenlijst en het tijdschema van `w` ermee vervangen."""
    programma, los = naar_programma(w.id, regels, db.onderdelen())
    db.programma_vervangen(w.id, programma)

    verslag = ImportVerslag(w.id, len(programma), sum(p.onderdeel_id is not None for p in programma),
                            los, sum(p.duur is None for p in programma))
    dagen = sorted({p.datum for p in programma})
    if w.datum not in dagen:
        verslag.waarschuwingen.append(
            f"Let op: het tijdschema is van {', '.join(d.isoformat() for d in dagen)}, de wedstrijd staat op "
            f"{w.datum.isoformat()} ('{bron_wedstrijd.naam}'). Klopt de link?")
    return verslag


def tijdschema_importeren(db: Opslag, wedstrijd_id: int, bron: str | None = None,
                          importer: Importer | None = None) -> ImportVerslag:
    """Haal het tijdschema op en vervang daarmee het tijdschema van de wedstrijd.

    bron: link (atletiek.nu of Seltec), wedstrijd-id of opgeslagen HTML-bestand; zonder bron
    de link van de wedstrijd zelf. Fouten bij ophalen of lezen worden OpslagFout; dan blijft
    het oude tijdschema staan. `importer` is voor tests (anders gekozen bij de site).
    """
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    bron = bron or w.bron_url
    if not bron:
        raise OpslagFout("Deze wedstrijd heeft geen link naar atletiek.nu of Seltec; "
                         "geef de link van het tijdschema op.")
    bron_wedstrijd, regels = _ophalen(bron, w, importer)
    return _opslaan(db, w, bron_wedstrijd, regels)


MAX_BESTAND = 5 * 1024 * 1024          # een opgeslagen tijdschemapagina is een paar honderd kB
MAX_BESTANDEN = 10                     # Seltec: één pagina per wedstrijddag


def _decodeer(inhoud: bytes) -> str:
    for codering in ("utf-8-sig", "cp1252"):
        try:
            return inhoud.decode(codering)
        except UnicodeDecodeError:
            continue
    raise OpslagFout("Dit bestand is geen opgeslagen webpagina (HTML).")


def tijdschema_uit_bestanden(db: Opslag, wedstrijd_id: int,
                             bestanden: list[tuple[str, bytes]]) -> ImportVerslag:
    """Het tijdschema vervangen door één of meer opgeslagen pagina's (atletiek.nu of Seltec).

    Voor als de site een browsercontrole geeft: de trainer slaat de pagina in de browser op
    (Ctrl+S, 'Alleen HTML') en uploadt hem. Seltec heeft één pagina per dag: upload ze samen.
    `bestanden` = [(bestandsnaam, inhoud)]. De pagina's gaan alleen naar een tijdelijke map die
    meteen weer verdwijnt; er blijft niets van op schijf. Alles of niets, zoals een gewone import.
    """
    w = db.wedstrijd(wedstrijd_id)
    if w is None:
        raise OpslagFout(f"Wedstrijd {wedstrijd_id} bestaat niet.")
    bestanden = [(n, i) for n, i in bestanden if i]
    if not bestanden:
        raise OpslagFout("Kies eerst een opgeslagen tijdschemapagina (een .html-bestand).")
    if len(bestanden) > MAX_BESTANDEN:
        raise OpslagFout(f"Maximaal {MAX_BESTANDEN} bestanden tegelijk.")
    if any(len(i) > MAX_BESTAND for _, i in bestanden):
        raise OpslagFout("Een bestand is te groot voor een tijdschemapagina.")
    teksten = [_decodeer(i) for _, i in bestanden]
    with tempfile.TemporaryDirectory(prefix="avs-tijdschema-") as tmp:
        for nr, tekst in enumerate(teksten, 1):
            (Path(tmp) / f"pagina{nr:02d}.html").write_text(tekst, encoding="utf-8")
        bron_wedstrijd, regels = _ophalen(tmp, w)
    return _opslaan(db, w, bron_wedstrijd, regels)


# ============================================================
# Nieuwe wedstrijd vanaf een link
# ============================================================
@dataclass
class NieuweWedstrijd:
    wedstrijd: Wedstrijd
    verslag: ImportVerslag
    bestond: bool                      # de link was al bekend: alleen het tijdschema is bijgewerkt


def _link_van(bron: str, bron_wedstrijd) -> str | None:
    """De link om bij de wedstrijd te bewaren: de echte webpagina, ook als er een opgeslagen bestand is ingelezen."""
    for kandidaat in (bron, getattr(bron_wedstrijd, "url", "")):
        if str(kandidaat or "").lower().startswith(("http://", "https://")):
            return normaliseer_link(kandidaat)
    return None


def wedstrijd_uit_link(db: Opslag, bron: str, indoor: bool = False,
                       importer: Importer | None = None) -> NieuweWedstrijd:
    """Maak een wedstrijd van een link naar atletiek.nu of Seltec, met naam, datum, plaats en tijdschema.

    Is er al een wedstrijd met deze link, dan blijven naam, datum en plaats zoals ze
    zijn (misschien met de hand aangepast) en wordt alleen het tijdschema bijgewerkt.
    Alles of niets: lukt het ophalen niet, dan wordt er ook geen wedstrijd aangemaakt.
    """
    bron = (bron or "").strip()
    if not bron:
        raise OpslagFout("Plak de link van de wedstrijd op atletiek.nu of Seltec.")
    bron_wedstrijd, regels = _ophalen(bron, None, importer)
    link = _link_van(bron, bron_wedstrijd)

    bestaand = None
    if link:
        bestaand = next((w for w in db.wedstrijden() if w.bron_url == link), None)
    if bestaand is not None:
        return NieuweWedstrijd(bestaand, _opslaan(db, bestaand, bron_wedstrijd, regels), True)

    try:
        datum = date.fromisoformat(bron_wedstrijd.datum)
    except (TypeError, ValueError):
        datum = min(date.fromisoformat(r.datum) for r in regels)
    naam = (getattr(bron_wedstrijd, "naam", "") or "").strip() or "Wedstrijd"
    plaats = (getattr(bron_wedstrijd, "plaats", "") or "").strip() or None
    w = db.wedstrijd_opslaan(Wedstrijd(naam=naam, datum=datum, locatie=plaats, bron=bron_uit_link(link),
                                       bron_url=link, indoor=indoor))
    try:
        verslag = _opslaan(db, w, bron_wedstrijd, regels)
    except Exception:
        db.wedstrijd_verwijderen(w.id)          # geen halve wedstrijd achterlaten
        raise
    return NieuweWedstrijd(w, verslag, False)
