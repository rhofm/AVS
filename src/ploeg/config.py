"""Waar de configuratiebestanden van de ploegen staan (config/ in de repo of naast de .exe).

- Vanuit de broncode: `config/` in de root van de repo.
- Gebouwd (PyInstaller): `config/` naast de .exe, zodat een ploegleider de
  YAML-bestanden kan aanpassen. Staat daar geen map, dan de kopie die in de
  .exe is meegebouwd (`sys._MEIPASS/config`).

Nooit uitgaan van de huidige werkmap.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]   # src/ploeg -> repo-root


def config_map() -> Path:
    """De map met `puntentelling/` en `ploeg_regels/`."""
    if getattr(sys, "frozen", False):
        naast_exe = Path(sys.executable).resolve().parent / "config"
        if naast_exe.is_dir():
            return naast_exe
        meegebouwd = getattr(sys, "_MEIPASS", None)
        if meegebouwd:
            return Path(meegebouwd) / "config"
        return naast_exe
    return _REPO_ROOT / "config"
