-- personen.db, migratie 006: meer dan één training per dag voor een groep.
--
-- groep_extra_trainingstijd: extra begintijden op een weekdag, naast de vaste
-- begintijd in groep_trainingstijden (bijv. zaterdag 09:00 staat daar, 10:30
-- hier). Eén rij per extra tijd. Een dag heeft alleen extra tijden als hij ook
-- een vaste begintijd heeft; dat controleert db/queries.py. Geen persoonsgegevens.
--
-- training.starttijd: de begintijd van deze training ('HH:MM'). Nodig om twee
-- trainingen van dezelfde groep op dezelfde datum uit elkaar te houden. Leeg
-- (NULL) = de vaste begintijd van die dag; zo blijven bestaande trainingen
-- gewoon de 'eerste' training van hun dag.

CREATE TABLE IF NOT EXISTS groep_extra_trainingstijd (
    groep_id  INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    dag       TEXT    NOT NULL CHECK (dag IN ('maandag', 'dinsdag', 'woensdag', 'donderdag',
                                              'vrijdag', 'zaterdag', 'zondag')),
    starttijd TEXT    NOT NULL CHECK (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]'
                                      AND starttijd <= '23:59'),
    PRIMARY KEY (groep_id, dag, starttijd)
);

ALTER TABLE training ADD COLUMN starttijd TEXT
    CHECK (starttijd IS NULL OR (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]'
                                 AND starttijd <= '23:59'));
