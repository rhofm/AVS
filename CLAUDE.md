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
- Test fixtures in `tests/fixtures/` must be **anonymised** (fake names, fake
  athlete IDs) before they are saved.
- Do not print or log personal data beyond what a feature needs.

## Tech stack and architecture

- **Python** for all processing; **SQLite** (via the standard `sqlite3` module)
  for storage. Data lives in SQL; logic lives in Python.
- **UI**: a local web UI — `src/ui/app.py` is to become a Flask/FastAPI server
  with `templates/` and `static/`. The framework choice is still open.
- **Distribution**: PyInstaller, driven by `build.py` (one command → `.exe`).
  Code must work both from source and frozen: use `sys.frozen` checks as in
  `standaard_db_pad()` and never assume the current working directory.

### Layout (`src/`)

| Package       | Purpose |
|---------------|---------|
| `models/`     | Data classes: `atleet`, `prestatie`, `groep`, `leerlijn` |
| `db/`         | `schema.sql`, `init_db.py` (create/migrate), `queries.py`, `migrations/` |
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

- The database is **not in git**. `src/db/init_db.py` creates it at
  `data/avs.db` (repo root when run from source, next to the `.exe` when frozen)
  and brings it up to date:
  ```
  python src/db/init_db.py              # create/update data/avs.db
  python src/db/init_db.py pad/naar.db  # another location (e.g. for tests)
  ```
- `schema.sql` is **version 1 and frozen**. Every later schema change goes in a
  new migration: `src/db/migrations/NNN_beschrijving.sql` (e.g.
  `002_add_blessures.sql`). Migrations are applied in number order and recorded
  in `schema_version`. Never edit an applied migration and never drop or wipe an
  existing database.
- Always open connections through `verbind()` so `PRAGMA foreign_keys = ON` and
  `sqlite3.Row` are set. Use parameterised queries (`?`), never string formatting.
- Conventions in the schema:
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
- Imports must be idempotent: re-importing the same link must not create
  duplicates (rely on the UNIQUE constraints and `bron_url`).
- Link imported athletes via `atleet.atletieknu_id` where available.
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