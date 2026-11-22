"""Nepgegevens rond één training met inhoud, voor meerdere testbestanden. Geen tests."""

from datetime import date

from models import Atleet, Groep, Training

__all__ = ["DINSDAG", "KERN_A", "basis_training"]

DINSDAG = date(2026, 10, 20)

KERN_A = """# Starts
- 6x **30 m** uit startblok
- *rustig* teruglopen
Herstel 2 min"""


def basis_training(db):
    """Sprintgroep (Anna, Bas, Cor) met een training op DINSDAG; Dirk zit niet in de groep.
    Geeft (anna, bas, cor, buiten, groep, training)."""
    anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
    bas = db.atleet_opslaan(Atleet("Bas", "Bakker"))
    cor = db.atleet_opslaan(Atleet("Cor", "Claassen"))
    buiten = db.atleet_opslaan(Atleet("Dirk", "Buiten"))
    g = db.groep_opslaan(Groep("Sprintgroep", leden=[anna.master_id, bas.master_id, cor.master_id]))
    t = db.training_opslaan(Training(g.id, DINSDAG, "Starts", "Veld 2 bezet, **binnenbaan**.",
                                     warming_up="10 min inlopen\nABC", kern_a=KERN_A, kern_b="3x 150 m",
                                     cooling_down="Uitlopen"))
    return anna, bas, cor, buiten, g, t
