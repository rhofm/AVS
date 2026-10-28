# Repo-overzicht — Atleet Volg Systeem (AVS)

What lives where in this repo, and how far along each part is.
For the features and ideas behind it, see [Structuur.md](Structuur.md); for coding rules, see [CLAUDE.md](../CLAUDE.md).

> **Snapshot:** branch `dev`, 28 October 2026 (GitHub `rhofm/AVS` and the local folder are the same).
> The feature branches (`feature/atleten`, `feature/importers`, `feature/ploeg`) are merged into `dev`. `staging` and `main` do not exist yet.

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
├── README.md                     ✅ features, ideas, install and run commands, git workflow
├── CLAUDE.md                     ✅ conventions, privacy rules, database design
├── pyproject.toml                ✅ dependencies (Python 3.13), `[dev]` = pytest + PyInstaller
├── build.py                      ✅ the "one command": tests → PyInstaller → content check → zelftest → dist/AVS.exe
├── .gitignore                    ✅ data/, databases, csv/xlsx, build output
│
├── docs/
│   ├── Structuur.md              ✅ features per area
│   ├── ToC.md                    ✅ this file
│   ├── Exe_bouwplan.md           ✅ plan for the .exe (steps 1-7 done; manual test list still open)
│   ├── Ploegopstelling_ontwerp.md ✅ design of the team feature
│   ├── Ontwerp_rooster_periodisering_doelen.md ✅ design of rooster, periodisering and doelen
│   ├── leerdoelen_overzicht.md   ✅ overview of the leerdoelen (the .csv version is git-ignored)
│
├── config/
│   ├── testen/                   ✅ shipped test templates (YAML); own ones go in <data folder>/testsjablonen/
│   ├── ploeg_regels/             lineup rules (YAML), editable by the team leader
│   │   ├── u14_u16_2026-2027.yaml        ✅
│   │   ├── u18_u20_2026-2027.yaml        ✅
│   │   ├── masters_2026-2027.yaml        ✅
│   │   ├── nk_teams_2026-2027.yaml       ✅
│   │   ├── senioren_1e_divisie_2026-2027.yaml ✅
│   │   ├── senioren_2e_divisie_2026-2027.yaml ✅
│   │   ├── senioren_3e_divisie_2026-2027.yaml ✅
│   │   ├── standaard.yaml        📝
│   │   └── competitie_u16.yaml   📝
│   └── puntentelling/            scoring constants, one file per edition
│       ├── au_2025.yaml          ✅ AU "Formules & Constanten"
│       └── masters_agegrading.yaml ⚠️ still empty: the age-grading factors have to come from the Atletiekunie tables
│
├── data/                         🔒 real databases and test data
│   ├── personen.db · prestaties.db · testen.db · trainingsschema.db · absentie.db ·
│   │   leerlijnen.db · leerdoelscores.db · notities.db     🔒 created by init_db.py
│   ├── vervangingen.txt          🔒 real name → fake name, for anonymising fixtures
│   └── live_controle/            🔒 live checks of the importers against the real sites
│
├── build/, dist/                 🔒 build output (AVS.exe, AVS-pakketten.txt); never committed
│
├── src/
│   ├── __main__.py               ✅ starts the app and opens the browser (`--geen-browser`, `--zelftest`)
│   ├── zelftest.py               ✅ `--zelftest`: checks that a build is complete (modules, SQL, templates, keyring, ...)
│   │
│   ├── db/
│   │   ├── init_db.py            ✅ keys, verbind(), create + migrate the 8 databases, recovery key, data folder
│   │   ├── queries.py            ✅ class Opslag: all SQL, models in → models out
│   │   ├── schema_<database>.sql ✅ v1 (frozen) for personen, prestaties, testen, trainingsschema, absentie,
│   │   │                            leerlijnen, leerdoelscores, notities
│   │   ├── schema.sql            ⚠️ old single-database schema, no longer used
│   │   └── migrations/
│   │       ├── personen/         002 absentie to own database · 004 groep_trainingstijden · 005 training parts and variants ·
│   │       │                     006 several trainings per day · 007 periodisering (+ old periodeplan → doelen) ·
│   │       │                     008 rooster · 009 AU licence number · 010 ploeg_opstelling · 011 preferences
│   │       │                     (there is no 003: two clashing 003s were replaced; init_db moves their data)
│   │       ├── testen/           002 sjablonen (test.sjabloon, testresultaat.score, testresultaat_deel)
│   │       ├── prestaties/       002 PR only wind-legal · 003 wedstrijd_programma (timetable) · 004 doelen
│   │       └── trainingsschema/  002 trainingskeuze (which training on a day with several)
│   │
│   ├── models/                   ✅ dataclasses, no SQL
│   │   ├── atleet.py · prestatie.py · groep.py · leerlijn.py · leerdoel.py · notitie.py
│   │   ├── programma.py          one timetable item
│   │   ├── trainingsschema.py    training days of an athlete
│   │   ├── periodisering.py      megacyclus + mesocyclus
│   │   ├── rooster.py            training-content template of N weeks
│   │   ├── doel.py               goals of a group or athlete
│   │   └── ploeg.py              Ploeg, PloegLid, Inzet
│   │
│   ├── atleten/                  ✅ everything around one athlete
│   │   ├── beheer.py · nieuw.py · aanpassen.py   add, edit, search, (de)activate, delete; duplicate check
│   │   ├── overzicht.py · landingspagina.py · profiel.py   athlete overview, landing page, full profile
│   │   ├── koppelen.py           link imported results to an athlete (master_id)
│   │   ├── prestaties.py         manual entry, PR history, season bests
│   │   ├── prs_importeren.py · importeer_atletieknu.py · atleet_toevoegen_atletieknu.py   PRs from atletiek.nu
│   │   ├── testen.py             test results, progress over time (also for template-based tests)
│   │   ├── trainingsschema.py    training days per athlete
│   │   ├── aanwezigheid.py       attendance of one athlete (list + month calendar)
│   │   └── notities.py           notes per athlete per date
│   │
│   ├── wedstrijden/              ✅ meets
│   │   ├── planning.py · kalender.py · overzicht.py · detail.py   plan, register, calendar, overview, meet page
│   │   ├── chronoloog.py         personal timetable, clashes / too little rest
│   │   ├── tijdschema_import.py  atletiek.nu or Seltec timetable → wedstrijd_programma
│   │   └── uitslag_import.py     results of a held meet → prestaties (trainer confirms name-only matches)
│   │
│   ├── importers/                ✅ scraping, one importer per site and kind of page
│   │   ├── base.py · detect.py   common interface (can_handle, parse) and automatic detection
│   │   ├── atletieknu_prs.py · atletieknu_wedstrijd.py · atletieknu_tijdschema.py
│   │   └── seltec.py · seltec_tijdschema.py
│   │
│   ├── ploeg/                    ✅ team selection
│   │   ├── punten.py             AU points per performance (constants from config/puntentelling/)
│   │   ├── regels.py · config.py rule files → Regelset, checks of a lineup, config lookup (source and .exe)
│   │   ├── vergelijk.py          matrix athletes × events
│   │   ├── voorspeller.py · estafettes.py   predicted performances, relays
│   │   ├── opstelling.py · optimaliseer.py · strategieen/   lineup, MILP optimiser, "mentaliteiten"
│   │   ├── tijdschema.py         clashes and day parts, technical-event groups
│   │   ├── voorkeuren.py         athlete preferences (wil niet / voorkeur / moet)
│   │   ├── inschrijven.py · export.py   sync with registrations, atletiek.nu CSV download
│   │   └── paginas.py            page data for the Ploegen pages (incl. several ploegen per day)
│   │
│   ├── groepen/                  ✅ groups
│   │   ├── groep.py · groepenoverzicht.py · landingspagina.py   groups, members, training times, weekly timetable
│   │   ├── groep_importeren.py · atleten_uit_csv.py   import a group from a table or CSV
│   │   ├── trainingen.py · absentie.py   trainings (parts, variants, automatic creation), attendance
│   │   ├── periodeplan.py        periodisering: mega/meso cycle, year view, copy
│   │   ├── rooster.py            planned training content: fill in, import, apply to trainings
│   │   ├── doelen.py             goals: status per line, forms
│   │   ├── leerdoelen_scoren.py  page 'Leerdoelen scoren': score a whole group on one leerdoel
│   │   ├── testen_invullen.py    page 'Testresultaten invullen': enter a test for a whole group (all-or-nothing, error per athlete)
│   │   └── overzichten.py        group tables: PRs, test results (parts + total), leerdoelen, attendance
│   │
│   ├── testen/                   ✅ test templates and results
│   │   ├── formule.py            safe formula engine (+ - * / ^, sqrt, parentheses; L/T/M and C1..Cn; no eval)
│   │   ├── sjabloon.py           Sjabloon/Onderdeel, YAML read/write, library (config/testen + <data>/testsjablonen)
│   │   ├── resultaten.py         record a result (values, scores, total), edit guard, delete, lines for the pages
│   │   └── editor.py             server-side state of the template form (rows, parameters, total checkbox)
│   │
│   ├── leerlijnen/               ✅
│   │   ├── voortgang.py          leerdoelen of one athlete with latest scores; saving scores
│   │   └── overzicht.py          page 'Leerlijnen': catalogue per onderdeel and/or category
│   │
│   ├── instellingen/             ✅ settings page: first weekday, theme, time notation, name order, data folder, recovery key
│   │
│   └── ui/                       ✅ local web UI (Flask)
│       ├── app.py                routes
│       ├── startpagina.py · importeren.py   start page and import page
│       ├── levensduur.py         AVS stops by itself when the last tab is closed
│       ├── export.py             training as markdown or PDF
│       ├── markdown.py · opmaak.py   safe markdown subset, Jinja filters
│       ├── templates/            ~60 pages
│       └── static/               avs.css, filter.js, sorteer.js, levend.js
│
└── tests/                        fake data only; run with `python -m pytest` (73 test files)
    ├── test_<feature>.py         one file per feature (models, queries, atleten, groepen, wedstrijden, importers,
    │                             ploegen, regels, punten, rooster, periodisering, doelen, build, zelftest, ...)
    ├── test_testen_*.py          formula engine, templates, results (incl. migration), editor and pages
    ├── test_groep_leerdoelen_scoren.py   scoring a whole group on a leerdoel
    ├── test_groep_testen_invullen.py     entering a test for a whole group
    ├── test_opstelling.py        📝 placeholder
    └── fixtures/                 saved, anonymised atletiek.nu/Seltec pages (profile, meet results, timetables)
