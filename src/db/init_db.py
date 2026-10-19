"""Initialiseert de versleutelde AVS-databases.

De databases staan NIET in git (privacy). De gegevens zijn verdeeld over acht
bestanden, elk met SQLCipher versleuteld met een eigen sleutel:

    data/personen.db         persoonsgegevens, groepen, trainingen, leerlijnen, ploegen
    data/prestaties.db       onderdelen, wedstrijden, prestaties, PR's
    data/testen.db           testen en testresultaten
    data/trainingsschema.db  op welke dagen van de week een atleet traint
    data/absentie.db         aanwezigheid per training (aanwezig/afgemeld/afwezig/blessure)
    data/leerlijnen.db       leerlijnen en leerdoelen per leeftijdscategorie (geen persoonsgegevens)
    data/leerdoelscores.db   score 1-5 per atleet per leerdoel per datum
    data/notities.db         vrije notities per atleet per datum (training/wedstrijd)

Sleutels
--------
Alles hangt aan één willekeurige hoofdsleutel (32 bytes) in de sleutelkluis
van het besturingssysteem (op Windows: Referentiebeheer, via `keyring`).
Daaruit worden met HMAC-SHA256 afgeleid:

  * per database een eigen versleutelingssleutel;
  * per database een eigen pseudoniem voor elke atleet.

Een atleet krijgt in personen.db een willekeurige master_id (nieuw_master_id()).
Alleen daar staat die id naast naam en geboortedatum. In de andere
databases staat in plaats daarvan pseudoniem(master_id, '<database>'). Die
pseudoniemen verschillen per database. Zonder de hoofdsleutel zijn de bestanden
onleesbaar, en ook met één gelekte database-sleutel is een bestand niet aan een
ander bestand of aan een persoon te koppelen.

LET OP: zonder hoofdsleutel is de data voor altijd weg. Schrijf de
herstelsleutel op (--herstelsleutel) en bewaar die buiten deze computer.

Dit script:
  1. maakt de map data/ aan als die nog niet bestaat,
  2. maakt zo nodig de hoofdsleutel aan in de sleutelkluis,
  3. voert per database het basisschema uit op een lege database (versie 1),
  4. voert daarna per database de migraties uit die nog niet zijn toegepast,
  5. verplaatst zo nodig de oude absentie uit personen.db naar absentie.db
     (eenmalig, zie migrations/personen/002_absentie_naar_eigen_database.sql).

Migraties staan in migrations/<database>/NNN_beschrijving.sql (bijv.
migrations/testen/002_add_testlocatie.sql) en worden op nummer gesorteerd.
Een bestaande database wordt nooit gewist. Komt er een nieuwe database bij
(zoals trainingsschema.db), dan maakt dit script hem bij de volgende start aan
met de bestaande hoofdsleutel.

Vereist: pip install sqlcipher3-wheels keyring

Gebruik:
    python src/db/init_db.py                      # maak/update data/*.db
    python src/db/init_db.py pad/naar/map         # andere map (bijv. voor tests)
    python src/db/init_db.py --herstelsleutel     # toon de herstelsleutel
    python src/db/init_db.py --herstel <sleutel>  # zet een herstelsleutel terug
                                                  # (bijv. op een nieuwe computer)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import re
import secrets
import sys
from contextlib import closing
from pathlib import Path

import sqlcipher3

DB_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = DB_DIR / "migrations"
_MIGRATIE_NAAM = re.compile(r"^(\d+)_.*\.sql$")

DATABASES = ("personen", "prestaties", "testen", "trainingsschema", "absentie", "leerlijnen", "leerdoelscores",
             "notities")
# Databases waarin een atleet als pseudoniem staat (personen.db gebruikt master_id).
GEPSEUDONIMISEERD = ("prestaties", "testen", "trainingsschema", "absentie", "leerdoelscores", "notities")

KEYRING_DIENST = "AVS"
KEYRING_NAAM = "hoofdsleutel"
_SLEUTEL_LENGTE = 32  # bytes


# ============================================================
# Sleutels
# ============================================================
class SleutelFout(RuntimeError):
    """De hoofdsleutel ontbreekt, is ongeldig of past niet bij de databases."""


def _naar_bytes(sleutel: str | bytes) -> bytes:
    if isinstance(sleutel, bytes):
        ruw = sleutel
    else:
        try:
            ruw = bytes.fromhex(sleutel.strip())
        except ValueError:
            raise SleutelFout("De sleutel moet uit hexadecimale tekens bestaan.") from None
    if len(ruw) != _SLEUTEL_LENGTE:
        raise SleutelFout(f"De sleutel moet {_SLEUTEL_LENGTE} bytes ({_SLEUTEL_LENGTE * 2} hex-tekens) zijn.")
    return ruw


def _keyring():
    try:
        import keyring
    except ImportError:
        raise SleutelFout("Het pakket 'keyring' ontbreekt: pip install keyring") from None
    return keyring


def _lees_hoofdsleutel() -> bytes | None:
    opgeslagen = _keyring().get_password(KEYRING_DIENST, KEYRING_NAAM)
    return _naar_bytes(opgeslagen) if opgeslagen else None


def _bewaar_hoofdsleutel(sleutel: bytes) -> None:
    _keyring().set_password(KEYRING_DIENST, KEYRING_NAAM, sleutel.hex())


def hoofdsleutel(aanmaken: bool = False) -> bytes:
    """De hoofdsleutel uit de sleutelkluis. Met aanmaken=True wordt er een gemaakt als die er nog niet is."""
    sleutel = _lees_hoofdsleutel()
    if sleutel is None:
        if not aanmaken:
            raise SleutelFout(
                "Geen hoofdsleutel gevonden op deze computer. "
                "Zet de herstelsleutel terug met: python src/db/init_db.py --herstel <sleutel>"
            )
        sleutel = secrets.token_bytes(_SLEUTEL_LENGTE)
        _bewaar_hoofdsleutel(sleutel)
    return sleutel


def _afgeleid(hoofd: bytes, doel: str) -> bytes:
    """Een aparte sleutel voor één doel, zodat geen twee doelen dezelfde sleutel delen."""
    return hmac.new(hoofd, f"AVS:{doel}".encode(), hashlib.sha256).digest()


def nieuw_master_id() -> str:
    """Willekeurige master_id voor een nieuwe atleet (32 hex-tekens).

    Nooit afleiden van naam, geboortedatum of bondsnummer: zulke id's zijn met
    proberen terug te rekenen.
    """
    return secrets.token_hex(16)


def pseudoniem(master_id: str, database: str, hoofd: str | bytes | None = None) -> str:
    """Het pseudoniem (atleet_ref) van een atleet in een van de databases uit GEPSEUDONIMISEERD."""
    if database not in GEPSEUDONIMISEERD:
        raise ValueError(f"Geen pseudoniemen in {database!r}; kies uit {GEPSEUDONIMISEERD}.")
    hoofd = _naar_bytes(hoofd) if hoofd is not None else hoofdsleutel()
    geheim = _afgeleid(hoofd, f"pseudoniem:{database}")
    return hmac.new(geheim, master_id.encode(), hashlib.sha256).hexdigest()[:32]


# ============================================================
# Verbinden
# ============================================================
def standaard_map() -> Path:
    """data/ naast de .exe (gebouwd) of in de root van de repo (ontwikkeling)."""
    if getattr(sys, "frozen", False):  # draait als PyInstaller-.exe
        basis = Path(sys.executable).resolve().parent
    else:
        basis = DB_DIR.parents[1]  # src/db -> repo-root
    return basis / "data"


def db_pad(database: str, map: Path | None = None) -> Path:
    if database not in DATABASES:
        raise ValueError(f"Onbekende database {database!r}; kies uit {DATABASES}.")
    return (Path(map) if map else standaard_map()) / f"{database}.db"


def verbind(database: str, map: Path | None = None, hoofd: str | bytes | None = None) -> sqlcipher3.Connection:
    """Open een versleutelde database met foreign keys aan en rijen als dict-achtige objecten.

    database: een naam uit DATABASES, bijv. 'personen' of 'absentie'.
    hoofd:    alleen voor tests; normaal komt de sleutel uit de sleutelkluis.
    """
    pad = db_pad(database, map)
    pad.parent.mkdir(parents=True, exist_ok=True)
    hoofd = _naar_bytes(hoofd) if hoofd is not None else hoofdsleutel()
    db_sleutel = _afgeleid(hoofd, f"versleuteling:{database}").hex()

    conn = sqlcipher3.connect(pad)
    conn.execute("PRAGMA cipher_log_level = NONE")  # geen ruwe SQLCipher-fouten in de console
    # PRAGMA key moet de eerste opdracht zijn. Een ruwe sleutel (x'..') slaat de
    # trage wachtwoord-afleiding over; dat mag omdat de sleutel al willekeurig is.
    # db_sleutel is zelf gemaakte hex, dus veilig om in de opdracht te zetten.
    conn.execute(f"PRAGMA key = \"x'{db_sleutel}'\"")
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher3.DatabaseError:
        conn.close()
        raise SleutelFout(
            f"{pad.name} kan niet worden geopend: de sleutel past niet, of het bestand "
            "is geen (versleutelde) AVS-database."
        ) from None
    conn.row_factory = sqlcipher3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA temp_store = MEMORY")  # geen tijdelijke bestanden op schijf
    return conn


# ============================================================
# Schema en migraties
# ============================================================
def huidige_versie(conn: sqlcipher3.Connection) -> int:
    """0 als de database nog leeg is."""
    bestaat = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not bestaat:
        return 0
    rij = conn.execute("SELECT MAX(versie) FROM schema_version").fetchone()
    return rij[0] or 0


def _migraties(database: str) -> list[tuple[int, Path]]:
    map_ = MIGRATIONS_DIR / database
    if not map_.is_dir():
        return []
    gevonden = []
    for f in map_.iterdir():
        m = _MIGRATIE_NAAM.match(f.name)
        if m:
            gevonden.append((int(m.group(1)), f))
    gevonden.sort()
    # Twee migraties met hetzelfde nummer (bijv. na het samenvoegen van twee
    # branches) zou er stil één overslaan. Dan liever niet starten.
    nummers = [n for n, _ in gevonden]
    dubbel = sorted({n for n in nummers if nummers.count(n) > 1})
    if dubbel:
        namen = ", ".join(f.name for n, f in gevonden if n in dubbel)
        raise RuntimeError(f"Migraties in migrations/{database}/ met hetzelfde nummer: {namen}. "
                           "Geef elke migratie een eigen nummer.")
    return gevonden


def _init_een(database: str, map: Path | None, hoofd: bytes) -> int:
    # closing(): `with conn` alleen commit, maar sluit de verbinding niet. Op Windows
    # blijft het bestand dan open (en vergrendeld) tot de garbage collector langskomt.
    with closing(verbind(database, map, hoofd)) as conn, conn:
        versie = huidige_versie(conn)

        if versie == 0:
            schema = DB_DIR / f"schema_{database}.sql"
            conn.executescript(schema.read_text(encoding="utf-8"))
            versie = huidige_versie(conn)
            print(f"Nieuwe database aangemaakt: {database}.db (versie {versie})")

        for nummer, bestand in _migraties(database):
            if nummer <= versie:
                continue
            conn.executescript(bestand.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_version (versie) VALUES (?)", (nummer,))
            versie = nummer
            print(f"Migratie toegepast op {database}.db: {bestand.name}")
    return versie


def _verplaats_absentie(map: Path | None, hoofd: bytes) -> int:
    """Eenmalig: oude absentie uit personen.db naar absentie.db. Geeft het aantal rijen.

    Eerst alles in absentie.db zetten, pas daarna de oude tabel weggooien. Gaat
    het tussendoor mis, dan staat alles nog in personen.db en gaat het de
    volgende keer verder; rijen die al verplaatst waren worden overgeslagen.
    """
    with closing(verbind("personen", map, hoofd)) as personen, personen:
        bestaat = personen.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='absentie_te_verplaatsen'"
        ).fetchone()
        if not bestaat:
            return 0
        rijen = personen.execute(
            "SELECT training_id, atleet_id, status, reden FROM absentie_te_verplaatsen"
        ).fetchall()
        with closing(verbind("absentie", map, hoofd)) as absentie:
            with absentie:
                absentie.executemany(
                    """INSERT OR IGNORE INTO absentie (training_id, atleet_ref, status, reden)
                       VALUES (?, ?, ?, ?)""",
                    [(r["training_id"], pseudoniem(r["atleet_id"], "absentie", hoofd), r["status"], r["reden"])
                     for r in rijen],
                )
        with personen:
            personen.execute("DROP TABLE absentie_te_verplaatsen")
    print(f"Absentie verplaatst naar absentie.db: {len(rijen)} rij(en)")
    return len(rijen)


_DAGEN = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


def _groep_trainingstijden_samenvoegen(map: Path | None, hoofd: bytes) -> int:
    """Eenmalig: tijden uit de twee oude varianten naar groep_trainingstijden. Geeft het aantal groepen.

    Oude varianten (allebei ooit migratie 003): kolommen maandag..zondag op
    `groep`, of de tabel `groep_trainingsdag` (één rij per groep per dag, tijd
    mocht leeg zijn). Een dag zonder begintijd kan niet mee: in de nieuwe tabel
    betekent leeg 'geen training'. Dat wordt gemeld.
    """
    with verbind("personen", map, hoofd) as c:
        tabellen = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "groep_trainingstijden" not in tabellen:
            return 0
        kolommen = {r[1] for r in c.execute("PRAGMA table_info(groep)")}
        tijden: dict[int, dict[str, str]] = {}
        zonder_tijd = 0
        if "groep_trainingsdag" in tabellen:
            for gid, dag, tijd in c.execute("SELECT groep_id, dag, starttijd FROM groep_trainingsdag"):
                if tijd:
                    tijden.setdefault(gid, {})[dag] = tijd
                else:
                    zonder_tijd += 1
        oude_kolommen = [d for d in _DAGEN if d in kolommen]
        if oude_kolommen:
            for r in c.execute(f"SELECT id, {', '.join(oude_kolommen)} FROM groep"):
                for i, d in enumerate(oude_kolommen, start=1):
                    if r[i]:
                        tijden.setdefault(r[0], {}).setdefault(d, r[i])
        if "groep_trainingsdag" not in tabellen and not oude_kolommen:
            return 0
        with c:
            for gid, per_dag in tijden.items():
                bestaat = c.execute("SELECT 1 FROM groep_trainingstijden WHERE groep_id = ?", (gid,)).fetchone()
                if bestaat:
                    continue   # al overgezet (bijv. bij een eerdere, onderbroken poging)
                c.execute(f"INSERT INTO groep_trainingstijden (groep_id, {', '.join(_DAGEN)}) "
                          f"VALUES (?, {', '.join('?' * len(_DAGEN))})",
                          (gid, *[per_dag.get(d) for d in _DAGEN]))
            if "groep_trainingsdag" in tabellen:
                c.execute("DROP TABLE groep_trainingsdag")
            for d in oude_kolommen:
                c.execute(f"ALTER TABLE groep DROP COLUMN {d}")   # d komt uit _DAGEN, vaste namen
    print(f"Trainingstijden van {len(tijden)} groep(en) overgezet naar groep_trainingstijden.")
    if zonder_tijd:
        print(f"Let op: {zonder_tijd} trainingsdag(en) zonder begintijd konden niet mee; "
              "vul die tijden opnieuw in bij de groep.")
    return len(tijden)


def _verplaats_periodeplannen(map: Path | None, hoofd: bytes) -> int:
    """Eenmalig: oude periodeplannen uit personen.db als doel naar prestaties.db. Geeft het aantal.

    Een periodeplan wordt een doel zonder regels: titel = naam, beschrijving =
    doel, startdatum, datum = einddatum, zelfde groep. Eerst alles in
    prestaties.db zetten, pas daarna de oude tabel leegmaken (de tabel zelf
    blijft: training.periodeplan_id verwijst ernaar, zie migratie personen/007).
    Gaat het tussendoor mis, dan gaat het de volgende keer verder; een doel dat
    al is overgezet (zelfde groep, titel, startdatum en datum) komt er niet nog eens bij.
    """
    with closing(verbind("personen", map, hoofd)) as personen, personen:
        if huidige_versie(personen) < 7:
            return 0
        rijen = personen.execute(
            "SELECT groep_id, naam, startdatum, einddatum, doel FROM periodeplan ORDER BY id").fetchall()
        if not rijen:
            return 0
        with closing(verbind("prestaties", map, hoofd)) as prestaties:
            with prestaties:
                for r in rijen:
                    al = prestaties.execute(
                        """SELECT 1 FROM doel WHERE groep_id IS ? AND titel = ? AND startdatum = ? AND datum IS ?""",
                        (r["groep_id"], r["naam"], r["startdatum"], r["einddatum"])).fetchone()
                    if not al:
                        prestaties.execute(
                            """INSERT INTO doel (groep_id, titel, startdatum, datum, beschrijving)
                               VALUES (?, ?, ?, ?, ?)""",
                            (r["groep_id"], r["naam"], r["startdatum"], r["einddatum"], r["doel"]))
        with personen:
            personen.execute("DELETE FROM periodeplan")    # zet training.periodeplan_id op NULL
    print(f"Periodeplannen overgezet naar doelen (prestaties.db): {len(rijen)}")
    return len(rijen)


def init_db(map: Path | None = None, hoofd: str | bytes | None = None) -> Path:
    """Maak de databases aan en/of breng ze naar de nieuwste versie. Geeft de map terug.

    hoofd: alleen voor tests; normaal komt de sleutel uit de sleutelkluis en
    wordt hij bij de allereerste start aangemaakt.
    """
    map = Path(map) if map else standaard_map()

    if hoofd is not None:
        hoofd = _naar_bytes(hoofd)
    else:
        bestaande = [db for db in DATABASES if db_pad(db, map).exists()]
        if bestaande and _lees_hoofdsleutel() is None:
            # Nooit een nieuwe sleutel maken naast bestaande databases: die zouden
            # dan onbereikbaar worden.
            raise SleutelFout(
                f"Er staan al databases in {map} ({', '.join(bestaande)}), maar er is geen "
                "hoofdsleutel op deze computer. Zet de herstelsleutel terug met --herstel."
            )
        hoofd = hoofdsleutel(aanmaken=True)

    for database in DATABASES:
        versie = _init_een(database, map, hoofd)
        print(f"{database}.db up-to-date: versie {versie}")
    _verplaats_absentie(map, hoofd)
    _groep_trainingstijden_samenvoegen(map, hoofd)
    _verplaats_periodeplannen(map, hoofd)
    return map


# ============================================================
# Herstelsleutel
# ============================================================
def herstelsleutel() -> str:
    """De hoofdsleutel als tekst, om op te schrijven en veilig te bewaren."""
    return hoofdsleutel().hex()


def herstel(sleutel: str) -> None:
    """Zet een opgeschreven herstelsleutel terug in de sleutelkluis van deze computer."""
    nieuw = _naar_bytes(sleutel)
    huidig = _lees_hoofdsleutel()
    if huidig is not None and not hmac.compare_digest(huidig, nieuw):
        raise SleutelFout(
            "Er staat al een andere hoofdsleutel op deze computer. Die wordt niet "
            "overschreven, anders zijn de huidige databases niet meer te openen."
        )
    _bewaar_hoofdsleutel(nieuw)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maak of update de AVS-databases.")
    parser.add_argument("map", nargs="?", type=Path, help="map voor de databases (standaard: data/)")
    groep = parser.add_mutually_exclusive_group()
    groep.add_argument("--herstelsleutel", action="store_true", help="toon de herstelsleutel")
    groep.add_argument("--herstel", metavar="SLEUTEL", help="zet een herstelsleutel terug")
    args = parser.parse_args(argv)

    try:
        if args.herstelsleutel:
            print("Herstelsleutel (bewaar deze buiten deze computer, deel hem met niemand):")
            print(herstelsleutel())
            return 0
        if args.herstel:
            herstel(args.herstel)
            print("Herstelsleutel teruggezet.")
        init_db(args.map)
    except (SleutelFout, RuntimeError) as fout:
        print(f"Fout: {fout}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
