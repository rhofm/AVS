-- Atleet Volg Systeem - testen.db, basisschema (versie 2)
-- Testen en testresultaten. Bevat GEEN namen of master_ids: een atleet staat
-- hier alleen als pseudoniem (atleet_ref), berekend met
-- pseudoniem(master_id, 'testen') uit init_db.py. Dat pseudoniem verschilt van
-- het pseudoniem in prestaties.db, zodat de twee bestanden niet te koppelen zijn.
--
-- Samengevoegd: dit is versie 1 + migratie 002, zodat een nieuwe installatie
-- niet alle oude stappen hoeft te doorlopen. Een database die ouder is dan
-- versie 2 kan deze AVS niet meer bijwerken (init_db.basisversie()).
-- De volgorde van de kolommen is gelijk aan die van een bijgewerkte database
-- (toegevoegde kolommen staan achteraan); houd dat zo.
-- Latere wijzigingen NIET hier, maar in migrations/testen/NNN_beschrijving.sql
-- (vanaf 003).
--
-- Een test kan uit meerdere onderdelen bestaan (bijv. hoogspringen staand + 30 m sprint),
-- met per onderdeel een score uit een formule en een totaalscore. De sjablonen zelf staan
-- als YAML-bestand in config/testen/ of in de map testsjablonen van de gegevensmap, niet in
-- de database: `test.sjabloon` is de bestandsnaam (zonder .yaml) waar de test bij hoort.
--
--   test.sjabloon                 NULL = een test van vóór de sjablonen (één waarde, geen onderdelen)
--   testresultaat.score           totaalscore (of de score van het ene onderdeel); NULL = geen score
--   testresultaat.waarde          de hoofdwaarde (totaalscore als die er is, anders de meting van
--                                 het eerste onderdeel), zodat 'beste' en 'vooruitgang' blijven werken
--   testresultaat_deel            per resultaat de meting (en score) van elk onderdeel, in de volgorde van
--                                 het sjabloon (deel 0, 1, ...). Wijzigt het aantal of de soort onderdelen in
--                                 een sjabloon nadat er resultaten zijn, dan weigert AVS dat (zie testen/resultaten.py)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test (
    id              INTEGER PRIMARY KEY,
    naam            TEXT NOT NULL UNIQUE,      -- bijv. '30m vliegend', 'Kogelstoten achterwaarts'
    eenheid         TEXT NOT NULL,
    lager_is_beter  INTEGER NOT NULL,
    sjabloon        TEXT                       -- slug van het YAML-sjabloon, zie boven
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_test_sjabloon ON test(sjabloon) WHERE sjabloon IS NOT NULL;

CREATE TABLE IF NOT EXISTS testresultaat (
    id          INTEGER PRIMARY KEY,
    atleet_ref  TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    test_id     INTEGER NOT NULL REFERENCES test(id),
    datum       TEXT NOT NULL,
    waarde      REAL NOT NULL,
    notities    TEXT,
    score       REAL
);
CREATE INDEX IF NOT EXISTS idx_testresultaat_atleet ON testresultaat(atleet_ref, test_id);

CREATE TABLE IF NOT EXISTS testresultaat_deel (
    resultaat_id INTEGER NOT NULL REFERENCES testresultaat(id) ON DELETE CASCADE,
    deel         INTEGER NOT NULL CHECK (deel >= 0),
    waarde       REAL    NOT NULL,
    score        REAL,
    PRIMARY KEY (resultaat_id, deel)
) WITHOUT ROWID;

INSERT INTO schema_version (versie) VALUES (2);
