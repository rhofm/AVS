-- prestaties.db, migratie 003: windmeting per onderdeel.
--
-- Bij sprints t/m 200 m, verspringen en hinkstapspringen wordt de wind
-- gemeten. Een prestatie op zo'n onderdeel telt alleen als PR als de wind
-- gemeten is en hoogstens +2,0 m/s was; ZONDER windmeting telt hij dus niet.
-- Bij alle andere onderdelen telt elke prestatie (een eventuele windwaarde
-- wordt genegeerd).
--
-- Vervangt de view `pr` uit migratie 002. Er gaan geen prestaties verloren.

ALTER TABLE onderdeel ADD COLUMN windmeting INTEGER NOT NULL DEFAULT 0;

-- Bestaande onderdelen indelen. Zelfde regel als heeft_windmeting() in
-- src/models/prestatie.py; houd ze gelijk. Later aan te passen per onderdeel.
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

DROP VIEW IF EXISTS pr;

CREATE VIEW pr AS
SELECT  p.atleet_ref,
        p.onderdeel_id,
        CASE WHEN o.lager_is_beter = 1 THEN MIN(p.waarde) ELSE MAX(p.waarde) END AS waarde
FROM prestatie p
JOIN onderdeel o ON o.id = p.onderdeel_id
WHERE o.windmeting = 0
   OR (p.wind IS NOT NULL AND p.wind <= 2.0)
GROUP BY p.atleet_ref, p.onderdeel_id;
