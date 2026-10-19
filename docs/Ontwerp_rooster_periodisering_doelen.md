# Design: Rooster, Periodisering & Doelen

Status: built. Periodisering (§2.1, §2.4, §3, §4), rooster (§2.2, §5) and doelen (§2.3, §6). Prestatiedoelen count wind-legal results only. Based on the requirements in
`Rooster_en_Periodisering.md` and the decisions of 2026-10-19:

1. The old `periodeplan` table makes way for the mega cycle; its purpose
   (goals for the group/athletes at specific events) moves to a new **Doelen** feature.
2. Rooster week numbers are **independent** of the meso cycle.
3. A mega cycle is shared by **copying** it to other groups, never by linking.

---

## 1. One rule: "valid from"

Rooster, mega cycle and meso cycle follow the same rule:

> A row has a start date and holds until the next row of the same kind (same group) starts.

- Only start dates are stored, so there are no end dates to keep in sync.
- Multiple occurrences per year (V1 twice, a new meso cycle in March) are just extra rows.
- Optional: a group without rows doesn't use the feature; the UI only shows an "instellen" button.
- Phase and meso week are **derived from the date**, never stored per training (like the `pr` view).

## 2. Storage

| What | Database | Why |
|---|---|---|
| Mega cycle, meso cycle, rooster | `personen.db` | No personal data, but real FKs to `groep` and `training` |
| Doelen | `prestaties.db` | Athlete as `atleet_ref`; real FKs to `onderdeel` and `wedstrijd`; "achieved" check joins `prestatie` on the same pseudonym |

### 2.1 personen.db — migration `007_periodisering.sql`

```sql
-- Mega cycle: one row per phase change.
CREATE TABLE groep_fase (
    groep_id   INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    startdatum TEXT    NOT NULL,                 -- holds until the next startdatum
    fase       TEXT    NOT NULL CHECK (fase IN ('V1', 'V2', 'WP', 'Rust', 'Geen')),
    PRIMARY KEY (groep_id, startdatum)
);
-- 'Geen' ends the periodisation (e.g. end of season); otherwise the last phase keeps going.

-- Meso cycle: repeats from startdatum until the next mesocyclus of the group.
CREATE TABLE mesocyclus (
    id           INTEGER PRIMARY KEY,
    groep_id     INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    startdatum   TEXT    NOT NULL,               -- first day of week 1, snapped to weekbegin()
    aantal_weken INTEGER NOT NULL CHECK (aantal_weken BETWEEN 1 AND 12),
    UNIQUE (groep_id, startdatum)
);
CREATE TABLE mesocyclus_week (
    mesocyclus_id INTEGER NOT NULL REFERENCES mesocyclus(id) ON DELETE CASCADE,
    weeknummer    INTEGER NOT NULL CHECK (weeknummer >= 1),
    naam          TEXT    NOT NULL,              -- 'Opbouw', 'Piek', 'Herstel'
    PRIMARY KEY (mesocyclus_id, weeknummer)
);

```

The old `periodeplan` table is **kept but emptied**, not renamed or dropped:
`training.periodeplan_id` has a foreign key to it, and SQLite refuses every
insert into `training` once that parent table is gone (checked while building).
`training.periodeplan_id` stays as a dead column; it is removed from
`Training`, `_TRAINING_VELDEN` and `_leeg()`.

### 2.2 personen.db — migration `008_rooster.sql`

```sql
-- A rooster is a template: reusable for several groups and next season.
CREATE TABLE rooster (
    id           INTEGER PRIMARY KEY,
    naam         TEXT    NOT NULL,
    aantal_weken INTEGER NOT NULL CHECK (aantal_weken >= 1)
);
CREATE TABLE rooster_regel (
    id           INTEGER PRIMARY KEY,
    rooster_id   INTEGER NOT NULL REFERENCES rooster(id) ON DELETE CASCADE,
    week         INTEGER NOT NULL CHECK (week >= 1),     -- 1..aantal_weken, own count (not meso)
    dag          TEXT    NOT NULL CHECK (dag IN ('maandag','dinsdag','woensdag','donderdag',
                                                 'vrijdag','zaterdag','zondag')),
    starttijd    TEXT,                                   -- NULL = the day's main time
    onderwerp TEXT, warming_up TEXT, kern_a TEXT, kern_b TEXT, cooling_down TEXT, notities TEXT,
    UNIQUE (rooster_id, week, dag, starttijd)
);
-- Which rooster a group follows from when.
CREATE TABLE groep_rooster (
    groep_id   INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    rooster_id INTEGER NOT NULL REFERENCES rooster(id) ON DELETE CASCADE,
    startdatum TEXT    NOT NULL,                         -- first day of rooster week 1
    herhalen   INTEGER NOT NULL DEFAULT 1 CHECK (herhalen IN (0, 1)),
    einddatum  TEXT,                                     -- optional hard stop
    PRIMARY KEY (groep_id, startdatum)
);
-- Where the content of a training came from. NULL = not (or no longer) from the rooster.
ALTER TABLE training ADD COLUMN rooster_regel_id INTEGER
    REFERENCES rooster_regel(id) ON DELETE SET NULL;
```

