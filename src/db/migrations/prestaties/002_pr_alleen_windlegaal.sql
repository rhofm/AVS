-- prestaties.db, migratie 002: PR's alleen uit windlegale prestaties.
--
-- Een prestatie met meer dan 2,0 m/s rugwind telt niet als record (regel van
-- World Athletics voor sprint, horden en horizontale sprongen). De view `pr`
-- uit versie 1 telde ze wel mee. Prestaties zonder windmeting (wind = NULL,
-- bijv. midden- en lange afstand, werpen, hoogspringen) tellen gewoon mee.
--
-- Er gaan geen gegevens verloren: alleen de view wordt opnieuw gemaakt.
-- init_db.py voert dit uit en zet schema_version op 2.

DROP VIEW IF EXISTS pr;

CREATE VIEW pr AS
SELECT  p.atleet_ref,
        p.onderdeel_id,
        CASE WHEN o.lager_is_beter = 1 THEN MIN(p.waarde) ELSE MAX(p.waarde) END AS waarde
FROM prestatie p
JOIN onderdeel o ON o.id = p.onderdeel_id
WHERE p.wind IS NULL OR p.wind <= 2.0
GROUP BY p.atleet_ref, p.onderdeel_id;