```

---

## The eight databases

The data is split over eight encrypted files (SQLCipher). Only `personen.db` contains names; `leerlijnen.db` is a catalogue without personal data; in the other six an athlete appears under a pseudonym that differs per database. The files live in `data/` when run from source and in `%LOCALAPPDATA%\AVS\data` when frozen (`$AVS_DATA` overrides both).

| File | Contents | Athlete identified by |
|------|----------|-----------------------|
| `personen.db` | athletes, groups, training times, group members, trainings (parts, variants), periodisering, rooster, leerlijnen (old), ploegen (`ploeg`, `ploeg_lid`, `ploeg_opstelling`), preferences | `master_id` |
| `prestaties.db` | onderdelen, wedstrijden (planned and past), prestaties, inschrijvingen, timetables (`wedstrijd_programma`), goals (`doel`, `doel_regel`), `pr` view | pseudonym |
| `testen.db` | tests (with their template slug), results with per-part values and scores | pseudonym |
| `trainingsschema.db` | training days per athlete, `trainingskeuze` | pseudonym |
| `absentie.db` | attendance in long format: `aanwezig` / `afgemeld` / `afwezig` / `blessure` | pseudonym |
| `leerlijnen.db` | catalogue: leerlijnen, leerdoelen (U10–U20, 215 goals), score scale. No personal data | — |
| `leerdoelscores.db` | score 1–5 per athlete per leerdoel per date | pseudonym |
| `notities.db` | free-text notes per athlete per date | pseudonym |

```
python src/db/init_db.py                      # create/update data/*.db (also runs new migrations)
python src/db/init_db.py --herstelsleutel     # show the recovery key (keep it safe!)
python src/db/init_db.py --herstel <sleutel>  # restore the key on a new computer
```

The recovery key can also be shown and restored on the **Instellingen** page, so the `.exe` needs no terminal.

Schema versions: `personen` 11 · `prestaties` 4 · `testen` 2 · `trainingsschema` 2 · `absentie` 1 · `leerlijnen` 1 · `leerdoelscores` 1 · `notities` 1.

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
ui/  ──►  atleten/ · wedstrijden/ · ploeg/ · groepen/ · leerlijnen/ · importers/ · instellingen/
                              │
                              ▼
                     db/queries.py  (Opslag)  ──►  the eight databases
                              │
                         models/ (shared dataclasses)
```

