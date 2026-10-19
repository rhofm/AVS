"""Gedeelde dataclasses voor de hele app.

Modellen bevatten alleen gegevens en kleine hulpfuncties: geen SQL en geen
bedrijfslogica. db/queries.py zet databaserijen om naar modellen en terug;
de feature-modules (atleten/, ploeg/, groepen/, ...) werken alleen met modellen.

Een atleet heet overal `master_id` / `atleet_id`. Pseudoniemen (atleet_ref)
blijven binnen db/.
"""

from .atleet import GESLACHTEN, Atleet, Geslacht
from .doel import BEOORDELINGEN, DOELSOORTEN, STATUSSEN, Doel, DoelRegel
from .groep import ABSENTIE_STATUSSEN, Absentie, AbsentieStatus, Groep, TRAININGSONDERDELEN, Training, normaliseer_tijd
from .leerdoel import CATEGORIEEN, LEERDOEL_BRONNEN, Categorie, Leerdoel, LeerdoelScore
from .leerlijn import Leerlijn, LeerlijnStap, LeerlijnVoortgang
from .notitie import Notitie
from .periodisering import FASE_CODES, FASEN, Fase, Mesocyclus, MesoWeek, Periode, Periodisering
from .ploeg import BESCHIKBAAR, PRESTATIEBASIS, ROLLEN, Beschikbaar, Inzet, Ploeg, PloegLid, Prestatiebasis, Rol
from .programma import ProgrammaOnderdeel, lees_categorie
from .rooster import INHOUD, INHOUD_VELDEN, GroepRooster, Rooster, RoosterRegel
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
    "Doel", "DoelRegel", "DOELSOORTEN", "BEOORDELINGEN", "STATUSSEN",
    "Onderdeel", "Wedstrijd", "Prestatie", "Inschrijving", "PR", "Test", "Testresultaat",
    "Bron", "BRONNEN", "Eenheid", "EENHEDEN", "MAX_WIND", "heeft_windmeting",
    "Groep", "normaliseer_tijd", "Training", "TRAININGSONDERDELEN", "Absentie", "AbsentieStatus", "ABSENTIE_STATUSSEN",
    "Fase", "FASEN", "FASE_CODES", "Mesocyclus", "MesoWeek", "Periode", "Periodisering",
    "Rooster", "RoosterRegel", "GroepRooster", "INHOUD", "INHOUD_VELDEN",
    "Leerlijn", "LeerlijnStap", "LeerlijnVoortgang",
    "Leerdoel", "LeerdoelScore", "Categorie", "CATEGORIEEN", "LEERDOEL_BRONNEN",
    "Trainingsschema", "DAGEN",
    "Notitie",
    "ProgrammaOnderdeel", "lees_categorie",
    "Ploeg", "PloegLid", "Inzet", "Rol", "ROLLEN", "Beschikbaar", "BESCHIKBAAR", "Prestatiebasis", "PRESTATIEBASIS",
]