Note: UNIQUE with a NULL `starttijd` doesn't stop duplicates in SQLite; `Opslag` checks it.

### 2.3 prestaties.db — migration `004_doelen.sql`

```sql
-- A goal: for a group (groep_id) or personal (groep_id NULL), usually tied to a meet.
CREATE TABLE doel (
    id            INTEGER PRIMARY KEY,
    groep_id      INTEGER,                    -- personen.db: groep(id); NULL = personal goal
    titel         TEXT    NOT NULL,           -- 'NK U16 indoor', 'Competitiefinale'
    wedstrijd_id  INTEGER REFERENCES wedstrijd(id) ON DELETE SET NULL,
    startdatum    TEXT    NOT NULL DEFAULT (date('now')),   -- results count from here
    datum         TEXT,                       -- target date; NULL = date of the wedstrijd
    beschrijving  TEXT,
    evaluatie     TEXT,                       -- looking back afterwards
    aangemaakt_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- What exactly has to be achieved, and by whom.
CREATE TABLE doel_regel (
    id           INTEGER PRIMARY KEY,
    doel_id      INTEGER NOT NULL REFERENCES doel(id) ON DELETE CASCADE,
    atleet_ref   TEXT CHECK (atleet_ref IS NULL OR length(atleet_ref) = 32),  -- NULL = the whole group
    soort        TEXT NOT NULL CHECK (soort IN ('prestatie', 'leerdoel', 'vrij')),
    onderdeel_id INTEGER REFERENCES onderdeel(id),
    leerdoel_id  TEXT,                        -- leerlijnen.db: leerdoel(id), e.g. 'SPR-U14-03'
    streefwaarde REAL,                        -- seconds/metres/points, or score 1-5 for a leerdoel
    omschrijving TEXT,                        -- free text (always for 'vrij')
    beoordeling  TEXT CHECK (beoordeling IN ('behaald', 'deels', 'niet')),  -- NULL = automatic/open
    CHECK (soort <> 'prestatie' OR (onderdeel_id IS NOT NULL AND streefwaarde IS NOT NULL)),
    CHECK (soort <> 'leerdoel'  OR (leerdoel_id  IS NOT NULL AND streefwaarde IS NOT NULL)),
    CHECK (soort <> 'vrij'      OR omschrijving IS NOT NULL)
);
CREATE INDEX idx_doel_groep      ON doel(groep_id);
CREATE INDEX idx_doel_regel_doel ON doel_regel(doel_id);
CREATE INDEX idx_doel_regel_atl  ON doel_regel(atleet_ref);
```

Checked in Python (`Opslag`): a personal goal (`groep_id` NULL) only has rows
with an `atleet_ref`; `datum` or `wedstrijd_id` is required; `groep_id` and
`leerdoel_id` exist. When a meet is deleted, `Opslag` first copies its date into
`doel.datum` for goals with `datum` NULL.

### 2.4 Moving the old periodeplannen (`init_db._verplaats_periodeplannen`) — built

Like `_verplaats_absentie`: copy every row of `periodeplan` to `doel`
(`groep_id`, `titel` = naam, `beschrijving` = doel, `startdatum`,
`datum` = einddatum, no rows), then `DELETE FROM periodeplan` (which sets
`training.periodeplan_id` to NULL). Re-running never duplicates a goal.
The `doel`/`doel_regel` tables (prestaties migration 004) were added together
with the periodisering branch so this move has somewhere to go; the Doelen UI
follows in its own branch.

## 3. Derivation (pure functions, `models/`)

| What | Rule |
|---|---|
| Phase on a date | latest `groep_fase` with `startdatum <= datum`; 'Geen' or none = no phase |
| Meso week | latest `mesocyclus` with `startdatum <= datum`; `((datum - start).days // 7) % aantal_weken + 1` → name from `mesocyclus_week` |
| Rooster row | latest `groep_rooster` with `startdatum <= datum` (and `datum <= einddatum`); `w = (datum - start).days // 7`; if `herhalen = 0` and `w >= aantal_weken` → none; else week `w % aantal_weken + 1`, then match `(dag, starttijd)` (NULL starttijd = main time) |
| Goal row status | see §6.3 |

