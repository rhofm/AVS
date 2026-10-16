# Repo-overzicht — Atleet Volg Systeem (AVS)

What lives where in this repo, and how far along each part is.
For the features and ideas behind it, see [Structuur.md](Structuur.md); for coding rules, see [CLAUDE.md](../CLAUDE.md).

> **Snapshot:** branch `feature/atleten`, 15 October 2026.
> Other branches can differ. The importer code, for example, is being built on `feature/importers`, so on this branch those files are still placeholders.

**Legend**

| Mark | Meaning |
|------|---------|
| ✅ | Implemented and tested |
| 📝 | Placeholder: only a docstring or `#This is an empty temporary file` |
| 🔒 | Git-ignored, never committed (privacy) |
| ⚠️ | Needs attention |

---

## Tree

```
AVS/
├── README.md                     ✅ features, ideas, git workflow
├── CLAUDE.md                     ✅ conventions, privacy rules, database design
├── pyproject.toml                📝⚠️ not valid TOML yet
├── build.py                      📝 the "one command" → PyInstaller → AVS.exe
├── .gitignore                    ✅ data/, databases, csv/xlsx, build output
│
├── docs/
│   ├── Structuur.md              ✅ features per area
│   └── ToC.md                    ✅ this file
│
├── config/
│   └── ploeg_regels/             lineup rules (YAML), editable by the team leader
│       ├── standaard.yaml        📝
│       └── competitie_u16.yaml   📝
│
├── data/                         🔒 real databases and test data
│   ├── personen.db               🔒 created by init_db.py
│   ├── prestaties.db             🔒 created by init_db.py
│   ├── testen.db                 🔒 created by init_db.py
│   ├── trainingsschema.db        🔒 created by init_db.py
│   ├── absentie.db               🔒 created by init_db.py
│   ├── vervangingen.txt          🔒 real name → fake name, for anonymising fixtures
│   └── live_controle/            🔒 live checks of the importers against the real sites
│
├── src/
│   ├── __main__.py               📝 starts the app and opens the browser
│   │
│   ├── db/
│   │   ├── init_db.py            ✅ keys, verbind(), create + migrate the 5 databases
│   │   ├── queries.py            ✅ class Opslag: all SQL, models in → models out
│   │   ├── schema_personen.sql   ✅ v1 (frozen): athletes, groups, trainings, leerlijnen, ploegen
│   │   ├── schema_prestaties.sql ✅ v1 (frozen): onderdelen, wedstrijden, prestaties, pr view
│   │   ├── schema_testen.sql     ✅ v1 (frozen): tests, test results
│   │   ├── schema_trainingsschema.sql ✅ v1 (frozen): training days per athlete (one column per weekday)
│   │   ├── schema_absentie.sql   ✅ v1 (frozen): attendance per training, long format
│   │   ├── schema.sql            ⚠️ old single-database schema, no longer used
│   │   └── migrations/
│   │       ├── personen/
│   │       │   └── 002_absentie_naar_eigen_database.sql  ✅ moves absence out of personen.db (init_db copies the rows)
│   │       └── prestaties/
│   │           └── 002_pr_alleen_windlegaal.sql       ✅ PR view: windmeting per event (sprint/hurdles ≤200 m,
│   │                                                     long/triple jump), max +2.0, indoor always counts
│   │
│   ├── models/                   ✅ dataclasses, no SQL
│   │   ├── atleet.py             Atleet (names hidden from repr)
│   │   ├── prestatie.py          Onderdeel, Wedstrijd, Prestatie, Inschrijving, PR, Test, Testresultaat
│   │   ├── groep.py              Groep, Training, Absentie, Periodeplan
│   │   ├── leerlijn.py           Leerlijn, LeerlijnStap, LeerlijnVoortgang
│   │   └── trainingsschema.py    Trainingsschema (training days), DAGEN
│   │
│   ├── atleten/                  ✅ everything around one athlete
│   │   ├── beheer.py             add, edit, search, (de)activate, delete; duplicate check
│   │   ├── koppelen.py           link imported results to an athlete (master_id)
│   │   ├── prestaties.py         manual entry, PR history, season bests, 12,93 / 1:58,21 notation
│   │   ├── testen.py             test results, progress over time
│   │   └── profiel.py            full athlete profile from personen, prestaties and testen
│   │
│   ├── wedstrijden/              ✅ planned meets
│   │   └── planning.py           plan a meet (date, name, location, link), register/deregister athletes
│   │                             per event, upcoming meets with participants; links normalised so the
│   │                             later results import finds the same meet
│   │
│   ├── importers/                📝 on this branch (see feature/importers)
│   │   ├── base.py               common interface: can_handle(url), parse(url)
│   │   ├── detect.py             picks the right importer automatically
│   │   ├── atletieknu_prs.py
│   │   ├── atletieknu_wedstrijd.py
│   │   └── seltec.py
│   │
│   ├── ploeg/                    📝 team selection
│   │   ├── vergelijk.py          compare PRs/performances across a group
│   │   ├── regels.py             loads rules from config/ploeg_regels/
│   │   ├── opstelling.py         lineup = athletes + rules + strategy
│   │   └── strategieen/          one file per "mentaliteit"
│   │
│   ├── groepen/
│   │   ├── groep.py              📝
│   │   ├── absentie.py           ✅ attendance list pre-filled from the training schedule, overview per athlete
│   │   └── periodeplan.py        📝
│   │
│   ├── leerlijnen/               📝
│   │
│   └── ui/                       📝 local web UI (Flask or FastAPI, not yet chosen)
│       ├── app.py
│       ├── templates/
│       └── static/
│
└── tests/                        fake data only; run with `python tests/test_<naam>.py`
    ├── test_models.py            ✅ 12 tests
    ├── test_queries.py           ✅ 17 tests (real encrypted databases in a temp folder)
    ├── test_atleten.py           ✅ 7 tests
    ├── test_absentie.py          ✅ 3 tests
    ├── test_wedstrijden.py       ✅ 5 tests
    ├── test_importers.py         📝 on this branch
    ├── test_opstelling.py        📝
    └── fixtures/                 saved, anonymised atletiek.nu/Seltec pages
```

