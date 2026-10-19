-- personen.db, migratie 009: licentienummer van de Atletiekunie (AU) per atleet.
--
-- Optioneel (NULL = niet bekend of geen licentie). Alleen cijfers; db/queries.py en
-- atleten/nieuw.py controleren dat. Uniek: twee atleten kunnen niet hetzelfde nummer
-- hebben (meerdere NULL's mag wel).
-- Persoonsgegeven: staat daarom alleen in personen.db, net als naam en atletiek.nu-id.

ALTER TABLE atleet ADD COLUMN au_licentienummer TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS atleet_au_licentienummer ON atleet (au_licentienummer);
