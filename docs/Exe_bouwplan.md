# Bouwplan: AVS als .exe

A step-by-step plan for turning AVS into one Windows `.exe` that a trainer can start
by double-clicking: no terminal, no Python installed.

Written against the working copy on branch `feature/ploeg` (October 2026).
Do steps 1–4 on their own feature branch(es) and merge them into `dev` before the build steps.

| Step | What | Why |
|------|------|-----|
| 1 ✅ | Restore the key from Instellingen | Users without a terminal must be able to restore the recovery key |
| 2 ✅ | Package the database schemas | Without them the .exe crashes on first start |
| 3 ✅ | External config has priority, per file | Updates bring new YAML files without losing local edits |
| 4 ✅ | Move `standaard_map()` to `%LOCALAPPDATA%` | Data must be writable, wherever the .exe is |
| 5 | Pin dependencies in `pyproject.toml` | Reproducible environment for building |
| 6 | Add `__main__.py` options and a self-test | Lets `build.py` check the built .exe |
| 7 | Write `build.py` | One command → `dist/AVS.exe` |
| 8 | Test the frozen build by hand | Check the things a self-test can't cover |
| 9 | Release (optional) | Automatic build on `main` |

---

## Step 1 — "Sleutel herstellen" on the Instellingen page ✅ done

**Goal:** a button **Sleutel herstellen** on `/instellingen`. Clicking it shows a box where
the user pastes the recovery key. After a successful restore the app works again without a restart.

### 1a. Let the Instellingen page work when AVS can't start

This is the main point to get right. Right now `maak_app()` blocks **every** page (except
static files) with `fout.html` when `startfout` is set. That is exactly the case where the user
needs to restore the key. Changes in `src/ui/app.py`:

- Store the error in `app.config["AVS_STARTFOUT"]` instead of the closure variable `startfout`,
  so the restore route can clear it.
- `controleer_start()`: let through `static`, `instellingen_pagina`, `instellingen_opslaan`
  and the new `sleutel_herstellen` endpoint.
- `trainingen_klaarzetten()` opens the databases. Skip it while `AVS_STARTFOUT` is set, or it
  raises `SleutelFout` before the page renders.
- `fout.html`: when the error is a key problem, add a link **Sleutel herstellen →**
  (`/instellingen#sleutel`) instead of only "Naar atleten". Pass a flag such as
  `sleutelfout=True` from `controleer_start()`.

### 1b. The route

```
POST /instellingen/sleutel   →  endpoint "sleutel_herstellen"
```

1. Read `request.form["herstelsleutel"]`, strip spaces and line breaks (people copy it out of
   e-mails or notes; allow spaces between groups).
2. Call `db.init_db.herstel(sleutel)`. It already validates the key (64 hex characters) and
   **refuses to overwrite a different key**. Keep that check: it is what protects existing data.
3. Then call `init_db(app.config["AVS_MAP"])`. Here it opens the existing databases with the
   restored key:
   - succeeds → `app.config["AVS_STARTFOUT"] = None`, `flash("Sleutel hersteld. AVS werkt weer.")`,
     redirect to `/instellingen`.
   - `SleutelFout` (key doesn't fit the databases) → remove the key just written again (only
     if no key existed before the call), and show a clear error: "Deze sleutel past niet bij
     de databases op deze computer."
4. Errors from `herstel()` are shown in the page's `fout` box, status 400.

**Privacy rules (from CLAUDE.md):**
- Never echo the submitted key back into the page, not even on error. The box comes back empty.
- Never `print`/log the key or `request.form`.
- Response header `Cache-Control: no-store`.
- Input field: `type="password"`, `autocomplete="off"`, `spellcheck="false"`.
- The server only listens on 127.0.0.1. Still, check that `request.origin`/`Referer`
  is the app itself before accepting the POST. Any website open in the same browser could
  otherwise post a form to `127.0.0.1:5050`. That attack is low-risk because `herstel()` never
  overwrites, but the check is a few lines.

### 1c. Template (`instellingen.html`)

A separate block **under** the existing settings form, with its own `<form>` (not nested):

