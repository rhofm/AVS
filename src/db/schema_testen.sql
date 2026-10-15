-- Atleet Volg Systeem - testen.db, basisschema (versie 1)
-- Testen en testresultaten. Bevat GEEN namen of master_ids: een atleet staat
-- hier alleen als pseudoniem (atleet_ref), berekend met
-- pseudoniem(master_id, 'testen') uit init_db.py. Dat pseudoniem verschilt van
-- het pseudoniem in prestaties.db, zodat de twee bestanden niet te koppelen zijn.
-- Latere wijzigingen NIET hier, maar in migrations/testen/NNN_beschrijving.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test (
    id              INTEGER PRIMARY KEY,
    naam            TEXT NOT NULL UNIQUE,      -- bijv. '30m vliegend', 'Kogelstoten achterwaarts'
    eenheid         TEXT NOT NULL,
    lager_is_beter  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS testresultaat (
    id          INTEGER PRIMARY KEY,
    atleet_ref  TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    test_id     INTEGER NOT NULL REFERENCES test(id),
    datum       TEXT NOT NULL,
    waarde      REAL NOT NULL,
    notities    TEXT
);
CREATE INDEX IF NOT EXISTS idx_testresultaat_atleet ON testresultaat(atleet_ref, test_id);

INSERT INTO schema_version (versie) VALUES (1);
