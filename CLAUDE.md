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
  (`--herstelsleutel`, or the button on Instellingen). Do not write keys to
  files, config or test fixtures.
- **Keep the split intact.** Names, birth dates, `master_id`, `atletieknu_id` and
  `au_licentienummer` (Atletiekunie licence number) live only in `personen.db`. Never copy them into `prestaties.db`,
  `testen.db`, `trainingsschema.db`, `absentie.db`, `leerlijnen.db`,
  `leerdoelscores.db` or `notities.db`, and never store anything there that points back to a person
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
- **Settings** (page Instellingen): `src/instellingen/` keeps first weekday, theme,
  time notation and name order (sort athletes by last or first name) in
  `instellingen.json` in the data folder (no personal data, so plain JSON).
  'systeem' = follow the computer (`instellingen/systeem.py` reads the Windows
  registry; the theme follows the browser's `prefers-color-scheme`). Never loop
  over `DAGEN` for *display*: use `instellingen.dagvolgorde()` (and `weekbegin()`,
  `eerste_weekdag()` for calendars). Show times with `instellingen.tijd()` /
  `tijdvak()` or the Jinja filters `| tijd` / `| tijdvak(eind)`, never raw
  'HH:MM'. Storage and form values stay 'HH:MM' and Monday-first. Sort athletes
  with `instellingen.naam_sleutel` / `op_naam()` (and `naam_tekst()` for
  `data-sort`), never with a hard-coded `ORDER BY achternaam`.
- **Distribution**: PyInstaller, driven by `build.py` (one command → `.exe`):
  `python build.py` clears `build/` + `dist/`, runs the tests (no build if they
  fail), builds `dist/AVS.exe` (`--onedir`: a folder), checks the build's
  contents for anything that looks like data (`.db`, `.csv`, `.xlsx`,
  `instellingen.json`, `data/`, `tests/` → refused), runs `AVS.exe --zelftest`
  and writes the exact package versions to `dist/AVS-pakketten.txt`.
  `--zonder-tests` is for trial builds only. The `.exe` is `--windowed`. What goes in is listed in
  `build.bronnen()`; every own module is passed as `--hidden-import` (from
  `zelftest_modules.txt`), plus `keyring.backends.Windows`, `--collect-all
  curl_cffi`, `--collect-binaries sqlcipher3`; optional packages AVS doesn't use
  are excluded (`NIET_MEENEMEN`). Code must work both from source and frozen:
  use `sys.frozen` checks as in `standaard_map()` and never assume the current
  working directory.

### Layout (`src/`)

| Package       | Purpose |
|---------------|---------|
| `models/`     | Data classes: `atleet`, `prestatie`, `groep`, `leerlijn`, `periodisering`, `rooster`, `doel`, `ploeg` |
| `db/`         | `schema_<database>.sql`, `init_db.py` (keys, connect, create/migrate), `queries.py`, `migrations/<database>/` |
| `importers/`  | Import results from links: atletiek.nu PRs, atletiek.nu competitions, Seltec competitions |
| `ploeg/`      | Team selection: `vergelijk` (compare athletes), `voorspeller` (predictions), `estafettes` (relays), `regels` (rules), `opstelling` (lineup), `optimaliseer` + `strategieen/` (selection "mentalities") |
| `groepen/`    | Groups, `absentie`, `periodeplan` (periodisering pages: mega/meso cycle, year view, copy), `rooster` (planned training content, import, apply to trainings), `doelen` (goals: status, forms) |
| `wedstrijden/` | `planning`: upcoming meets, who goes, which events (uses `wedstrijd` + `inschrijving` in `prestaties.db`) |
| `atleten/`, `leerlijnen/` | Feature logic for athletes and learning pathways |
| `ui/`         | Web UI |

Other folders: `config/ploeg_regels/*.yaml` (team rule sets, per competition),
`config/puntentelling/<uitgave>.yaml` (AU scoring constants, one file per
edition of "Formules & Constanten"), `tests/`, `docs/`. Find config files with
`ploeg.config.config_bestand(submap, naam)` / `config_bestanden(submap)` (works
from source and frozen; never use the working directory). Frozen, each file is
looked up separately: `config/` next to the `.exe` first (the team leader's own
edits and additions), then the copy built into the `.exe`; an empty file
(only whitespace/#-comments) never hides a filled one. Loaded files are cached
by path + modification time, so an edited YAML file counts without a restart. Design of the team feature: `docs/Ploegopstelling_ontwerp.md`.

Some YAML rule sets (`competitie_u16.yaml`, `standaard.yaml`) are still empty
placeholders (`#This is an empty temporary file`).

**Dependencies** are in `pyproject.toml` (Python 3.13), installed into the
conda environment with `pip install -e .[dev]` (`[dev]` = pytest + PyInstaller).
It installs only the dependencies: `[tool.setuptools] packages = []`, so the
generic folder names in `src/` (`db`, `ui`, `models`, …) never land in
site-packages. Every lower bound must have a ready-made Windows wheel for
Python 3.13 (checked with `pip download --only-binary :all: --python-version 3.13
--platform win_amd64`); a new dependency goes in `dependencies` with a comment
saying what uses it.

**Starting and stopping** (`src/__main__.py`, `src/ui/levensduur.py`): `python src`
/ `AVS.exe` starts the app; `--geen-browser` doesn't open the browser. The `.exe`
has no console window (`--windowed`): AVS stops by itself when the last AVS tab is
closed, or with the **AVS afsluiten** button in the app bar (`POST /afsluiten`,
page `afgesloten.html`). Every page loads `static/levend.js` (only when a
`Bewaker` is set, i.e. a real start): `POST /levend` with a per-page id on load
and every `HARTSLAG` s, `navigator.sendBeacon('/weg')` on `pagehide`. The
`Bewaker` stops the server when no page is open and nothing happened for
`WEG_WACHTTIJD` s, when a page was silent for `TIJDLIMIET` s (generous: browsers
throttle background tabs to once a minute), or when no page came within
`EERSTE_PAGINA` s; a jump in its own clock means the computer slept, which
never stops AVS. It stops via `server.shutdown()` in another thread, so never in
the middle of a request. `/weg` and `/afsluiten` only accept requests from AVS
itself (`_van_deze_app`). Request logging is off (`_StilleHandler`: URLs contain
athlete ids). Without a console, `--zelftest` writes to the console it was
started from (`AttachConsole`), and an unexpected start error is shown as a
Windows message box.

**Self-test**: `--zelftest` (`src/zelftest.py`)
checks everything a build can miss — all own modules import, the outside packages,
SQL files, a throw-away encrypted database (random key, temp folder), the
keyring backend, every rule file loads, strategies, `milp`, a PDF, curl_cffi,
all templates and static files — and exits 0/1. It never touches the real data
folder or keyring. In the `.exe` the module list comes from `zelftest_modules.txt`
(`zelftest.schrijf_modulelijst()`, written by `build.py`), because PyInstaller
only bundles what it finds through imports: a module nothing imports (e.g.
`importers.detect`) would otherwise be missing silently. A new outside package
also goes in `zelftest.EXTERNE_MODULES`.

The keyring can fail on its own (no backend, Credential Manager blocked):
`_lees_hoofdsleutel`/`_bewaar_hoofdsleutel` turn any `KeyringError` into
`SleutelkluisFout` (an `InstallatieFout`, not a `SleutelFout`: restoring the key
can't help), shown on the error page at start and during use; never a traceback.

## Database

### Encrypted databases

The data is split over eight SQLCipher-encrypted files in the data folder,
`init_db.standaard_map()`: `data/` in the repo root when run from source,
`%LOCALAPPDATA%\AVS\data` when frozen (always writable, wherever the `.exe`
is), or `$AVS_DATA` when that environment variable is set. On the first frozen
start with an empty data folder, `oude_data_overnemen()` copies a `data/`
folder next to the `.exe` (copy only, never overwrite, all-or-nothing; on
failure `OvernameFout` and no `init_db()`, so no empty databases appear). The
Instellingen page shows the data folder. Never hard-code `data/` elsewhere. The files:

| File             | Contents | Athlete identified by |
|------------------|----------|-----------------------|
| `personen.db`    | `atleet` (personal details), `groep` (id + name), `groep_trainingstijden` (one row per group: `groep_id` + `maandag` … `zondag`, start time 'HH:MM' or NULL = no training), `groep_extra_trainingstijd` (extra start times on a fixed day: `groep_id`, `dag`, `starttijd`), `groep_lid` (long: one row per athlete per group; an athlete can be in several groups), `training` (`warming_up`, `kern_a`, `kern_b`, `cooling_down`, `notities`; `hoofdtraining_id` for a deviating variant), `training_atleet` (long: who follows a variant), `groep_fase` (mega cycle: `groep_id`, `startdatum`, `fase`), `mesocyclus` + `mesocyclus_week` (meso cycles and week names), `rooster` + `rooster_regel` (training-content templates) + `groep_rooster` (which group follows which template from when), leerlijnen, `ploeg` (+ `categorie`, `programma`, `datum`, `prestatiebasis`), `ploeg_lid` (who is on the form: `rol` deelnemer/reserve, `beschikbaar`), `ploeg_opstelling` (athlete + programme key from the rule file, `groep`, `vast`), `atleet_voorkeur` + `ploeg_voorkeur` (team-selection preferences); `periodeplan` is obsolete and always empty | `master_id` |
| `prestaties.db`  | `onderdeel`, `wedstrijd`, `prestatie`, `inschrijving`, `wedstrijd_programma` (meet timetable / chronoloog: one row per item, no personal data), `doel` + `doel_regel` (goals for a group or athlete, usually at a meet), `pr` view | `atleet_ref` (pseudonym) |
| `testen.db`      | `test`, `testresultaat` | `atleet_ref` (pseudonym) |
| `trainingsschema.db` | `trainingsschema`: one row per athlete, columns `maandag` … `zondag` (0/1); `trainingskeuze`: which (`groep_id`, `starttijd`) the athlete picks on a day with several trainings | `atleet_ref` (pseudonym) |
| `absentie.db`    | `absentie`: long format, one row per athlete per training (`training_id`, `status`, `reden`) | `atleet_ref` (pseudonym) |
| `leerlijnen.db`  | Catalogue, no personal data: `leerlijn`, `leerdoel` (id `SPR-U10-01`, per category U10–U20), `categorie`, `scoreschaal` | — |
| `leerdoelscores.db` | `leerdoelscore`: long format, one row per athlete per leerdoel per date (score 1–5), `laatste_leerdoelscore` view | `atleet_ref` (pseudonym) |
| `notities.db`    | `notitie`: free-text notes, one row per note (`datum`, `inhoud`, `aangemaakt_op`, `bijgewerkt_op`) | `atleet_ref` (pseudonym) |

None of the databases are in git. `src/db/init_db.py` creates them and brings
them up to date:

```
python src/db/init_db.py                      # create/update data/*.db
python src/db/init_db.py pad/naar/map         # another folder (e.g. for tests)
python src/db/init_db.py --herstelsleutel     # show the recovery key
python src/db/init_db.py --herstel <sleutel>  # restore the key (e.g. new computer)
```

Users without a terminal (the `.exe`) restore the key on **Instellingen > Sleutel
herstellen** (`POST /instellingen/sleutel`). That page and the settings form work
even when the databases can't be opened (`ZONDER_DATABASE` in `ui/app.py`);
every other page shows the start error. `herstel()` only stores a key after it
has opened the existing databases, and the submitted key is never echoed,
logged or cached.

Writing the key down works the other way round: **Instellingen > Herstelsleutel
tonen** (`POST /instellingen/sleutel/tonen`) shows it in groups of 8, only when
the databases are open (not in `ZONDER_DATABASE`, and refused while there is a
start error) and only a key that actually opens them
(`init_db.herstelsleutel_als_hij_past()`). POST only and only from AVS itself
(`_van_deze_app`), the response is `Cache-Control: no-store`, and a normal GET of
the page never contains the key.

The SQL files are read from `init_db.SQL_DIR` (`src/db/` from source,
`sys._MEIPASS/db` in the `.exe`), never via the working directory. `init_db()`
first runs `controleer_sql_bestanden()` and refuses databases newer than the
newest known migration (`_controleer_versies()`); both raise `InstallatieFout`
before anything is touched. A new database needs its `schema_<naam>.sql` in
`src/db/`; the build includes `schema_*.sql` and `migrations/`.

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
- In every database except `personen.db` an athlete is
  `atleet_ref = pseudoniem(master_id, "<database>")`.
  The pseudonyms differ per database, so the files cannot be joined without the master key.
  To combine data, look up the `master_id` in `personen.db` and compute the
  pseudonym in Python; there is no stored mapping table.
- Cross-file references (`ploeg.wedstrijd_id` → `prestaties.db`; `absentie.training_id` → `personen.db`;
  `leerdoelscore.leerdoel_id` → `leerlijnen.db`) are not enforced
  by SQLite; check them in Python. Deleting a training must go through
  `Opslag.training_verwijderen()` so its absence rows go too.
- Leerdoel ids are never reused or renumbered (scores point to them); retire a
  leerdoel with `actief = 0` in a migration. The old `leerlijn`/`leerlijn_stap`/
  `atleet_leerlijn` tables in `personen.db` predate `leerlijnen.db` and are superseded
  by it (the old `Opslag.leerlijn*`/`voortgang*` methods still use them).
- Notes (`notities.db`) are free text: the pseudonym protects the link to the
  athlete, but not what is written in the text. Only the encryption protects
  that. Keep notes factual, no diagnoses, and don't name other athletes.
  `Notitie.inhoud` is hidden from `repr()`; never log note text.
- Group training times live once per group in `groep_trainingstijden`, never
  per athlete. Every training day has a start time (empty = no training).
  `groep_opslaan()` does not touch them; save them with
  `groep_trainingsdagen_opslaan()`. Joining a group or adding a day only ADDS
  days to the members' `trainingsschema` (`groepen.groep.schema_aanvullen`);
  nothing removes days automatically, since that can differ per athlete.
- A group can train more than once on a day: the main time stays in
  `groep_trainingstijden`, extra times go in `groep_extra_trainingstijd` (only
  on days with a main time; `Groep.tijden(dag)` gives all). Each time is its own
  `training` row; `training.starttijd` NULL = the day's main time, so always
  read it with `Training.effectieve_starttijd(groep)`.
- `trainingskeuze` stores a strict subset only: no rows for a day = all
  trainings of the athlete's groups that day. Keuzes for a group the athlete
  left or a time the group dropped are ignored on reading. Use
  `Trainingsschema.traint_mee(training, groep)` (not `traint_op`) wherever
  "is this athlete expected at this training" matters: pre-filling attendance,
  expected counts, 'niet ingevuld'. The attendance form still lists all members.
- Every migration number must be unique per database. `init_db.py` refuses to
  start when two files share a number (this happened once after merging two
  branches that both added a `003`).
- Training texts (`warming_up`, `kern_a`, `kern_b`, `cooling_down`,
  `notities`) are multi-line and may contain a small markdown subset; render
  them only with the `markdown` Jinja filter (`ui/markdown.py`), which escapes
  all HTML first. Never mark training text `| safe`.
- A deviating training is a `training` row with `hoofdtraining_id` = the normal
  training of the group (same group and date) plus its athletes in
  `training_atleet`. `Opslag.trainingen()` returns normal trainings only;
  attendance always belongs to the normal training. Use
  `Opslag.training_voor_atleet()` to find what one athlete does.
- Trainings on a group's fixed training days are created automatically
  (`groepen.trainingen.trainingen_aanvullen`, once a day and after changing
  the days); if the group follows a rooster they get its content right away.
  Only empty future trainings (no texts, variants or attendance) are ever
  removed automatically (`trainingen_opruimen`).
- Periodisering (`models/periodisering.py`, `groepen/periodeplan.py`): a mega
  cycle row (`groep_fase`) or meso cycle (`mesocyclus`) holds from its
  `startdatum` until the next row of the same kind; only start dates are
  stored. Phase and meso week are derived from the date
  (`Periodisering.op(datum)`), never stored per training. Phases are
  `V1`, `V2`, `WP`, `Rust` and `Geen` (ends the periodisation); labels live
  in `FASEN`. A meso cycle starts on `instellingen.weekbegin()`. Saving
  replaces all rows of a group (`groep_fasen_opslaan`, `mesocycli_opslaan`).
  Sharing between groups is a copy (`periodeplan.kopieren`), never a link.
- Rooster (`models/rooster.py`, `groepen/rooster.py`): a `rooster` is a
  template of N weeks; `rooster_regel` = content for (week, dag, starttijd),
  starttijd NULL = the day's main time. A group follows a rooster from a
  `groep_rooster.startdatum` (week start) until its next koppeling; `herhalen`
  repeats the weeks, `einddatum` stops it. Rooster weeks are independent of
  the meso cycle. Content is **copied** into trainings and
  `training.rooster_regel_id` records where it came from: only trainings that
  are empty or still linked are (re)filled (`rooster_toepassen`), never past
  trainings or variants; editing a training with different content unlinks it
  (`losmaken_als_aangepast`). Rooster-only content counts as empty for
  `trainingen_opruimen`. Before deleting a rule, clear its linked future
  trainings (`regel_opslaan` does): `ON DELETE SET NULL` would otherwise make
  them look hand-written.
- Doelen (`models/doel.py`, `groepen/doelen.py`, tables `doel` + `doel_regel`
  in `prestaties.db`): a goal belongs to a group (`groep_id`, cross-file, checked
  in Python) or is personal (`groep_id` NULL, all rows for one athlete). Rows
  name the athlete as `atleet_ref` (prestaties pseudonym; NULL = whole group).
  The target date is `datum`, else the meet's date. Whether a row is achieved
  is **derived**, never stored: best wind-legal result on the event (at the
  meet, or between `startdatum` and the target date), or the latest leerdoel
  score up to the target date; a manual `beoordeling` always wins.
  `atleet_verwijderen` removes the athlete's rows (and personal goals left
  empty); `wedstrijd_verwijderen` copies the meet date into goals that had no
  own date. Free text in goals follows the notes rule: factual, no other
  athletes' names, no diagnoses.
- The old `periodeplan` table was replaced (migration personen/007):
  `init_db` copies its rows to `doel` in `prestaties.db` and empties it. The
  table and `training.periodeplan_id` stay because SQLite refuses inserts into
  `training` once the parent table of its foreign key is gone; never drop it
  without rebuilding `training`, and never write to either.
- Absence stores every status explicitly, `aanwezig` included: no row means
  "not filled in yet". `blessure` is health data — keep `reden` short and
  factual, never a diagnosis.

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
- The atletiek.nu timetable importer (`importers/atletieknu_tijdschema.py`)
  reads `/wedstrijd/chronoloog/<id>/`; any meet link or id works. Duration only
  exists when the page has the timeline tab ('visueel'); otherwise it stays
  empty. `wedstrijden/tijdschema_import.py` writes it to `wedstrijd_programma`
  (replacing the old version) and never creates events itself: unmatched
  events are stored as text and listed in the report.
- The Seltec timetable importer (`importers/seltec_tijdschema.py`) reads
  `/Competitions/Details/<id>` plus one page per day (`/Details/<id>/<dag>`);
  the date is the first day from the header + (day − 1). Seltec gives no end
  times, so duration stays empty. A row can be for several categories
  ('U18M, U16J'); it stays one row and `chronoloog.past_bij` matches if any
  of them fits. Seltec's `M` is ambiguous: men from U18 up, girls up to U16
  (`U16J` = boys). Codes are stored as `U18-M`, `U16-V`, `SEN-V`, `Masters-M`.
  `tijdschema_import.site_van` picks atletiek.nu or Seltec from the link, the
  saved file, or (for a bare id) the meet's own link. `detect.kies_importer`
  still sends Seltec `Details` links to the results importer.
- Match each imported athlete to a `master_id` in `personen.db` (via
  `atleet.atletieknu_id` where available), then store results in
  `prestaties.db` under the pseudonym. Drop names and per-athlete URLs after
  matching; do not store raw scraped pages.
- Imports must be idempotent: re-importing the same link must not create
  duplicates (rely on the UNIQUE constraints and `wedstrijd.bron_url`).
- A meet's timetable (`wedstrijd_programma`) belongs to the meet, not to a
  person: date, start time, `duur` (minutes), event (`onderdeel_id` and/or
  `onderdeel_tekst`), `categorie` as written in the timetable, `ronde`, `groep`
  (1st, 2nd, ...), `opmerking`. Who has to be where is computed by
  `wedstrijden/chronoloog.py` from the registrations and the athlete's
  category on the day of the meet; never store per-athlete times.
- Results of a held meet are imported with `wedstrijden/uitslag_import.py`
  (button 'Uitslagen importeren' on the meet page). Only certain matches are
  saved automatically (`koppelen.py`, or the name of exactly one athlete
  registered for the meet); name-only matches wait for the trainer. Between
  import and confirmation nothing is kept on the server: the form carries the
  candidate master_ids and the values (re-checked on submit); the name and club
  from the site are only shown, never stored.
- A planned meet and its results are the **same** `wedstrijd` row. Always pass
  meet links through `wedstrijden.planning.normaliseer_link()` before saving,
  so an atletiek.nu `/main/`, `/inschrijvingen/` or `/uitslagen/` link all
  find the meet that was planned earlier.
- Tests run against saved, anonymised pages in `tests/fixtures/` — not against
  the live sites.

## Team selection (ploeg)

- Rules live in YAML (`config/ploeg_regels/`), so team leaders can change them
  without touching code. Do not hard-code competition rules in Python.
- Points come from `ploeg/punten.py` (`punten()`, `prestatie_voor()`); the
  constants live in `config/puntentelling/`, never in Python. Points are
  truncated (`INT`), never negative; hand times are corrected with
  `handtijd_correctie()`. A new AU edition is a new YAML file, not an edit.
- `ploeg/regels.py` loads a rule file into a `Regelset` (validated on load,
  also against the scoring table: every programme event needs a points
  formula) and checks a lineup with `controleer()` / `controleer_dag()`.
  Event keys in rule files are the keys of the scoring table (`80mH`,
  `kogelstoten`, `4x80m`), or carry `punten:` when they differ (senior events
  `100m-V` / `100m-M` with `geslacht:` in the mixed ploeg `SEN`); categories are
  codes like `U14-V`, `U16-M`, `SEN-V` (`categorie_code()`), or masters classes
  `V45` in a file with `leeftijdsklassen: masters` (`masters_code()`, age on the
  meet day; `V35+` in `toegestaan`/`specificatie` means "from V35"). Rule files
  exist for U14/U16, U18/U20, masters, NK Teams and senioren 1e/2e/3e divisie
  (see `docs/Ploegopstelling_ontwerp.md`). A lineup is `models.ploeg`: `PloegLid` (who is on the
  form, `rol` deelnemer/reserve) and `Inzet` (athlete + event key). Violations
  name athletes only by master_id; the UI adds names.
- A ploeg stores its own `datum`; with a linked meet the meet's date wins (the
  page moves it along) and deleting the meet only unlinks it. `ploeg_opstelling`
  rows exist only for members (FK to `ploeg_lid`); save both together with
  `Opslag.ploeg_opstelling_opslaan()`. The athletes × events matrix is
  `ploeg/vergelijk.matrix()` (best wind-legal performance per `prestatiebasis`
  up to the meet day, matched by event name + specification from the rule
  file; hand times count with correction); totals and checks are in
  `ploeg/opstelling.py`, page data in `ploeg/paginas.py`. Nothing in the
  matrix is stored.
- Saving a lineup of a ploeg linked to a meet also writes `inschrijving` rows
  (`ploeg/inschrijven.synchroniseer`, old -> new lineup, so the trainer's own
  registrations stay); go through `ploeg.paginas.ploeg_opslaan` /
  `opstelling_opslaan` / `ploeg_verwijderen`, not the bare `Opslag` methods,
  from the UI. The atletiek.nu CSV (`ploeg/export.py`) holds personal data: build
  it in memory and only return it as a download (`Cache-Control: no-store`);
  never write it to disk or log it.
- Strategies ("mentaliteiten") are pluggable modules in `ploeg/strategieen/`:
  a class `Strategie` with `naam`, `titel`, `uitleg` and `bouw(model)` returning
  objectives (maximised one after the other) for the MILP in
  `ploeg/optimaliseer.py` (`scipy.optimize.milp`). Register a new one in
  `STRATEGIEEN` (explicit imports, so PyInstaller bundles it). scipy is a
  runtime dependency of the optimiser only; the rest of AVS works without it.
- Missing performances are predicted (`ploeg/voorspeller.py`) from the rule
  file's `buren` (neighbour events, via equal points) and `verhouding`
  (implement/hurdle-height ratios), times `algemeen.voorspelling_factor`.
  Predictions only use real performances (no chains), are always flagged
  (`Cel.voorspeld`, `Cel.bron`) and are never exported as a performance (the
  CSV gets 'x'). Relays (`ploeg/estafettes.py`): sum of the leg times
  (`benen`) + `correctie_s`; the optimiser chooses among precomputed quartets.
  All these numbers are configuration, not code.
- With a linked meet that has a timetable, `ploeg/tijdschema.py` maps timetable
  rows to programme keys per athlete: clashes and events outside the member's
  `beschikbaar` (morning/afternoon, afternoon from 13:00) are warnings in the
  check and hard constraints in the optimiser; technical-event groups (9.1) are
  assigned automatically on save/optimise (`groepen_indelen`). All ploegen of
  one day are made in order on `/ploegen/dag/<datum>` (`dag_optimaliseren`:
  earlier ploeg picks first, 10.10).
- Masters age grading: `leeftijdsfactoren:` in the rule file names a file in
  `config/puntentelling/` (`punten.Leeftijdsfactoren`; performance x factor,
  then the senior formula). The shipped `masters_agegrading.yaml` is still
  empty: never invent factors; they must come from the AU tables.
- Athlete preferences (`ploeg/voorkeuren.py`, migration personen/011): standing
  per athlete in `atleet_voorkeur` (event name without specification, matched
  with `normaliseer`) and per ploeg in `ploeg_voorkeur` (programme key; wins over
  the standing one, `neutraal` switches it off). `wil_niet`/`moet` are hard in the
  optimiser, `voorkeur` is an objective inserted right after the strategy's
  first one; the check only warns.
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
- When a design decision is still open (e.g. the UI framework), propose an
  option and ask rather than silently picking one. Decided: pytest as test
  runner, plain `pyproject.toml` dependencies installed with pip into the conda
  environment.