Phase labels/colours live in one Python constant `FASEN` (code → name, colour):
V1 = Algemene voorbereiding, V2 = Specifieke voorbereiding, WP = Wedstrijdperiode, Rust = Overgang/rust.

## 4. Mega and meso cycle — editing

- Page `/groep/<id>/periodisering` (button "Periodisering" on the group page; only "instellen" when empty).
- **Mega cycle**: a list of rows (phase dropdown + start date, "+ rij", remove). The whole list is saved
  at once (`Opslag.groep_fasen_opslaan(groep_id, rijen)` replaces all rows), like the training days.
- **Meso cycle**: list of cycles; per cycle start date (snapped to `instellingen.weekbegin()`) and
  number of weeks, which shows that many name fields (small JS; works without JS by a
  "weken bijwerken" submit).
- **Copy to other groups**: "Kopiëren naar…" with group checkboxes and per item a choice
  (mega cycle / meso cycles). Copying **replaces** the target's rows of that kind after a confirm
  page listing what will be overwritten. After copying the groups are independent.
- **Year view** on the group page: a horizontal band per phase (colour), meso week names below,
  goals (§6) as markers on their date, "vandaag" line.

## 5. Rooster

### 5.1 Linking to trainings: copy + provenance

- `trainingen_aanvullen()` creates trainings as before; for each new training it calls
  `rooster_toepassen()`, which copies onderwerp/texts from the matching row and sets
  `rooster_regel_id`.
- Also when a rooster is linked or changed: existing **future** trainings that are empty or still
  have a `rooster_regel_id` get (re)filled.
- `training_bewerken()`: if the content differs from the rooster row → `rooster_regel_id = NULL`
  ("afwijkend van rooster", with a "terugzetten naar rooster" button on the training page).
- Changing a rooster row updates future trainings that still point to it; past trainings never change.
- `_leeg()`: a training whose content comes only from the rooster (has `rooster_regel_id`, no
  variants, no attendance) counts as empty, so `trainingen_opruimen()` can still remove it.
- Variants (afwijkende trainingen) are never created from the rooster.

### 5.2 Editing

- Page `/groep/<id>/rooster`: choose/create rooster, start date, repeat on/off, end date; history of
  earlier links.
