-- prestaties.db, migratie 004: doelen voor een groep of een atleet, meestal bij een wedstrijd.
--
-- Vervangt het doel van het oude periodeplan in personen.db: init_db.py zet de
-- oude periodeplannen hier over als doel zonder regels (titel = naam,
-- beschrijving = doel, datum = einddatum).
--
-- doel: wat willen we bereiken, en wanneer / bij welke wedstrijd.
--   groep_id verwijst naar personen.db: groep(id) (geen persoonsgegeven; SQLite
--   kan het tussen bestanden niet afdwingen, db/queries.py controleert het).
--   groep_id NULL = persoonlijk doel van één atleet.
--   datum NULL = de datum van de wedstrijd.
-- doel_regel: wat precies, en voor wie. atleet_ref = pseudoniem(master_id,
--   'prestaties'), zoals in prestatie; NULL = de hele groep.
--   soort 'prestatie': onderdeel + streefwaarde (seconden/meters/punten, zoals
--   prestatie.waarde; beter = onderdeel.lager_is_beter).
--   soort 'leerdoel': leerdoel_id (leerlijnen.db) + streefwaarde = score 1-5.
--   soort 'vrij': alleen een omschrijving.
--   Of een regel behaald is, rekent de app uit; beoordeling (met de hand) gaat voor.
--
-- titel, beschrijving, omschrijving en evaluatie zijn vrije tekst: feitelijk
-- houden, geen namen van andere atleten, geen diagnoses (zoals bij notities).

CREATE TABLE IF NOT EXISTS doel (
    id            INTEGER PRIMARY KEY,
    groep_id      INTEGER,
    titel         TEXT    NOT NULL,
    wedstrijd_id  INTEGER REFERENCES wedstrijd(id) ON DELETE SET NULL,
    startdatum    TEXT    NOT NULL DEFAULT (date('now')),
    datum         TEXT,
    beschrijving  TEXT,
    evaluatie     TEXT,
    aangemaakt_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS doel_regel (
    id           INTEGER PRIMARY KEY,
    doel_id      INTEGER NOT NULL REFERENCES doel(id) ON DELETE CASCADE,
    atleet_ref   TEXT    CHECK (atleet_ref IS NULL OR length(atleet_ref) = 32),
    soort        TEXT    NOT NULL CHECK (soort IN ('prestatie', 'leerdoel', 'vrij')),
    onderdeel_id INTEGER REFERENCES onderdeel(id),
    leerdoel_id  TEXT,
    streefwaarde REAL,
    omschrijving TEXT,
    beoordeling  TEXT    CHECK (beoordeling IN ('behaald', 'deels', 'niet')),
    CHECK (soort <> 'prestatie' OR (onderdeel_id IS NOT NULL AND streefwaarde IS NOT NULL)),
    CHECK (soort <> 'leerdoel'  OR (leerdoel_id  IS NOT NULL AND streefwaarde IS NOT NULL)),
    CHECK (soort <> 'vrij'      OR omschrijving IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_doel_groep      ON doel(groep_id);
CREATE INDEX IF NOT EXISTS idx_doel_regel_doel ON doel_regel(doel_id);
CREATE INDEX IF NOT EXISTS idx_doel_regel_atl  ON doel_regel(atleet_ref);
