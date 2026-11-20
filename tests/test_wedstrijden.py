"""Tests voor src/wedstrijden/planning.py (komende wedstrijden plannen), met echte versleutelde databases.

Alleen nepgegevens en een vaste testsleutel.
"""

from datetime import date

from db.queries import OpslagFout
from models import Atleet, Onderdeel, Prestatie
from wedstrijden import planning
from hulp import opslag, verwacht as _verwacht

LINK = "https://www.atletiek.nu/wedstrijd/main/45678/"


def _basis(db):
    anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
    bas = db.atleet_opslaan(Atleet("Bas", "Bakker"))
    db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
    db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
    db.onderdeel_opslaan(Onderdeel("Kogelstoten", "afstand", False, "werpen"))
    w = planning.plan_wedstrijd(db, "Clubkampioenschappen", date(2027, 5, 15), "Nijmegen", LINK)
    return anna, bas, w


def test_links():
    n = planning.normaliseer_link
    verwacht = "https://www.atletiek.nu/wedstrijd/uitslagen/45678/"
    for link in (LINK, " https://atletiek.nu/wedstrijd/inschrijvingen/45678/#top",
                 "https://www.atletiek.nu/wedstrijd/uitslagen/45678/492691/"):
        assert n(link) == verwacht, link
    assert n("https://seltec.nl/uitslagen/abc ") == "https://seltec.nl/uitslagen/abc"
    assert n("") is None and n(None) is None
    assert planning.bron_uit_link(LINK) == "atletieknu"
    assert planning.bron_uit_link("https://seltec.nl/x") == "seltec"
    assert planning.bron_uit_link(None) == "handmatig"


def test_plannen_en_bijwerken():
    with opslag() as db:
        _, _, w = _basis(db)
        assert (w.naam, w.datum, w.locatie, w.bron) == ("Clubkampioenschappen", date(2027, 5, 15), "Nijmegen", "atletieknu")
        assert w.bron_url == "https://www.atletiek.nu/wedstrijd/uitslagen/45678/"
        # Dezelfde wedstrijd via een andere atletiek.nu-pagina: bijwerken, geen tweede rij.
        w2 = planning.plan_wedstrijd(db, "CK 2027", date(2027, 5, 16), "Nijmegen",
                                     "https://www.atletiek.nu/wedstrijd/inschrijvingen/45678/")
        assert w2.id == w.id and len(db.wedstrijden()) == 1 and db.wedstrijd(w.id).naam == "CK 2027"
        # Zonder link mag ook (handmatig).
        h = planning.plan_wedstrijd(db, "Trainingswedstrijd", date(2027, 4, 1))
        assert h.bron == "handmatig" and h.bron_url is None
        _verwacht(OpslagFout, lambda: planning.plan_wedstrijd(db, "  ", date(2027, 4, 1)))


def test_inschrijven_en_afmelden():
    with opslag() as db:
        anna, bas, w = _basis(db)
        planning.inschrijven(db, w.id, anna.master_id, ["100m", "Verspringen"])
        planning.inschrijven(db, w.id, anna.master_id, ["100m"])               # dubbel: geen extra regel
        planning.inschrijven(db, w.id, bas.master_id)                          # onderdelen nog onbekend
        o = planning.overzicht(db, w.id)
        assert o.deelnemers == {anna.master_id: ["100m", "Verspringen"], bas.master_id: []}
        assert o.aantal_deelnemers == 2 and o.link == w.bron_url

        planning.inschrijven(db, w.id, bas.master_id, ["Kogelstoten"])         # 'onbekend' vervalt
        assert planning.overzicht(db, w.id).deelnemers[bas.master_id] == ["Kogelstoten"]
        assert planning.overzicht(db, w.id).per_onderdeel() == {
            "100m": [anna.master_id], "Kogelstoten": [bas.master_id], "Verspringen": [anna.master_id]}

        # Fouten: niets wordt half opgeslagen.
        _verwacht(OpslagFout, lambda: planning.inschrijven(db, w.id, anna.master_id, ["Kogelstoten", "Polsstok"]))
        assert planning.overzicht(db, w.id).deelnemers[anna.master_id] == ["100m", "Verspringen"]
        _verwacht(OpslagFout, lambda: planning.inschrijven(db, 999, anna.master_id, ["100m"]))
        _verwacht(OpslagFout, lambda: planning.inschrijven(db, w.id, "0" * 32, ["100m"]))

        planning.afmelden(db, w.id, anna.master_id, "Verspringen")
        assert planning.overzicht(db, w.id).deelnemers[anna.master_id] == ["100m"]
        planning.afmelden(db, w.id, anna.master_id)                            # hele wedstrijd
        assert anna.master_id not in planning.overzicht(db, w.id).deelnemers
        # Staat bij de atleet zelf ook goed (profiel gebruikt inschrijvingen()).
        assert [i.onderdeel_id for i in db.inschrijvingen(bas.master_id)] == [db.onderdeel("Kogelstoten").id]


def test_komende_wedstrijden_en_afgelast():
    with opslag() as db:
        anna, _, w = _basis(db)
        oud = planning.plan_wedstrijd(db, "Oud", date(2026, 1, 10))
        later = planning.plan_wedstrijd(db, "Later", date(2027, 9, 1))
        komend = planning.komende_wedstrijden(db, vanaf=date(2026, 10, 16))
        assert [o.wedstrijd.naam for o in komend] == ["Clubkampioenschappen", "Later"]

        planning.inschrijven(db, later.id, anna.master_id, ["100m"])
        planning.wedstrijd_afgelast(db, later.id)
        assert db.wedstrijd(later.id) is None and db.inschrijvingen(anna.master_id) == []

        # Een wedstrijd met uitslagen wordt nooit verwijderd.
        db.prestatie_opslaan(Prestatie("100m", date(2026, 1, 10), 13.1, wind=0.0, wedstrijd_id=oud.id)
                             .gekoppeld(anna.master_id))
        _verwacht(OpslagFout, lambda: planning.wedstrijd_afgelast(db, oud.id))


def test_verwijderde_atleet_verdwijnt_van_deelnemerslijst():
    with opslag() as db:
        anna, bas, w = _basis(db)
        planning.inschrijven(db, w.id, anna.master_id, ["100m"])
        planning.inschrijven(db, w.id, bas.master_id, ["100m"])
        db.atleet_verwijderen(anna.master_id)
        assert list(planning.overzicht(db, w.id).deelnemers) == [bas.master_id]
