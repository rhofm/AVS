-- Atleet Volg Systeem - trainingsschema.db, basisschema (versie 1)
-- Op welke dagen van de week een atleet traint. Bevat GEEN namen of
-- master_ids: een atleet staat hier alleen als pseudoniem (atleet_ref),
-- berekend met pseudoniem(master_id, 'trainingsschema') uit init_db.py. Dat
-- pseudoniem verschilt van die in prestaties.db en testen.db, zodat de
-- bestanden niet aan elkaar te koppelen zijn.
-- Latere wijzigingen NIET hier, maar in migrations/trainingsschema/NNN_beschrijving.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Eén rij per atleet; per dag 1 = traint, 0 = traint niet.
CREATE TABLE IF NOT EXISTS trainingsschema (
    atleet_ref  TEXT PRIMARY KEY CHECK (length(atleet_ref) = 32),
    maandag     INTEGER NOT NULL DEFAULT 0 CHECK (maandag   IN (0, 1)),
    dinsdag     INTEGER NOT NULL DEFAULT 0 CHECK (dinsdag   IN (0, 1)),
    woensdag    INTEGER NOT NULL DEFAULT 0 CHECK (woensdag  IN (0, 1)),
    donderdag   INTEGER NOT NULL DEFAULT 0 CHECK (donderdag IN (0, 1)),
    vrijdag     INTEGER NOT NULL DEFAULT 0 CHECK (vrijdag   IN (0, 1)),
    zaterdag    INTEGER NOT NULL DEFAULT 0 CHECK (zaterdag  IN (0, 1)),
    zondag      INTEGER NOT NULL DEFAULT 0 CHECK (zondag    IN (0, 1))
);

INSERT INTO schema_version (versie) VALUES (1);
