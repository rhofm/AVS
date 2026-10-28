-- testen.db, migratie 002: testsjablonen met meerdere onderdelen en scores.
--
-- Een test kan nu uit meerdere onderdelen bestaan (bijv. hoogspringen staand + 30 m sprint),
-- met per onderdeel een score uit een formule en een totaalscore. De sjablonen zelf staan
-- als YAML-bestand in config/testen/ of in de map testsjablonen van de gegevensmap, niet in
-- de database: `test.sjabloon` is de bestandsnaam (zonder .yaml) waar de test bij hoort.
--
--   test.sjabloon                 NULL = een test van vóór de sjablonen (één waarde, geen onderdelen)
--   testresultaat.score           totaalscore (of de score van het ene onderdeel); NULL = geen score
--   testresultaat.waarde          blijft bestaan: de hoofdwaarde (totaalscore als die er is, anders de
--                                 meting van het eerste onderdeel), zodat 'beste' en 'vooruitgang' blijven werken
--   testresultaat_deel            per resultaat de meting (en score) van elk onderdeel, in de volgorde van
--                                 het sjabloon (deel 0, 1, ...). Wijzigt het aantal of de soort onderdelen in
--                                 een sjabloon nadat er resultaten zijn, dan weigert AVS dat (zie testen/resultaten.py)
--
-- Geen persoonsgegevens: de atleet blijft alleen een pseudoniem op testresultaat.

ALTER TABLE test ADD COLUMN sjabloon TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_test_sjabloon ON test(sjabloon) WHERE sjabloon IS NOT NULL;

ALTER TABLE testresultaat ADD COLUMN score REAL;

CREATE TABLE IF NOT EXISTS testresultaat_deel (
    resultaat_id INTEGER NOT NULL REFERENCES testresultaat(id) ON DELETE CASCADE,
    deel         INTEGER NOT NULL CHECK (deel >= 0),
    waarde       REAL    NOT NULL,
    score        REAL,
    PRIMARY KEY (resultaat_id, deel)
) WITHOUT ROWID;
