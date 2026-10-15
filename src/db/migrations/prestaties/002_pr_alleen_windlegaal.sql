-- prestaties.db, migratie 002: PR's alleen uit windlegale prestaties.
--
-- Regels (World Athletics):
--   * Bij onderdelen MET windmeting telt een prestatie alleen als PR als de
--     wind gemeten is en hoogstens +2,0 m/s was; zonder windmeting telt hij
--     dus niet. Windmeting hebben: sprints t/m 200 m, horden t/m 200 m,
--     verspringen en hinkstapspringen.
--   * Bij alle andere onderdelen telt elke prestatie (een eventuele
--     windwaarde wordt genegeerd).
--   * Indoor wordt geen wind gemeten: een indoorprestatie telt altijd.
--     Een wedstrijd kan als indoor gemarkeerd worden; de prestaties op die
--     wedstrijd nemen dat over (db/queries.py regelt dat). Bestaande
--     wedstrijden staan op outdoor; markeer indoorwedstrijden zelf.
--
-- Vervangt de view `pr` uit versie 1. Er gaan geen prestaties verloren.
-- init_db.py voert dit uit en zet schema_version op 2.

-- 1. Nieuwe kolommen ------------------------------------------------------
ALTER TABLE onderdeel ADD COLUMN windmeting INTEGER NOT NULL DEFAULT 0;
ALTER TABLE wedstrijd ADD COLUMN indoor     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE prestatie ADD COLUMN indoor     INTEGER NOT NULL DEFAULT 0;

-- 2. Bestaande onderdelen indelen ------------------------------------------
-- Samen gelijk aan heeft_windmeting() in src/models/prestatie.py; houd ze
-- gelijk. Later per onderdeel aan te passen.

-- Sprints t/m 200 m ('100m', '200 meter'), verspringen en hinkstapspringen.
-- Geen horden en geen estafettes (4x100m).
UPDATE onderdeel SET windmeting = 1
WHERE lower(naam) LIKE '%verspringen%'
   OR lower(naam) LIKE '%hinkstap%'
   OR (    lower(naam) NOT LIKE '%horden%'
       AND lower(naam) NOT LIKE '%hurdles%'
       AND trim(naam) GLOB '[0-9]*'
       AND lower(naam) NOT LIKE '%x%'                       -- estafettes (4x100m)
       AND CAST(trim(naam) AS INTEGER) BETWEEN 1 AND 200
       AND (   trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) IN ('', 'm', 'meter')
            OR trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) LIKE 'm %'
            OR trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) LIKE 'meter %'));

-- Horden t/m 200 m ('80m horden', '100m Hurdles', '60mH', '110 meter horden').
UPDATE onderdeel SET windmeting = 1
WHERE trim(naam) GLOB '[0-9]*'
  AND lower(naam) NOT LIKE '%x%'                            -- geen estafettes
  AND CAST(trim(naam) AS INTEGER) BETWEEN 1 AND 200
  AND (   trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) = 'mh'
       OR trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) LIKE 'mh %'
       OR (    (lower(naam) LIKE '%horden%' OR lower(naam) LIKE '%hurdles%')
           AND (   trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) LIKE 'm %'
                OR trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) LIKE 'meter %')));

-- 3. PR-view: alleen windlegale of indoorprestaties ------------------------
DROP VIEW IF EXISTS pr;

CREATE VIEW pr AS
SELECT  p.atleet_ref,
        p.onderdeel_id,
        CASE WHEN o.lager_is_beter = 1 THEN MIN(p.waarde) ELSE MAX(p.waarde) END AS waarde
FROM prestatie p
JOIN onderdeel o ON o.id = p.onderdeel_id
WHERE o.windmeting = 0
   OR p.indoor = 1
   OR (p.wind IS NOT NULL AND p.wind <= 2.0)
GROUP BY p.atleet_ref, p.onderdeel_id;
