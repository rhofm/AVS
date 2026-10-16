"""Gedeelde dataclasses voor de hele app.

Modellen bevatten alleen gegevens en kleine hulpfuncties: geen SQL en geen
bedrijfslogica. db/queries.py zet databaserijen om naar modellen en terug;
de feature-modules (atleten/, ploeg/, groepen/, ...) werken alleen met modellen.

Een atleet heet overal `master_id` / `atleet_id`. Pseudoniemen (atleet_ref)
blijven binnen db/.
"""

from .atleet import GESLACHTEN, Atleet, Geslacht
from .groep import ABSENTIE_STATUSSEN, Absentie, AbsentieStatus, Groep, Periodeplan, Training
from .leerdoel import CATEGORIEEN, LEERDOEL_BRONNEN, Categorie, Leerdoel, LeerdoelScore
from .leerlijn import Leerlijn, LeerlijnStap, LeerlijnVoortgang
from .prestatie import (
    BRONNEN,
    EENHEDEN,
    MAX_WIND,
    PR,
    Bron,
    Eenheid,
    Inschrijving,
    Onderdeel,
    Prestatie,
    Test,
    Testresultaat,
    Wedstrijd,
    heeft_windmeting,
)
from .trainingsschema import DAGEN, Trainingsschema

__all__ = [
    "Atleet", "Geslacht", "GESLACHTEN",
    "Onderdeel", "Wedstrijd", "Prestatie", "Inschrijving", "PR", "Test", "Testresultaat",
    "Bron", "BRONNEN", "Eenheid", "EENHEDEN", "MAX_WIND", "heeft_windmeting",
    "Groep", "Training", "Absentie", "AbsentieStatus", "ABSENTIE_STATUSSEN", "Periodeplan",
    "Leerlijn", "LeerlijnStap", "LeerlijnVoortgang",
    "Leerdoel", "LeerdoelScore", "Categorie", "CATEGORIEEN", "LEERDOEL_BRONNEN",
    "Trainingsschema", "DAGEN",
]
