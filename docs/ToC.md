# Repo-overzicht — Atleet Volg Systeem (AVS)

What lives where in this repo, and how far along each part is.
For the features and ideas behind it, see [Structuur.md](Structuur.md); for coding rules, see [CLAUDE.md](../CLAUDE.md).

> **Snapshot:** branch `feature/database`, 15 October 2026.
> Other branches can differ. The importer code, for example, is being built on `feature/importers`, so on this branch those files are still placeholders.

**Legend**

| Mark | Meaning |
|------|---------|
| ✅ | Implemented |
| 📝 | Placeholder: only a docstring or `#This is an empty temporary file` |
| 🔒 | Git-ignored, never committed (privacy) |
| ⚠️ | Needs attention |

---

## Tree

```
AVS/
├── README.md                    ✅ features, ideas, git workflow
├── CLAUDE.md                    ✅ conventions, privacy rules, database design
├── pyproject.toml               📝⚠️ not valid TOML yet
├── build.py                     📝 the "one command" → PyInstaller → AVS.exe
├── .gitignore                   ✅ data/, databases, csv/xlsx, build output
│
├── docs/
│   ├── Structuur.md             ✅ features per area
│   └── ToC.md                   ✅ this file
│
├── config/
│   └── ploeg_regels/            lineup rules (YAML), editable by the team leader
│       ├── standaard.yaml       📝
│       └── competitie_u16.yaml  📝
│
├── data/                        🔒 the real databases and test data live here
│   ├── personen.db              🔒 created by init_db.py
│   ├── prestaties.db            🔒 created by init_db.py
│   ├── testen.db                🔒 created by init_db.py
│   ├── vervangingen.txt         🔒 real name → fake name, for anonymising fixtures
│   └── live_controle/           🔒 live checks of the importers against the real sites
│       ├── gevallen.txt         🔒 list of links to check
│       └── *.csv, diag_*.html   🔒 output of those checks
│
├── src/
│   ├── __main__.py              📝 starts the app and opens the browser
│   │
│   ├── db/
│   │   ├── init_db.py           ✅ keys, verbind(), create + migrate the 3 databases
│   │   ├── schema_personen.sql  ✅ v1 (frozen): athletes, groups, absence, leerlijnen, ploegen
│   │   ├── schema_prestaties.sql✅ v1 (frozen): onderdelen, wedstrijden, prestaties, pr view
│   │   ├── schema_testen.sql    ✅ v1 (frozen): tests, test results
│   │   ├── schema.sql           ⚠️ old single-database schema, no longer used
│   │   ├── queries.py           📝 all SQL in one place
│   │   └── migrations/          one subfolder per database, e.g. testen/002_….sql
│   │
│   ├── models/                  📝 dataclasses
│   │   ├── atleet.py
│   │   ├── prestatie.py
│   │   ├── groep.py
│   │   └── leerlijn.py
│   │
│   ├── importers/               📝 on this branch (see feature/importers)
│   │   ├── base.py              common interface: can_handle(url), parse(url)
│   │   ├── detect.py            picks the right importer automatically
│   │   ├── atletieknu_prs.py
│   │   ├── atletieknu_wedstrijd.py
│   │   └── seltec.py
│   │
│   ├── atleten/                 📝 personal data, PRs, test results, specialisation
│   │
│   ├── ploeg/                   📝 team selection
│   │   ├── vergelijk.py         compare PRs/performances across a group
│   │   ├── regels.py            loads rules from config/ploeg_regels/
│   │   ├── opstelling.py        lineup = athletes + rules + strategy
│   │   └── strategieen/         one file per "mentaliteit"
│   │
│   ├── groepen/                 📝
│   │   ├── groep.py
│   │   ├── absentie.py
│   │   └── periodeplan.py
│   │
│   ├── leerlijnen/              📝
│   │
│   └── ui/                      📝 local web UI (Flask or FastAPI, not yet chosen)
│       ├── app.py
│       ├── templates/
│       └── static/
│
└── tests/
    ├── fixtures/                saved, anonymised atletiek.nu/Seltec pages
    ├── test_importers.py        📝 on this branch
    └── test_opstelling.py       📝
```

---

## The three databases

The data is split over three encrypted files (SQLCipher). Only `personen.db` contains names; in the other two an athlete appears under a pseudonym that differs per database.

| File | Contents | Athlete identified by |
|------|----------|-----------------------|
| `personen.db` | athletes, groups, trainings, absence, period plans, leerlijnen, ploegen | `master_id` |
| `prestaties.db` | onderdelen, wedstrijden, prestaties, inschrijvingen, `pr` view | pseudonym |
| `testen.db` | tests and test results | pseudonym |

```
python src/db/init_db.py                      # create/update data/*.db
python src/db/init_db.py --herstelsleutel     # show the recovery key (keep it safe!)
python src/db/init_db.py --herstel <sleutel>  # restore the key on a new computer
```

---

## How the layers fit together

```
ui/  ──►  atleten/ · ploeg/ · groepen/ · leerlijnen/ · importers/  ──►  db/
                              │
                         models/ (shared dataclasses)
```

- The UI never runs SQL itself. It calls the feature modules, and they go through `db/`.
- Importers deliver `models` objects. Matching to an athlete happens in `personen.db`; the results go to `prestaties.db` under the pseudonym.
- Lineup rules live in `config/`, not in code, so team leaders can change them without programming.

---

## Open items

- [ ] `pyproject.toml`: replace the placeholder text with a real config (dependencies: `sqlcipher3-wheels`, `keyring`, …).
- [ ] `src/db/schema.sql`: remove it; it has been replaced by the three `schema_*.sql` files.
- [ ] `build.py`: PyInstaller command (remember `--hidden-import keyring.backends.Windows`).
- [ ] Choose a UI framework (Flask or FastAPI).
- [ ] Merge `feature/importers` into `dev`.

### Build order

1. ✅ `db`
2. `models` + `atleten`
3. `importers` (in progress)
4. `ploeg`
5. `groepen` / `leerlijnen`
6. `ui` + `build.py`
