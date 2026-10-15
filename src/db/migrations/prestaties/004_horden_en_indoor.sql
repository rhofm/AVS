-- prestaties.db, migratie 004: horden t/m 200 m met windmeting, en indoor.
--
-- 1. Horden t/m 200 m krijgen windmeting: een PR telt daar alleen met een
--    gemeten wind van hoogstens +2,0 m/s (net als sprints t/m 200 m,
--    verspringen en hinkstapspringen, zie migratie 003).
-- 2. Indoor wordt geen wind gemeten. Een indoorprestatie telt daarom altijd
--    voor een PR. Een wedstrijd kan als indoor gemarkeerd worden; de
--    prestaties op die wedstrijd nemen dat over (db/queries.py regelt dat).
--    Bestaande wedstrijden staan op outdoor; markeer indoorwedstrijden zelf.
--
-- Vervangt de view `pr` uit migratie 003. Er gaan geen prestaties verloren.

ALTER TABLE wedstrijd ADD COLUMN indoor INTEGER NOT NULL DEFAULT 0;
ALTER TABLE prestatie ADD COLUMN indoor INTEGER NOT NULL DEFAULT 0;

-- Horden t/m 200 m (bijv. '80m horden', '100m Hurdles', '60mH', '110 meter horden').
-- Samen met migratie 003 gelijk aan heeft_windmeting() in src/models/prestatie.py.
UPDATE onderdeel SET windmeting = 1
WHERE trim(naam) GLOB '[0-9]*'
  AND lower(naam) NOT LIKE '%x%'                            -- geen estafettes
  AND CAST(trim(naam) AS INTEGER) BETWEEN 1 AND 200
  AND (   trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) = 'mh'
       OR trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) LIKE 'mh %'
       OR (    (lower(naam) LIKE '%horden%' OR lower(naam) LIKE '%hurdles%')
           AND (   trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) LIKE 'm %'
                OR trim(lower(substr(trim(naam), length(CAST(CAST(trim(naam) AS INTEGER) AS TEXT)) + 1))) LIKE 'meter %')));

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
