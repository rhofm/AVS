-- personen.db, migratie 010: ploegopstellingen (zie docs/Ploegopstelling_ontwerp.md).
--
-- ploeg krijgt erbij:
--   categorie       ploeg in het regelbestand, bijv. 'U16-V'
--   programma       welke wedstrijd van de competitie, bijv. 'wedstrijd_2' of 'finale_2027'
--   datum           wedstrijddag 'YYYY-MM-DD' (ook zonder gekoppelde wedstrijd; voor de
--                   categorie van de atleten en 'één ploeg per dag')
--   prestatiebasis  'seizoen' (huidig + vorig seizoen), 'pr' of '12mnd'
--   (regelset = bestandsnaam in config/ploeg_regels/, competitie = naam uit dat bestand)
--
-- ploeg_lid: wie op het inschrijfformulier staat, als deelnemer of reserve, en of de
--   atleet de hele dag of een dagdeel kan.
--
-- ploeg_opstelling wordt opnieuw opgebouwd: een onderdeel is nu de programmasleutel
--   uit het regelbestand ('80mH', 'kogelstoten', '4x80m') in plaats van een onderdeel_id.
--   Welk onderdeel (met specificatie) dat bij de prestaties is, hangt af van de ploeg
--   en volgt uit het regelbestand. Een regel kan alleen bestaan voor een lid van de
--   ploeg (foreign key naar ploeg_lid). Wie in de oude tabel stond, wordt lid
--   (reserve als al zijn rijen reserve waren); de oude onderdeel_id's zijn niet om te
--   zetten naar programmasleutels en vervallen.
-- Persoonsgegevens: alleen master_id's, net als de rest van personen.db.

ALTER TABLE ploeg ADD COLUMN categorie TEXT;
ALTER TABLE ploeg ADD COLUMN programma TEXT;
ALTER TABLE ploeg ADD COLUMN datum TEXT;
ALTER TABLE ploeg ADD COLUMN prestatiebasis TEXT NOT NULL DEFAULT 'seizoen';

CREATE TABLE IF NOT EXISTS ploeg_lid (
    ploeg_id    INTEGER NOT NULL REFERENCES ploeg(id) ON DELETE CASCADE,
    atleet_id   TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    rol         TEXT    NOT NULL DEFAULT 'deelnemer' CHECK (rol IN ('deelnemer', 'reserve')),
    beschikbaar TEXT    NOT NULL DEFAULT 'hele_dag' CHECK (beschikbaar IN ('hele_dag', 'ochtend', 'middag')),
    PRIMARY KEY (ploeg_id, atleet_id)
);

INSERT OR IGNORE INTO ploeg_lid (ploeg_id, atleet_id, rol)
SELECT ploeg_id, atleet_id, CASE WHEN MIN(reserve) = 1 THEN 'reserve' ELSE 'deelnemer' END
FROM ploeg_opstelling
GROUP BY ploeg_id, atleet_id;

DROP TABLE ploeg_opstelling;

CREATE TABLE ploeg_opstelling (
    ploeg_id   INTEGER NOT NULL,
    atleet_id  TEXT    NOT NULL,
    onderdeel  TEXT    NOT NULL,                  -- programmasleutel uit het regelbestand
    groep      INTEGER CHECK (groep IS NULL OR groep >= 1),   -- groep bij een technisch onderdeel
    vast       INTEGER NOT NULL DEFAULT 0,        -- vastgezet door de trainer
    PRIMARY KEY (ploeg_id, atleet_id, onderdeel),
    FOREIGN KEY (ploeg_id, atleet_id) REFERENCES ploeg_lid (ploeg_id, atleet_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ploeg_datum ON ploeg (datum);