- Table week × training moment (the group's `momenten`); click a cell → same fields as
  `training_bewerken`. Cells on days the group doesn't train are shown greyed with a warning.
- "Nieuw rooster" / "Kopie maken" (templates are shared; editing a template used by more groups
  shows "wordt gebruikt door: …").

### 5.3 Import (CSV or pasted table)

- `/groep/<id>/rooster/importeren`: textarea (paste from Excel = tab-separated) **or** file upload.
  Delimiter `;` `,` or tab detected; header row required, column names case-insensitive.
- Columns: `week;dag;tijd;onderwerp;warming_up;kern_a;kern_b;cooling_down;notities`
  **or** `datum;tijd;…` — dates are converted to (week, dag) relative to the chosen start date
  (weekbegin of the earliest date by default); `aantal_weken` = span of the dates.
- Preview step (like "Uitslagen controleren"): parsed rows, warnings (unknown day, day without
  training, duplicate moment, text too long). Nothing is saved before confirming.
- "Download voorbeeld-CSV" link. Logic in `groepen/rooster.py`, no SQL there.

## 6. Doelen (replaces the purpose of periodeplan)

### 6.1 Concept

A **doel** is "what do we want to achieve, by when / at which meet", with one or more
**doel rows** saying exactly what and for whom:

| Example | doel | rows |
|---|---|---|
| Group goal at a meet | "Competitiefinale", wedstrijd = finale | per athlete: onderdeel + streefwaarde |
| Group target without athletes | "Ploeg ≥ 18 000 punten", wedstrijd | one row, `atleet_ref` NULL, soort 'vrij' |
| Development goal | "Horden techniek", datum = end of V2 | per athlete: soort 'leerdoel', `HRD-U14-02`, score ≥ 4 |
| Personal goal | (groep NULL) "NK U18", wedstrijd = NK | one row for that athlete: 800m ≤ 2:05.00 |

### 6.2 Editing

- **Group page → "Doelen"**: upcoming goals (date, title, meet, "3/7 behaald"); page
  `/groep/<id>/doelen` with komend / geweest.
- **New/edit goal**: title, meet (dropdown of planned meets → date taken over) or date, start date,
  description. Then rows:
  - "Vul aan vanuit inschrijvingen": one row per registered (athlete, onderdeel) of the chosen
    meet, with the athlete's current PR shown as reference → trainer only fills in target values.
  - Or per athlete/onderdeel by hand; leerdoel rows with a leerdoel picker filtered on category.
  - Target values typed like results ('12.45', '2:05.00', '5.20'), parsed with the existing
    prestatie parsing; direction from `onderdeel.lager_is_beter`.
- **Athlete page**: block "Doelen" with all his rows (from group goals and personal), status and,
  if achieved, the performance. "+ Persoonlijk doel".
- **Meet page**: next to the results, the target per athlete ("doel 12.50 → 12.38 ✓").
- **Afterwards**: per goal an evaluation text; per row an optional manual judgement
  (behaald / deels / niet) that overrides the automatic status.

### 6.3 Status of a row (derived, not stored)

1. `beoordeling` filled in → that.
2. `prestatie`: best result of that athlete on that onderdeel in the window
   (`wedstrijd_id` set → only that meet; else `startdatum`..target date) meets the target → **behaald**.
3. `leerdoel`: latest score in `leerdoelscores.db` ≤ target date is ≥ target → **behaald**
   (pseudonym of `leerdoelscores` computed in Python from the master_id).
4. Otherwise: target date in the past → **niet behaald**; else **open**.
5. Group row (`atleet_ref` NULL) without manual judgement → **open** / **te beoordelen**.

### 6.4 Privacy

- Athletes only as `atleet_ref` (`pseudoniem(master_id, "prestaties")`); `groep_id` is not
  personal data (same as `trainingskeuze`).
- `titel`, `beschrijving`, `omschrijving`, `evaluatie` are free text: same rule as notes —
  factual, no names of other athletes, no diagnoses. Never log them.

## 7. Code layout

| File | Contents |
|---|---|
| `models/periodisering.py` | `FASEN`, `Fase`, `Mesocyclus`, `fase_op()`, `mesoweek_op()` |
| `models/rooster.py` | `Rooster`, `RoosterRegel`, `GroepRooster`, `regel_op()` |
| `models/doel.py` | `Doel`, `DoelRegel`, `DOELSOORTEN`, status enum |
| `models/groep.py` | remove `Periodeplan`; `Training.periodeplan_id` → `rooster_regel_id` |
| `db/queries.py` | `groep_fasen[_opslaan]`, `mesocycli`, `mesocyclus_opslaan/verwijderen`, `rooster*`, `groep_rooster*`, `doel*`, `doelen_van_atleet`, `periodisering_kopieren` |
| `db/init_db.py` | `_verplaats_periodeplannen()` after the migrations |
| `groepen/periodeplan.py` | page data periodisering + year view + copy |
| `groepen/rooster.py` | CSV/paste parsing, preview, `rooster_toepassen()` |
| `groepen/doelen.py` | page data doelen, form, status computation |
| `groepen/trainingen.py`, `groepen/landingspagina.py` | show phase + meso week instead of periodeplan; `_leeg()` |
| `ui/app.py` + templates | `groep_periodisering.html`, `groep_rooster.html`, `rooster_importeren.html`, `groep_doelen.html`, `doel_bewerken.html`; blocks on group, training, athlete and meet pages |

## 8. Tests

- `test_periodisering.py`: phase boundaries (day before/on start), V1 twice a year, before the
  first row, 'Geen', meso repeat, new meso replaces the old, start snapped to weekbegin, copying
  replaces only the chosen kind.
- `test_rooster.py`: parsing `;` `,` tab, week/day and date columns, preview warnings, repeat
  on/off, einddatum, extra training times, fill on create, propagation only to linked future
  trainings, detach on edit, `_leeg()` with rooster content.
- `test_doelen.py`: status rules (lower/higher is better, window per meet vs dates, leerdoel
  score, manual override, overdue), prefill from registrations, personal goal validation,
  meet deletion keeps the date.
- `test_init_db`: periodeplan rows move to `doel` and the old table is dropped; re-run is safe.

## 9. Suggested build order (separate feature branches → dev)

1. `feature/periodisering`: migration 007 + move, models, page, year view, copy.
2. `feature/rooster`: migration 008, template + link, apply to trainings, editor, import.
3. `feature/doelen`: prestaties migration 004, pages, status, blocks on athlete/meet pages.
