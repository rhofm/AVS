-- Atleet Volg Systeem - absentie.db, basisschema (versie 1)
-- Aanwezigheid per training, in lang formaat: één rij per atleet per training.
-- Bevat GEEN namen of master_ids: een atleet staat hier alleen als pseudoniem
-- (atleet_ref), berekend met pseudoniem(master_id, 'absentie') uit init_db.py.
-- Apart van personen.db omdat 'blessure' een gezondheidsgegeven is (AVG).
-- Latere wijzigingen NIET hier, maar in migrations/absentie/NNN_beschrijving.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- training_id verwijst naar personen.db: training(id). Daar staan de datum en
-- de groep. SQLite kan geen foreign keys tussen bestanden afdwingen; de
-- Python-code (db/queries.py) controleert ze.
-- Elke status wordt expliciet opgeslagen, ook 'aanwezig': geen rij betekent
-- "nog niet ingevuld", niet "aanwezig".
CREATE TABLE IF NOT EXISTS absentie (
    training_id INTEGER NOT NULL,
    atleet_ref  TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    status      TEXT    NOT NULL CHECK (status IN ('aanwezig', 'afgemeld', 'afwezig', 'blessure')),
    reden       TEXT,                          -- kort en feitelijk, geen diagnose
    PRIMARY KEY (training_id, atleet_ref)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_absentie_atleet ON absentie(atleet_ref);

INSERT INTO schema_version (versie) VALUES (1);
