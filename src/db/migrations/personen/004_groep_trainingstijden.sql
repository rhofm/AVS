-- personen.db, migratie 004: trainingstijden per groep.
--
-- Eén rij per groep: de groep-id en per weekdag de begintijd ('HH:MM', 24 uur)
-- of leeg (NULL) = de groep traint die dag niet. Een groep zonder rij heeft
-- (nog) geen vaste trainingsdagen; de app leidt ze dan af uit de trainingen of
-- de trainingsschema's. Geen persoonsgegevens.
--
-- Vervangt twee eerdere varianten die allebei als migratie 003 waren genummerd
-- (kolommen maandag..zondag op `groep`, en de tabel `groep_trainingsdag`).
-- init_db.py zet de tijden uit die varianten over en ruimt ze daarna op.

CREATE TABLE IF NOT EXISTS groep_trainingstijden (
    groep_id  INTEGER PRIMARY KEY REFERENCES groep(id) ON DELETE CASCADE,
    maandag   TEXT CHECK (maandag IS NULL OR (length(maandag) = 5 AND maandag GLOB '[0-2][0-9]:[0-5][0-9]' AND maandag <= '23:59')),
    dinsdag   TEXT CHECK (dinsdag IS NULL OR (length(dinsdag) = 5 AND dinsdag GLOB '[0-2][0-9]:[0-5][0-9]' AND dinsdag <= '23:59')),
    woensdag  TEXT CHECK (woensdag IS NULL OR (length(woensdag) = 5 AND woensdag GLOB '[0-2][0-9]:[0-5][0-9]' AND woensdag <= '23:59')),
    donderdag TEXT CHECK (donderdag IS NULL OR (length(donderdag) = 5 AND donderdag GLOB '[0-2][0-9]:[0-5][0-9]' AND donderdag <= '23:59')),
    vrijdag   TEXT CHECK (vrijdag IS NULL OR (length(vrijdag) = 5 AND vrijdag GLOB '[0-2][0-9]:[0-5][0-9]' AND vrijdag <= '23:59')),
    zaterdag  TEXT CHECK (zaterdag IS NULL OR (length(zaterdag) = 5 AND zaterdag GLOB '[0-2][0-9]:[0-5][0-9]' AND zaterdag <= '23:59')),
    zondag    TEXT CHECK (zondag IS NULL OR (length(zondag) = 5 AND zondag GLOB '[0-2][0-9]:[0-5][0-9]' AND zondag <= '23:59'))
);
