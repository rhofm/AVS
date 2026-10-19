-- personen.db, migratie 008: rooster (geplande trainingsinhoud per week), optioneel per groep.
--
-- rooster: een sjabloon van `aantal_weken` weken; kan door meer groepen en in
--   een volgend seizoen opnieuw worden gebruikt.
-- rooster_regel: wat er in week n op een dag (en begintijd) wordt gedaan: dezelfde
--   tekstvelden als een training. starttijd NULL = de vaste (eerste) begintijd van
--   die dag; een andere tijd is voor een extra training op die dag. Weeknummers
--   tellen vanaf de start van het rooster, los van de mesocyclus.
--   De UNIQUE telt een lege starttijd niet als gelijk; db/queries.py voorkomt dubbele regels.
-- groep_rooster: welk rooster een groep volgt vanaf welke datum (begin van week 1).
--   Zelfde regel als de periodisering: geldt tot de volgende koppeling van de groep.
--   herhalen 1 = na de laatste week weer week 1; 0 = één keer, daarna niets.
--   einddatum (optioneel) = harde stop.
-- training.rooster_regel_id: uit welke roosterregel de inhoud van een training is
--   gekopieerd. NULL = niet (of niet meer) uit het rooster: met de hand ingevuld of
--   aangepast. Alleen trainingen die nog naar een regel wijzen, worden bijgewerkt als
--   het rooster verandert; trainingen in het verleden nooit.
-- Geen persoonsgegevens.

CREATE TABLE IF NOT EXISTS rooster (
    id           INTEGER PRIMARY KEY,
    naam         TEXT    NOT NULL,
    aantal_weken INTEGER NOT NULL CHECK (aantal_weken BETWEEN 1 AND 60)
);

CREATE TABLE IF NOT EXISTS rooster_regel (
    id           INTEGER PRIMARY KEY,
    rooster_id   INTEGER NOT NULL REFERENCES rooster(id) ON DELETE CASCADE,
    week         INTEGER NOT NULL CHECK (week >= 1),
    dag          TEXT    NOT NULL CHECK (dag IN ('maandag', 'dinsdag', 'woensdag', 'donderdag',
                                                 'vrijdag', 'zaterdag', 'zondag')),
    starttijd    TEXT    CHECK (starttijd IS NULL OR (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]'
                                                      AND starttijd <= '23:59')),
    onderwerp    TEXT,
    warming_up   TEXT,
    kern_a       TEXT,
    kern_b       TEXT,
    cooling_down TEXT,
    notities     TEXT,
    UNIQUE (rooster_id, week, dag, starttijd)
);
CREATE INDEX IF NOT EXISTS idx_rooster_regel_rooster ON rooster_regel(rooster_id);

CREATE TABLE IF NOT EXISTS groep_rooster (
    groep_id   INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    rooster_id INTEGER NOT NULL REFERENCES rooster(id) ON DELETE CASCADE,
    startdatum TEXT    NOT NULL CHECK (length(startdatum) = 10 AND startdatum GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    herhalen   INTEGER NOT NULL DEFAULT 1 CHECK (herhalen IN (0, 1)),
    einddatum  TEXT    CHECK (einddatum IS NULL OR einddatum >= startdatum),
    PRIMARY KEY (groep_id, startdatum)
) WITHOUT ROWID;

ALTER TABLE training ADD COLUMN rooster_regel_id INTEGER REFERENCES rooster_regel(id) ON DELETE SET NULL;