---

## The five databases

The data is split over five encrypted files (SQLCipher). Only `personen.db` contains names; in the other four an athlete appears under a pseudonym that differs per database.

| File | Contents | Athlete identified by |
|------|----------|-----------------------|
| `personen.db` | athletes, groups, trainings, period plans, leerlijnen, ploegen | `master_id` |
| `prestaties.db` | onderdelen, wedstrijden (planned and past), prestaties, inschrijvingen (who goes to which meet, per event), `pr` view | pseudonym |
| `testen.db` | tests and test results | pseudonym |
| `trainingsschema.db` | per athlete, one column per weekday (`maandag` … `zondag`, 0/1): on which days they train | pseudonym |
| `absentie.db` | attendance in long format: one row per athlete per training, status `aanwezig` / `afgemeld` / `afwezig` / `blessure` | pseudonym |

```
python src/db/init_db.py                      # create/update data/*.db (also runs new migrations)
python src/db/init_db.py --herstelsleutel     # show the recovery key (keep it safe!)
python src/db/init_db.py --herstel <sleutel>  # restore the key on a new computer
```

Schema versions: `personen` 2 · `prestaties` 2 · `testen` 1 · `trainingsschema` 1 · `absentie` 1.

Absence used to live in `personen.db`. Because `blessure` is health data, it moved to its own pseudonymised file. On an existing installation `init_db.py` moves the old rows automatically, once (`personen` migration 002).

### When does a performance count as a PR?

| Event | Outdoor | Indoor |
|-------|---------|--------|
| Sprint and hurdles up to and including 200 m, long jump, triple jump | only with a wind reading of at most +2.0 | always |
| Everything else | always | always |

Which events are wind-measured is stored per event (`onderdeel.windmeting`) and can be changed by hand.
A competition marked `indoor` passes that on to all its performances.

---

## How the layers fit together

```
ui/  ──►  atleten/ · wedstrijden/ · ploeg/ · groepen/ · leerlijnen/ · importers/
                              │
                              ▼
                     db/queries.py  (Opslag)  ──►  personen.db · prestaties.db · testen.db · trainingsschema.db · absentie.db
                              │
                         models/ (shared dataclasses)
```

- The UI never runs SQL. It calls the feature modules, and they go through `Opslag`.
- Outside `db/`, an athlete is always a `master_id`. Pseudonyms stay inside `db/`.
- Importers deliver `Prestatie` objects with temporary `bron_*` fields. `atleten/koppelen.py` finds the athlete; after linking those fields are wiped, so no name reaches `prestaties.db`.
- Lineup rules live in `config/`, not in code, so team leaders can change them without programming.

---

## Open items

- [ ] Mark existing indoor competitions as `indoor` (existing ones all default to outdoor).
- [ ] Importers: fill `bron_naam` / `bron_atletieknu_id` / `bron_geboortejaar` / `bron_club`, set `Wedstrijd.indoor`, and use `atleten/koppelen.py`. Save meets with `wedstrijden.planning.normaliseer_link()` so results land on the planned meet.
- [ ] Merge `feature/importers` and `feature/atleten` into `dev`.
- [ ] `pyproject.toml`: replace the placeholder text with a real config (dependencies: `sqlcipher3-wheels`, `keyring`, …).
- [ ] `src/db/schema.sql`: remove it; it has been replaced by the five `schema_*.sql` files.
- [ ] Model + queries for `ploeg` / `ploeg_opstelling` (tables exist, no model yet).
- [x] Use the training schedule to pre-fill attendance lists (`groepen/absentie.py`).
- [ ] Show the training schedule and attendance overview in `atleten/profiel.py`.
- [ ] `build.py`: PyInstaller command (remember `--hidden-import keyring.backends.Windows`).
- [ ] Choose a UI framework (Flask or FastAPI) and a test runner (the tests are written so pytest can run them too).

### Build order

1. ✅ `db` (incl. `queries.py`)
2. ✅ `models` + `atleten`
3. `importers` (in progress)
4. `ploeg`
5. `groepen` / `leerlijnen`
6. `ui` + `build.py`
