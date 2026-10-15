AVS/
├── README.md
├── pyproject.toml            # dependencies + project metadata
├── .gitignore                # data/, *.db, *.sqlite, dist/, build/
├── build.py                  # the "one command" → PyInstaller → AVS.exe
├── docs/
│   └── Structuur.md
├── config/
│   └── ploeg_regels/         # lineup rules as YAML/JSON, editable by the team leader
│       ├── standaard.yaml
│       └── competitie_u16.yaml
├── data/                     # gitignored, the real database lives here
├── src/avs/
│   ├── __main__.py           # starts the app and opens the browser
│   ├── db/
│   │   ├── schema.sql        # schema IS in git, data is not
│   │   ├── init_db.py        # creates an empty database on first run
│   │   ├── migrations/       # 001_init.sql, 002_add_leerlijnen.sql, ...
│   │   └── queries.py        # all SQL in one place
│   ├── models/               # dataclasses: Atleet, Prestatie, Groep, Leerlijn...
│   ├── importers/
│   │   ├── base.py           # common interface: can_handle(url), parse(url)
│   │   ├── detect.py         # automatic detection: tries each importer
│   │   ├── atletieknu_prs.py
│   │   ├── atletieknu_wedstrijd.py
│   │   └── seltec.py
│   ├── atleten/              # personal data, PRs, test results, specialisation
│   ├── ploeg/
│   │   ├── vergelijk.py      # compare PRs/performances across a group
│   │   ├── regels.py         # loads rules from config/
│   │   ├── opstelling.py     # builds a lineup from athletes + rules + strategy
│   │   └── strategieen/      # one file per "mentaliteit" (max points, depth, ...)
│   ├── groepen/
│   │   ├── groep.py
│   │   ├── absentie.py
│   │   └── periodeplan.py
│   ├── leerlijnen/
│   └── ui/
│       ├── app.py            # Flask/FastAPI routes
│       ├── templates/
│       └── static/
└── tests/
    ├── fixtures/             # saved (anonymised!) atletiek.nu/seltec pages
    ├── test_importers.py
    └── test_opstelling.py