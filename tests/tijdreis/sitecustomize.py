"""Tijdreis: draai de tests alsof het een andere dag is, om tests te vinden die op een
bepaalde datum stukgaan (bijv. op 1 januari, als een atleet een leeftijdscategorie opschuift).

Gebruik, vanuit de map AVS:

    PowerShell:  $env:TIJDREIS_DATUM = "2027-09-01"; $env:PYTHONPATH = "tests\\tijdreis"; python -m pytest
    Bash:        TIJDREIS_DATUM=2027-09-01 PYTHONPATH=tests/tijdreis python -m pytest

Python laadt sitecustomize.py vanzelf bij het opstarten als deze map op PYTHONPATH staat. Dan
geeft date.today() overal de gekozen dag, al vanaf het begin: in de AVS-code, in de tests en
in waarden die een test bij het laden uitrekent. Een test met VASTE_VANDAAG (conftest.py) houdt
gewoon zijn eigen vaste dag. Zonder TIJDREIS_DATUM doet dit bestand niets.

Faalt een test hier wel en op de echte datum niet, dan is hij afhankelijk van de datum van
vandaag: geef de testmodule dan VASTE_VANDAAG = date(...). Draai dit vóór een release met een
datum een jaar verder. Dit bestand hoort alleen bij de tests en komt nooit in de .exe.
"""

import datetime as _dt
import os as _os

_doel = _os.environ.get("TIJDREIS_DATUM")
if _doel:
    _echt = _dt.date
    _dag = _echt.fromisoformat(_doel)

    class _IsEenDatum(type(_echt)):
        """isinstance(x, date) blijft werken: elke echte datum telt als date."""
        def __instancecheck__(cls, obj):
            return isinstance(obj, _echt)

        def __subclasscheck__(cls, sub):
            return issubclass(sub, _echt)

    class date(_echt, metaclass=_IsEenDatum):
        def __new__(cls, *args, **kwargs):
            return _echt(*args, **kwargs)          # een gemaakte datum is gewoon een echte date

        @classmethod
        def today(cls):
            return _dag

    date.__module__ = "datetime"
    _dt.date = date                                # vóór iets anders `from datetime import date` doet
    print(f"[tijdreis] date.today() = {_dag.isoformat()}")
