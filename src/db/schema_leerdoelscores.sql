-- Atleet Volg Systeem - leerdoelscores.db, basisschema (versie 1)
-- Per atleet per leerdoel een score van 1 t/m 5, in LANG formaat: één rij per
-- atleet per leerdoel per beoordelingsdatum. De volledige geschiedenis blijft
-- staan, zodat de ontwikkeling van een atleet zichtbaar is. Het overzicht
-- "atleten x leerdoelen" (breed formaat) wordt in Python gemaakt
-- (Opslag.leerdoelscores_breed), niet opgeslagen.
--
-- Bevat GEEN namen of master_ids: een atleet staat hier alleen als pseudoniem
-- (atleet_ref), berekend met pseudoniem(master_id, 'leerdoelscores') uit init_db.py.
-- Latere wijzigingen NIET hier, maar in migrations/leerdoelscores/NNN_beschrijving.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- leerdoel_id verwijst naar leerlijnen.db: leerdoel(id). SQLite kan geen
-- foreign keys tussen bestanden afdwingen; db/queries.py controleert ze.
-- De betekenis van 1-5 staat in leerlijnen.db: scoreschaal.
-- Nog niet beoordeeld = geen rij (niet: score 1).
-- Op dezelfde dag opnieuw scoren overschrijft de score van die dag.
CREATE TABLE IF NOT EXISTS leerdoelscore (
    atleet_ref   TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    leerdoel_id  TEXT    NOT NULL,
    score        INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    datum        TEXT    NOT NULL CHECK (datum GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    notities     TEXT,                          -- kort en over de techniek; geen gezondheidsgegevens
    PRIMARY KEY (atleet_ref, leerdoel_id, datum)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_leerdoelscore_leerdoel ON leerdoelscore(leerdoel_id);

-- De meest recente score per atleet per leerdoel.
CREATE VIEW IF NOT EXISTS laatste_leerdoelscore AS
SELECT s.atleet_ref, s.leerdoel_id, s.score, s.datum, s.notities
FROM leerdoelscore s
WHERE s.datum = (SELECT MAX(t.datum) FROM leerdoelscore t
                 WHERE t.atleet_ref = s.atleet_ref AND t.leerdoel_id = s.leerdoel_id);

INSERT INTO schema_version (versie) VALUES (1);