```html
<section id="sleutel" class="blok">
  <h2 class="kop">Sleutel</h2>
  <p>Nieuwe computer of Windows opnieuw geïnstalleerd? Zet hier je herstelsleutel terug.</p>
  <details {% if sleutel_open %}open{% endif %}>
    <summary class="knop">Sleutel herstellen</summary>
    <form method="post" action="{{ url_for('sleutel_herstellen') }}">
      <label for="herstelsleutel">Herstelsleutel</label>
      <input id="herstelsleutel" name="herstelsleutel" type="password"
             autocomplete="off" spellcheck="false" required>
      <button type="submit" class="knop">Herstellen</button>
    </form>
  </details>
</section>
```

`<details>`/`<summary>` gives "button opens a box" without JavaScript. Open it automatically
(`sleutel_open=True`) when AVS couldn't start because of the key, or after a failed attempt.

### 1d. Messages that point to the terminal

Replace the text `python src/db/init_db.py --herstel <sleutel>` in:
- `hoofdsleutel()` and `init_db()` in `src/db/init_db.py`
- `start()` in `src/ui/app.py`

with: "Zet de herstelsleutel terug via Instellingen → Sleutel herstellen."
The `--herstel` command line in `init_db.py` stays for development.

### 1e. Tests (`tests/test_instellingen.py`)

Never use the real keyring: monkeypatch `init_db._lees_hoofdsleutel` and
`init_db._bewaar_hoofdsleutel` to a dict in memory, and use `maak_app(map=tmp_path, ...)`.

- With a key error, `/instellingen` shows the page, and `/atleten` still shows the error page.
- Correct key → saved, `AVS_STARTFOUT` cleared, `/atleten` works.
- Wrong format → error, nothing saved.
- Valid format but doesn't fit the databases → error, nothing left in the keyring.
- Different key already present → refused, existing key unchanged.
- The submitted key never appears in any response body.

---

## Step 2 — Package the database schemas ✅ done

The SQL files are read from `SQL_DIR` (`init_db._sql_map()`): `src/db/` from source,
`sys._MEIPASS/db` in the .exe. The `--add-data` lines in step 7 put them there:
`src/db/schema_*.sql → db` and `src/db/migrations → db/migrations`. Use `schema_*.sql`, not
`*.sql`: the old `src/db/schema.sql` is not used.

Two safety checks, both before any database is touched:
- `controleer_sql_bestanden()` (first thing in `init_db()`): every `schema_<database>.sql`
  exists and is not empty, `migrations/` exists, no empty or duplicate migrations.
  Otherwise `InstallatieFout` ("AVS is niet volledig geïnstalleerd …").
- `_controleer_versies()`: a database whose version is higher than the newest migration this
  AVS knows (an older .exe, or a build without migrations) → `InstallatieFout`, before
  anything is migrated.

`app.start()` shows an `InstallatieFout` on the error page without the "Sleutel herstellen"
button. Checked with a real PyInstaller build: with the two `--add-data` lines all databases
and migrations are created; without `migrations/` the build stops with the error.
The self-test in step 6 calls `controleer_sql_bestanden()`.

---

## Step 3 — External config has priority, per file ✅ done

**Now:** `config_map()` takes the whole `config/` folder next to the .exe if it exists, otherwise
the built-in copy. After an update, new YAML files inside the .exe are never seen.

**New:** resolve **per file**. Search order:
1. `config/` next to the .exe (what a team leader edited), then
2. the copy built into the .exe (`sys._MEIPASS/config`).

From source there is only one folder (`config/` in the repo), so nothing changes there.

### Changes in `src/ploeg/config.py`

```python
def config_mappen() -> list[Path]:
    """Folders to search, highest priority first."""

def config_bestand(*delen: str) -> Path:
    """The first existing, non-empty file, e.g. config_bestand("ploeg_regels", "masters_2026-2027.yaml")."""

def config_bestanden(submap: str, patroon: str = "*.yaml") -> list[Path]:
    """All files from all folders, combined by name; the external file wins."""
```

