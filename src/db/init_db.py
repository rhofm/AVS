"""Initialiseert de AVS-database.

De database staat NIET in git (privacy). Dit script:
  1. maakt de map data/ en een lege database aan als die nog niet bestaat,
  2. voert schema.sql uit op een lege database (versie 1),
  3. voert daarna alle migraties uit migrations/ uit die nog niet zijn toegepast.

Migraties heten NNN_beschrijving.sql (bijv. 002_add_blessures.sql) en worden
op nummer gesorteerd. Een bestaande database wordt nooit gewist.

Gebruik:
    python src/db/init_db.py            # maak/update data/avs.db
    python src/db/init_db.py pad/naar.db
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = DB_DIR / "schema.sql"
MIGRATIONS_DIR = DB_DIR / "migrations"
_MIGRATIE_NAAM = re.compile(r"^(\d+)_.*\.sql$")


def standaard_db_pad() -> Path:
    """data/avs.db naast de .exe (gebouwd) of in de root van de repo (ontwikkeling)."""
    if getattr(sys, "frozen", False):  # draait als PyInstaller-.exe
        basis = Path(sys.executable).resolve().parent
    else:
        basis = DB_DIR.parents[1]  # src/db -> repo-root
    return basis / "data" / "avs.db"


def verbind(pad: Path | None = None) -> sqlite3.Connection:
    """Open een verbinding met foreign keys aan en rijen als dict-achtige objecten."""
    pad = Path(pad) if pad else standaard_db_pad()
    pad.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(pad)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def huidige_versie(conn: sqlite3.Connection) -> int:
    """0 als de database nog leeg is."""
    bestaat = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not bestaat:
        return 0
    rij = conn.execute("SELECT MAX(versie) FROM schema_version").fetchone()
    return rij[0] or 0


def _migraties() -> list[tuple[int, Path]]:
    if not MIGRATIONS_DIR.is_dir():
        return []
    gevonden = []
    for f in MIGRATIONS_DIR.iterdir():
        m = _MIGRATIE_NAAM.match(f.name)
        if m:
            gevonden.append((int(m.group(1)), f))
    return sorted(gevonden)


def init_db(pad: Path | None = None) -> Path:
    """Maak de database aan en/of breng hem naar de nieuwste versie. Geeft het pad terug."""
    pad = Path(pad) if pad else standaard_db_pad()
    with verbind(pad) as conn:
        versie = huidige_versie(conn)

        if versie == 0:
            conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
            versie = huidige_versie(conn)
            print(f"Nieuwe database aangemaakt: {pad} (versie {versie})")

        for nummer, bestand in _migraties():
            if nummer <= versie:
                continue
            conn.executescript(bestand.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_version (versie) VALUES (?)", (nummer,))
            versie = nummer
            print(f"Migratie toegepast: {bestand.name}")

    print(f"Database up-to-date: versie {versie}")
    return pad


if __name__ == "__main__":
    init_db(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