- The UI never runs SQL. It calls the feature modules, and they go through `Opslag`.
- Outside `db/`, an athlete is always a `master_id`. Pseudonyms stay inside `db/`.
- Importers deliver `Prestatie` objects with temporary `bron_*` fields. `atleten/koppelen.py` finds the athlete; after linking those fields are wiped, so no name reaches `prestaties.db`.
- Lineup rules and scoring constants live in `config/`, not in code, so team leaders can change them without programming. Next to the `.exe`, a `config/` folder takes priority over the copy built in.

---

## Open items

- [ ] Fill in the masters age-grading factors in `config/puntentelling/masters_agegrading.yaml` (from the Atletiekunie tables; never invent them).
- [x] Entry form for test results, based on YAML test templates (`testen/`, pages 'Testsjablonen' and 'Testresultaat').
- [x] Enter test results for a whole group in one go (`groepen/testen_invullen.py`).
- [ ] Progress chart per test.
- [x] Score a whole group on a leerdoel in one go.
- [ ] Progress chart per athlete.
- [ ] Run the manual `.exe` checklist in `docs/Exe_bouwplan.md` (first start, key recovery, imports, optimiser, PDF, edited config, no write access, SmartScreen).
- [ ] Fill or remove the placeholders `config/ploeg_regels/standaard.yaml` and `competitie_u16.yaml`.
- [ ] Timetable: add or delete rows by hand; upload a saved page when atletiek.nu blocks the import.
- [ ] Mark existing indoor competitions as `indoor` (existing ones all default to outdoor).
- [ ] Refine the predictor defaults (`voorspelling_factor`, `verhouding`, `correctie_s`) with real data.
- [ ] `src/db/schema.sql`: remove it; it has been replaced by the eight `schema_*.sql` files.
- [ ] Create `staging` and `main` branches when the app is ready for trainers.
- [x] Importers, ploeg, groepen, leerlijnen, UI (Flask), settings page, `pyproject.toml`, `build.py` and `__main__.py`.
- [x] Training schedule pre-fills attendance lists; weekly timetable on the athlete page; training content form.
- [x] Periodisering, rooster and doelen; athlete preferences; several ploegen on one day.

### Build order

1. ✅ `db` (incl. `queries.py`)
2. ✅ `models` + `atleten`
3. ✅ `importers`
4. ✅ `ploeg`
5. ✅ `groepen` / `leerlijnen`
6. ✅ `ui` + `build.py`
7. Testing the `.exe` by hand, then `staging` → `main`