- An **empty** external file (the 34-byte placeholders such as `standaard.yaml`) does not win:
  fall back to the built-in one. Otherwise a leftover placeholder would hide a real rule file.
- Keep `config_map()` for backward compatibility (returns the first folder), but stop using
  it for lookups.

### Callers

- `ploeg/regels.py`: `_map()` + `glob("*.yaml")` in the list function → `config_bestanden("ploeg_regels")`;
  loading one rule file → `config_bestand("ploeg_regels", f"{naam}.yaml")`.
  An explicit `map` argument (tests) keeps working as it does now.
- `ploeg/punten.py`: `_laad(uitgave, map)` and `_laad_factoren(naam, map)` currently get a
  folder. Pass the resolved file instead, and add its modification time to the cache key (as
  `regels._laad` already does), so an edited points file is picked up without a restart.
- The `puntentelling:` reference in a rule file is resolved the same way, so an external
  rule file can use a points table that only exists in the built-in copy.

**Built** as described above (`tests/test_config_voorrang.py`), and checked with a real
PyInstaller build: an edited `masters_2026-2027.yaml` and a new rule file in `config/` next to
the program are used; the other rule files and the points table come from the built-in copy.
Points files are now also cached by modification time (like rule files).

### Tests
- An external file overrides the built-in one with the same name.
- A new file that only exists in the built-in copy is found.
- An empty external file doesn't hide a built-in one.
- The list of rule files has no duplicates.
(Simulate frozen with `monkeypatch.setattr(sys, "frozen", True, raising=False)`, `sys._MEIPASS`
and `sys.executable` pointing into `tmp_path`.)

---

## Step 4 — Move `standaard_map()` ✅ done

**New location for the .exe:** `%LOCALAPPDATA%\AVS\data`
(e.g. `C:\Users\<naam>\AppData\Local\AVS\data`). It's always writable, belongs to the
Windows user (like the keyring key), and doesn't move when the .exe moves.

```python
def standaard_map() -> Path:
    eigen = os.environ.get("AVS_DATA")              # override, for testing and special cases
    if eigen:
        return Path(eigen)
    if getattr(sys, "frozen", False):
        basis = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return basis / "AVS" / "data"
    return DB_DIR.parents[1] / "data"               # from source: data/ in the repo, as now
```

- Running from source stays as it is, so development and tests don't change.
- `instellingen.json` moves along automatically (`instellingen._pad()` uses `standaard_map()`).

### One-time move of existing data

You have real data in the repo's `data/` folder. The first time the .exe starts, its data
folder is empty. Then `init_db()` would create **new empty databases** with the existing
keyring key, which looks like all data is gone.

- In `start()` (frozen only): when `standaard_map()` holds no `*.db` files but a `data/` folder
  next to the .exe does, **copy** (not move) `*.db` and `instellingen.json` from there and
  report it in the console. Never overwrite existing files.
- For your own move from the repo: copy `data\*.db` and `data\instellingen.json` once to
  `%LOCALAPPDATA%\AVS\data` by hand. That works because the key is the same (same Windows user,
  same keyring).
- Show the data folder on the Instellingen page (read-only text: "Je gegevens staan in …"),
  so a user knows what to back up.

**Built** as described (`tests/test_datamap.py`). The copy is all-or-nothing: files go to a
temporary folder first and are only then put in place; if anything fails, `OvernameFout`
is shown on the error page and `init_db()` does not run (so no empty databases appear).
The old folder is never changed. Checked with a real PyInstaller build in a "Program Files"
folder: the first start copies the 8 databases, the second start copies nothing.

### Tests
- Frozen + `LOCALAPPDATA` in `tmp_path` → `standaard_map()` is `…/AVS/data`.
- `AVS_DATA` wins over everything.
- The copy step copies when the target is empty and never overwrites.

---

## Step 5 — `pyproject.toml`

Replace the placeholder. Plain `pyproject.toml` dependencies, installed into the
`atletiek` conda environment with `pip install -e .[dev]`.

