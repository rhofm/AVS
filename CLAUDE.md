# CLAUDE.md — Atleet Volg Systeem (AVS)

Guidance for Claude when working in this repository.

## What this project is

AVS is an athlete tracking system for an athletics club, used by trainers.
It tracks athletes' PRs, performances, planned competitions and test results,
and where each athlete is in the learning pathways (leerlijnen). It also helps
with assembling competition teams (ploegen), group attendance (absentie), and
planning training periods and trainings.

Users are trainers and team leaders, not programmers. The app must be usable
**without a terminal**: one build command produces a `.exe` that runs on a local
machine and opens an easy, click-through UI.

Feature overview and open ideas: `README.md` and `docs/Structuur.md`.

## Language conventions

- The domain language is **Dutch**: module names, table and column names,
  functions, variables, docstrings, comments, UI text and commit messages
  (e.g. `atleet`, `prestatie`, `onderdeel`, `ploeg`, `verbind()`, `init_db()`).
  Keep new code in Dutch to match.
- Athletics terms follow Dutch usage: onderdeel (event), wedstrijd (competition),
  PR, ploeg (team), leerlijn (learning pathway), periodeplan, absentie.

## Privacy — non-negotiable

This project holds personal data about athletes, many of them minors.

- **Never commit databases or real athlete data.** `data/`, `*.db`, `*.sqlite*`,
  `*.csv` and `*.xlsx` are git-ignored on purpose. Do not weaken `.gitignore`,
  and do not add files that contain real names, birth dates or results.
- **Never commit, print or log keys.** The master key lives only in the OS
  keyring; the recovery key is shown only on explicit request
  (`--herstelsleutel`). Do not write keys to files, config or test fixtures.
- **Keep the split intact.** Names, birth dates, `master_id` and `atletieknu_id`
  live only in `personen.db`. Never copy them into `prestaties.db`,
  `testen.db` or `trainingsschema.db`, and never store anything there that points back to a person
  (e.g. a per-athlete atletiek.nu URL).
- Test fixtures in `tests/fixtures/` must be **anonymised** (fake names, fake
  athlete IDs) before they are saved.
- Do not print or log personal data beyond what a feature needs.

## Tech stack and architecture

- **Python** for all processing; **SQLite encrypted with SQLCipher** (via the
  `sqlcipher3` module, pip package `sqlcipher3-wheels`) for storage, and
  `keyring` for the master key. Data lives in SQL; logic lives in Python.
- **UI**: a local web UI — `src/ui/app.py` is to become a Flask/FastAPI server
  with `templates/` and `static/`. The framework choice is still open.
- **Distribution**: PyInstaller, driven by `build.py` (one command → `.exe`).
  Code must work both from source and frozen: use `sys.frozen` checks as in
  `standaard_map()` and never assume the current working directory. The build
  needs `--hidden-import keyring.backends.Windows`.

### Layout (`src/`)

| Package       | Purpose |
|---------------|---------|
| `models/`     | Data classes: `atleet`, `prestatie`, `groep`, `leerlijn` |
| `db/`         | `schema_<database>.sql`, `init_db.py` (keys, connect, create/migrate), `queries.py`, `migrations/<database>/` |
| `importers/`  | Import results from links: atletiek.nu PRs, atletiek.nu competitions, Seltec competitions |
| `ploeg/`      | Team selection: `vergelijk` (compare athletes), `regels` (rules), `opstelling` (lineup), `strategieen/` (selection "mentalities") |
| `groepen/`    | Groups, `absentie`, `periodeplan` |
| `atleten/`, `leerlijnen/` | Feature logic for athletes and learning pathways |
| `ui/`         | Web UI |

Other folders: `config/ploeg_regels/*.yaml` (team rule sets, per competition),
`tests/`, `docs/`.

Many files are still placeholders (a docstring or `#This is an empty temporary
file`): `pyproject.toml`, `build.py`, `src/__main__.py`, the YAML rule sets and
most modules. The docstring in each placeholder describes its intended role —
follow it when implementing.

## Database

### Three encrypted databases

The data is split over four SQLCipher-encrypted files in `data/` (repo root
when run from source, next to the `.exe` when frozen):

| File             | Contents | Athlete identified by |
|------------------|----------|-----------------------|
| `personen.db`    | `atleet` (personal details), groups, trainings, `absentie`, `periodeplan`, leerlijnen, `ploeg`, `ploeg_opstelling` | `master_id` |
| `prestaties.db`  | `onderdeel`, `wedstrijd`, `prestatie`, `inschrijving`, `pr` view | `atleet_ref` (pseudonym) |
| `testen.db`      | `test`, `testresultaat` | `atleet_ref` (pseudonym) |
| `trainingsschema.db` | `trainingsschema`: one row per athlete, columns `maandag` … `zondag` (0/1) | `atleet_ref` (pseudonym) |

