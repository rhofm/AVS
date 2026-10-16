-- Atleet Volg Systeem - notities.db, basisschema (versie 1)
-- Vrije notities over een atleet: wat de trainer zag op een training of
-- wedstrijd en wil onthouden. Eén rij per notitie; de tekst mag lang zijn.
--
-- Bevat GEEN namen of master_ids als sleutel: een atleet staat hier alleen als
-- pseudoniem (atleet_ref), berekend met pseudoniem(master_id, 'notities') uit
-- init_db.py. LET OP: de tekst zelf is vrij. Wat erin staat (bijv. een naam of
-- een blessure) is alleen beschermd door de versleuteling, niet door het
-- pseudoniem. Houd notities feitelijk en zet er geen diagnoses in.
-- Latere wijzigingen NIET hier, maar in migrations/notities/NNN_beschrijving.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notitie (
    id            INTEGER PRIMARY KEY,
    atleet_ref    TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    datum         TEXT    NOT NULL CHECK (datum GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    inhoud        TEXT    NOT NULL CHECK (length(trim(inhoud)) > 0),   -- geen lengtegrens
    aangemaakt_op TEXT    NOT NULL DEFAULT (datetime('now')),
    bijgewerkt_op TEXT                                                 -- NULL = nooit aangepast
);
CREATE INDEX IF NOT EXISTS idx_notitie_atleet ON notitie(atleet_ref, datum);
CREATE INDEX IF NOT EXISTS idx_notitie_datum  ON notitie(datum);

INSERT INTO schema_version (versie) VALUES (1);
