-- personen.db, migratie 005: trainingen met warming-up, kern A, kern B,
-- cooling-down en notities, en afwijkende trainingen voor enkele atleten.
--
-- Nummer 005 (niet 004): op een andere branch bestaat al een migratie 004
-- (groep_trainingstijden). Zo botsen ze niet als die branches samenkomen.
--
-- Tekstvelden (warming_up, kern_a, kern_b, cooling_down, notities): vrije,
-- meerregelige tekst. Markdown mag (**vet**, *schuin*, '- ' lijstjes, '# ' kopjes);
-- de app toont het opgemaakt. Leeg (NULL) = niet ingevuld.
--
-- Afwijkende training: een rij met hoofdtraining_id = de gewone training van
-- de groep (zelfde groep en datum). Welke atleten die volgen staat in
-- training_atleet (lang formaat, één rij per atleet). De gewone training
-- (hoofdtraining_id leeg) heeft geen rijen in training_atleet: die geldt voor
-- de rest van de groep. Aanwezigheid hoort altijd bij de gewone training.
--
-- De oude kolom `inhoud` gaat over naar `notities` en verdwijnt daarna.

ALTER TABLE training ADD COLUMN warming_up       TEXT;
ALTER TABLE training ADD COLUMN kern_a           TEXT;
ALTER TABLE training ADD COLUMN kern_b           TEXT;
ALTER TABLE training ADD COLUMN cooling_down     TEXT;
ALTER TABLE training ADD COLUMN notities         TEXT;
ALTER TABLE training ADD COLUMN hoofdtraining_id INTEGER REFERENCES training(id) ON DELETE CASCADE;

UPDATE training SET notities = inhoud WHERE inhoud IS NOT NULL AND trim(inhoud) <> '';
ALTER TABLE training DROP COLUMN inhoud;

CREATE INDEX IF NOT EXISTS idx_training_hoofd ON training(hoofdtraining_id);

CREATE TABLE IF NOT EXISTS training_atleet (
    training_id INTEGER NOT NULL REFERENCES training(id) ON DELETE CASCADE,
    atleet_id   TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    PRIMARY KEY (training_id, atleet_id)
);
