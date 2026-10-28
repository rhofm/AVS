"""Tests voor src/groepen/absentie.py (de absentie-tool), met echte versleutelde databases.

Alleen nepgegevens en een vaste testsleutel.
"""

from datetime import date, timedelta

from groepen import absentie
from models import Atleet, Groep, Training, Trainingsschema
from hulp import opslag


def _groep(db):
    anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
    bas = db.atleet_opslaan(Atleet("Bas", "Bakker"))
    cor = db.atleet_opslaan(Atleet("Cor", "Claassen"))
    g = db.groep_opslaan(Groep("Junioren C", leden=[anna.master_id, bas.master_id, cor.master_id]))
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["dinsdag", "donderdag"]))
    db.trainingsschema_opslaan(Trainingsschema.met_dagen(bas.master_id, ["dinsdag"]))
    # Cor heeft (nog) geen trainingsschema.
    dinsdag = db.training_opslaan(Training(g.id, date(2026, 10, 20)))
    return anna, bas, cor, g, dinsdag


def test_lijst_vooraf_ingevuld_uit_trainingsschema():
    with opslag() as db:
        anna, bas, cor, g, dinsdag = _groep(db)
        lijst = absentie.absentielijst(db, dinsdag.id)
        assert [(a.atleet_id, a.status) for a in lijst] == [
            (anna.master_id, "aanwezig"), (bas.master_id, "aanwezig")]          # Cor niet ingeroosterd
        assert len(absentie.absentielijst(db, dinsdag.id, alle_leden=True)) == 3
        assert db.absenties(dinsdag.id) == []                                     # nog niets opgeslagen

        donderdag = db.training_opslaan(Training(g.id, date(2026, 10, 22)))
        assert [a.atleet_id for a in absentie.absentielijst(db, donderdag.id)] == [anna.master_id]


def test_uitzonderingen_aanpassen_en_opslaan():
    with opslag() as db:
        anna, bas, cor, g, dinsdag = _groep(db)
        lijst = absentie.absentielijst(db, dinsdag.id)
        absentie.zet_status(lijst, bas.master_id, "blessure", "enkel")
        absentie.zet_status(lijst, cor.master_id, "aanwezig")                    # extra gekomen
        absentie.opslaan(db, lijst)

        opgeslagen = {a.atleet_id: (a.status, a.reden) for a in db.absenties(dinsdag.id)}
        assert opgeslagen == {anna.master_id: ("aanwezig", None), bas.master_id: ("blessure", "enkel"),
                              cor.master_id: ("aanwezig", None)}
        # Opnieuw openen: opgeslagen statuses gaan voor het schema.
        assert {a.atleet_id: a.status for a in absentie.absentielijst(db, dinsdag.id)}[bas.master_id] == "blessure"


def test_overzicht():
    with opslag() as db:
        anna, _, _, g, dinsdag = _groep(db)
        statussen = ["aanwezig", "aanwezig", "afgemeld", "aanwezig"]
        for i, s in enumerate(statussen):
            tr = dinsdag if i == 0 else db.training_opslaan(Training(g.id, date(2026, 10, 20) + timedelta(weeks=i)))
            db.absentie_opslaan(absentie.Absentie(tr.id, anna.master_id, s))
        o = absentie.overzicht(db, anna.master_id)
        assert o["aanwezig"] == 3 and o["afgemeld"] == 1 and o["blessure"] == 0
        assert o["totaal"] == 4 and o["percentage_aanwezig"] == 75.0
        assert absentie.overzicht(db, "0" * 32)["percentage_aanwezig"] == 0.0
