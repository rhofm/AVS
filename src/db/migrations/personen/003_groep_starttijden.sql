-- personen.db, migratie 003: starttijd per weekdag voor elke groep.
--
-- Eén kolom per weekdag (maandag ... zondag). Leeg (NULL) = de groep traint
-- die dag niet; anders de starttijd als 'HH:MM' (bijv. '18:30').
-- De tijden staan één keer per groep, niet per atleet: wie in de groep zit
-- staat in groep_lid (lang formaat, één rij per atleet per groep; een atleet
-- kan in meerdere groepen zitten).
-- Bestaande groepen krijgen geen tijden; vul ze in via de app.

ALTER TABLE groep ADD COLUMN maandag   TEXT CHECK (maandag IS NULL OR (maandag GLOB '[0-2][0-9]:[0-5][0-9]' AND maandag <= '23:59'));
ALTER TABLE groep ADD COLUMN dinsdag   TEXT CHECK (dinsdag IS NULL OR (dinsdag GLOB '[0-2][0-9]:[0-5][0-9]' AND dinsdag <= '23:59'));
ALTER TABLE groep ADD COLUMN woensdag  TEXT CHECK (woensdag IS NULL OR (woensdag GLOB '[0-2][0-9]:[0-5][0-9]' AND woensdag <= '23:59'));
ALTER TABLE groep ADD COLUMN donderdag TEXT CHECK (donderdag IS NULL OR (donderdag GLOB '[0-2][0-9]:[0-5][0-9]' AND donderdag <= '23:59'));
ALTER TABLE groep ADD COLUMN vrijdag   TEXT CHECK (vrijdag IS NULL OR (vrijdag GLOB '[0-2][0-9]:[0-5][0-9]' AND vrijdag <= '23:59'));
ALTER TABLE groep ADD COLUMN zaterdag  TEXT CHECK (zaterdag IS NULL OR (zaterdag GLOB '[0-2][0-9]:[0-5][0-9]' AND zaterdag <= '23:59'));
ALTER TABLE groep ADD COLUMN zondag    TEXT CHECK (zondag IS NULL OR (zondag GLOB '[0-2][0-9]:[0-5][0-9]' AND zondag <= '23:59'));
