"""De opzet van de tests zelf: een testbestand importeert nooit uit een ander testbestand.

Gedeelde hulpjes staan in hulp.py en conftest.py, gedeelde nepgegevens in voorbeeld_*.py. Zo
breekt het aanpassen of verwijderen van de ene test geen andere, en draait elk bestand los.
"""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _geimporteerde_modules(pad: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(pad.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
    return modules


def test_geen_imports_uit_andere_testbestanden():
    fout = {pad.name: sorted(m for m in _geimporteerde_modules(pad) if m.startswith("test_"))
            for pad in TESTS.glob("*.py")}
    assert not {k: v for k, v in fout.items() if v}, "zet het gedeelde in hulp.py of voorbeeld_*.py"


def test_voorbeelden_bevatten_geen_tests():
    """pytest verzamelt voorbeeld_*.py niet; een test daarin zou dus stil nooit draaien."""
    for pad in TESTS.glob("voorbeeld_*.py"):
        namen = [n.name for n in ast.parse(pad.read_text(encoding="utf-8")).body
                 if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        assert not [n for n in namen if n.startswith(("test", "Test"))], pad.name