None of the databases are in git. `src/db/init_db.py` creates them and brings
them up to date:

```
python src/db/init_db.py                      # create/update data/*.db
python src/db/init_db.py pad/naar/map         # another folder (e.g. for tests)
python src/db/init_db.py --herstelsleutel     # show the recovery key
python src/db/init_db.py --herstel <sleutel>  # restore the key (e.g. new computer)
```

### Keys and IDs

- One random 32-byte **master key** is stored in the OS keyring (service `AVS`,
  name `hoofdsleutel`). It is created on the first run. `init_db` refuses to
  create a new key when databases already exist, and `herstel()` refuses to
  overwrite a different key — losing the key means losing all data.
- From the master key, HMAC-SHA256 derives a separate **encryption key per
  database** and a separate **pseudonym key per database**.
- Every athlete gets a random `master_id` (32 hex chars) in `personen.db`.
  Create it with `nieuw_master_id()` — **never derive it** from name, birth date
  or a federation number.
- In `prestaties.db`, `testen.db` and `trainingsschema.db` an athlete is
  `atleet_ref = pseudoniem(master_id, "prestaties" | "testen" | "trainingsschema")`.
  The pseudonyms differ per database, so the files cannot be joined without the master key.
  To combine data, look up the `master_id` in `personen.db` and compute the
  pseudonym in Python; there is no stored mapping table.
- Cross-file references (`ploeg.wedstrijd_id`, `ploeg_opstelling.onderdeel_id`
  → `prestaties.db`) are not enforced by SQLite; check them in Python.

### Rules

- Always open connections through `verbind("<database>")` so the key,
  `PRAGMA foreign_keys = ON`, `temp_store = MEMORY` and `sqlcipher3.Row` are
  set. Never use the plain `sqlite3` module on these files.
- Tests pass an explicit test key (`hoofd=` in `verbind()` / `init_db()`) and a
  temporary folder; they never touch the real keyring or `data/`.
- Each `schema_<database>.sql` is **version 1 and frozen**. Every later schema
  change goes in a new migration for that database:
  `src/db/migrations/<database>/NNN_beschrijving.sql` (e.g.
  `migrations/testen/002_add_testlocatie.sql`). Migrations are applied in
  number order and recorded in that database's `schema_version`. Never edit an
  applied migration and never drop or wipe an existing database.
- Use parameterised queries (`?`), never string formatting.
- Conventions in the schemas:
  - Dates are ISO text, `'YYYY-MM-DD'` (birth date may be just `'YYYY'`).
  - `prestatie.waarde` is a REAL in seconds, metres or points; whether lower is
    better comes from `onderdeel.lager_is_beter`.
  - PRs are derived by the `pr` view — there is no PR table to keep in sync.
  - `prestatie.ronde` uses `''` rather than NULL so the UNIQUE constraint that
    prevents duplicate imports works.
  - `bron` is one of `'atletieknu'`, `'seltec'`, `'handmatig'`.

## Importers

- Every importer implements the shared interface in `importers/base.py`:
  `can_handle(url)` and `parse(url)`.
- `importers/detect.py` picks the importer automatically by trying each
  `can_handle(url)` until one matches. Register new importers there.
- Match each imported athlete to a `master_id` in `personen.db` (via
  `atleet.atletieknu_id` where available), then store results in
  `prestaties.db` under the pseudonym. Drop names and per-athlete URLs after
  matching; do not store raw scraped pages.
- Imports must be idempotent: re-importing the same link must not create
  duplicates (rely on the UNIQUE constraints and `wedstrijd.bron_url`).
- Tests run against saved, anonymised pages in `tests/fixtures/` — not against
  the live sites.

## Team selection (ploeg)

- Rules live in YAML (`config/ploeg_regels/`), so team leaders can change them
  without touching code. Do not hard-code competition rules in Python.
- Strategies ("mentaliteiten") are pluggable modules in `ploeg/strategieen/`.
- `ploeg.regelset` stores the rule file name and `ploeg.strategie` the strategy
  used, so a lineup can be explained afterwards.

## Git workflow

Build every feature on its own branch, then merge upward:

```
feature/<naam>  →  dev  →  staging  →  main
```

- `dev` = development, `staging` = dress rehearsal, `main` = production/released.
- Never commit straight to `main` or `staging`; open feature work against `dev`.

## Working style

- Keep the UI simple for non-technical users; put the complexity in the back end.
- Write tests for new logic (`tests/`); importers and team selection especially.
- When a design decision is still open (UI framework, test runner, dependency
  management in `pyproject.toml`), propose an option and ask rather than
  silently picking one.