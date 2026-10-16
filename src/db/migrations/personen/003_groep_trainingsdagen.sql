-- personen.db, migratie 003: vaste trainingsdagen en begintijden per groep.
--
-- Eén rij per groep per weekdag waarop de groep traint. De begintijd is
-- optioneel ('HH:MM', 24 uur). Een groep zonder rijen heeft (nog) geen vaste
-- dagen; de app leidt ze dan af uit de trainingen of de trainingsschema's.
-- Geen persoonsgegevens.

CREATE TABLE IF NOT EXISTS groep_trainingsdag (
    groep_id   INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    dag        TEXT    NOT NULL CHECK (dag IN ('maandag', 'dinsdag', 'woensdag', 'donderdag',
                                                'vrijdag', 'zaterdag', 'zondag')),
    starttijd  TEXT    CHECK (starttijd IS NULL OR (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]')),
    PRIMARY KEY (groep_id, dag)
);