```toml
[project]
name = "avs"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
  "flask",
  "sqlcipher3-wheels",
  "keyring",
  "requests",
  "curl_cffi",
  "beautifulsoup4",
  "pyyaml",
  "numpy",
  "scipy",
  "fpdf2",
]

[project.optional-dependencies]
dev = ["pytest", "pyinstaller>=6"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Pin exact versions (`==`) once the first build works, so a later build gives the same .exe.
This list is based on part of the modules. PyInstaller's `warn-AVS.txt` (step 7) shows what's missing.

---

## Step 6 — `src/__main__.py`: options and self-test

```
AVS.exe                 start the server and open the browser (as now)
AVS.exe --geen-browser  start without opening the browser
AVS.exe --zelftest      check the build and stop (exit code 0/1)
```

`--zelftest` must **not** touch the keyring or the data folder. It checks that:
- every module in `src/` imports (including `scipy.optimize`, `curl_cffi`, `fpdf`, `sqlcipher3`,
  `keyring.backends.Windows`)
- `ui/templates` and `ui/static` exist in `_MEIPASS`
- every `schema_*.sql` and the migrations exist (step 2)
- `config_bestanden("ploeg_regels")` and `config_bestand("puntentelling", "au_2025.yaml")` are found (step 3)
- an SQLCipher database with a test key can be created, written and read in a temp folder

---

## Step 7 — `build.py`

One command: `python build.py`. It:

1. runs `pytest` and stops on failure
2. removes `build/` and `dist/`
3. runs PyInstaller from Python (`PyInstaller.__main__.run([...])`), with `sep = os.pathsep`:

```
src/__main__.py --name AVS --onefile --console --noconfirm --clean
--paths src
--add-data src/ui/templates{sep}ui/templates
--add-data src/ui/static{sep}ui/static
--add-data src/db/schema_*.sql{sep}db
--add-data src/db/migrations{sep}db/migrations
--add-data config{sep}config
--hidden-import keyring.backends.Windows
--collect-all curl_cffi
--collect-binaries sqlcipher3
--icon assets/avs.ico            (optional)
```

4. runs `dist/AVS.exe --zelftest` and fails the build if it doesn't return 0
5. prints the path and size of the .exe

**Never** add `data/`, `tests/` or `.git` (athlete privacy). `build/`, `dist/` and `*.spec`
are already in `.gitignore`.

Choices for now:
- `--console`: the console window is the way to stop AVS ("sluit dit venster om te stoppen").
  Switch to `--windowed` only after adding another way to stop (tray icon, a "Stoppen" button,
  or stopping automatically when the browser tab closes).
- `--onefile`: one file, as the README asks. Expect roughly 80–120 MB (scipy) and a few seconds
  to start. If start-up is too slow, use `--onedir` and ship it as a zip.

After the first build, read `build/AVS/warn-AVS.txt` and add `--hidden-import` lines for
anything missing.

---

## Step 8 — Test by hand on a clean Windows account

- [ ] Double-click `AVS.exe` → console opens, browser opens on the start page
- [ ] First start: key created, databases in `%LOCALAPPDATA%\AVS\data`
- [ ] Restart: same data, no new key
- [ ] Delete the key from Windows Credential Manager → error page with a "Sleutel herstellen" link → restore works (step 1)
- [ ] Import from atletiek.nu (uses curl_cffi) and from Seltec
- [ ] Optimise a ploeg (uses scipy)
- [ ] Export a training as PDF (uses fpdf2)
- [ ] Put an edited `config\ploeg_regels\*.yaml` next to the .exe → it is used, other built-in files are still found (step 3)
- [ ] .exe in a folder without write access → still works (step 4)
- [ ] SmartScreen: "Onbekende uitgever" → *Meer informatie → Toch uitvoeren* (expected without code signing)

---

## Step 9 — Release (optional)

A GitHub Actions workflow on `windows-latest` that runs on a version tag on `main`:
install Python 3.13 → `pip install -e .[dev]` → `python build.py` → attach `dist/AVS.exe`
to a GitHub Release.

Updating for users: replace `AVS.exe`. Their data stays in `%LOCALAPPDATA%\AVS\data`, migrations
run on the next start, and their own `config\` edits keep priority (step 3).
