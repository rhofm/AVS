"""Waar de configuratiebestanden van de ploegen staan (puntentelling/ en ploeg_regels/).

Per bestand, in deze volgorde (de eerste die bestaat en niet leeg is wint):

- Vanuit de broncode: alleen `config/` in de root van de repo.
- Gebouwd (PyInstaller):
    1. `config/` naast de .exe: wat een ploegleider zelf heeft aangepast of toegevoegd;
    2. de kopie die in de .exe is meegebouwd (`sys._MEIPASS/config`).

Zo krijgt een gebruiker na een update de nieuwe bestanden uit de .exe, terwijl zijn
eigen aanpassingen blijven gelden. Een leeg bestand (alleen witruimte of #-commentaar,
zoals de voorbeeldbestanden) wint nooit van een gevuld bestand met dezelfde naam.

Nooit uitgaan van de huidige werkmap.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]   # src/ploeg -> repo-root


def _naast_exe() -> Path:
    return Path(sys.executable).resolve().parent / "config"


def config_mappen() -> list[Path]:
    """De mappen met `puntentelling/` en `ploeg_regels/`, hoogste voorrang eerst."""
    if getattr(sys, "frozen", False):
        mappen = [_naast_exe()]
        meegebouwd = getattr(sys, "_MEIPASS", None)
        if meegebouwd:
            mappen.append(Path(meegebouwd) / "config")
        return [m for m in mappen if m.is_dir()] or mappen[-1:]     # niets gevonden: de meegebouwde
    return [_REPO_ROOT / "config"]


def config_map() -> Path:
    """De map met de hoogste voorrang (voor meldingen). Zoek bestanden met config_bestand()."""
    return config_mappen()[0]


def _leeg(pad: Path) -> bool:
    """Alleen witruimte en #-commentaar (zoals '#This is an empty temporary file')."""
    try:
        tekst = pad.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False                 # onleesbaar: niet stil overslaan, laden legt uit wat er mis is
    return all(not r.strip() or r.lstrip().startswith("#") for r in tekst.splitlines())


def config_bestand(submap: str, naam: str) -> Path | None:
    """Het bestand dat geldt, bijv. config_bestand("ploeg_regels", "masters_2026-2027.yaml").

    De eerste map met een niet-leeg bestand wint. Bestaat het alleen leeg, dan dat lege
    bestand (laden legt uit dat het leeg is). Nergens: None.
    """
    gevonden = [m / submap / naam for m in config_mappen() if (m / submap / naam).is_file()]
    for pad in gevonden:
        if not _leeg(pad):
            return pad
    return gevonden[0] if gevonden else None


def config_bestanden(submap: str, patroon: str = "*.yaml") -> list[Path]:
    """Alle geldende bestanden uit alle mappen, één per naam (zie config_bestand), op naam gesorteerd."""
    namen = sorted({p.name for m in config_mappen() if (m / submap).is_dir() for p in (m / submap).glob(patroon)})
    return [pad for naam in namen if (pad := config_bestand(submap, naam)) is not None]


def gezocht_in(submap: str) -> str:
    """Voor foutmeldingen: de mappen waarin gezocht is."""
    return " en ".join(str(m / submap) for m in config_mappen())
