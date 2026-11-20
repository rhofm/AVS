-- Atleet Volg Systeem - trainingsschema.db, basisschema (versie 2)
-- Op welke dagen van de week een atleet traint, en welke training(en) hij kiest
-- als er op een dag meerdere zijn. Bevat GEEN namen of master_ids: een atleet
-- staat hier alleen als pseudoniem (atleet_ref), berekend met
-- pseudoniem(master_id, 'trainingsschema') uit init_db.py. Dat pseudoniem
-- verschilt van die in de andere databases, zodat de bestanden niet aan elkaar
-- te koppelen zijn.
--
-- Samengevoegd: dit is versie 1 + migratie 002, zodat een nieuwe installatie
-- niet alle oude stappen hoeft te doorlopen. Een database die ouder is dan
-- versie 2 kan deze AVS niet meer bijwerken (init_db.basisversie()).
-- Latere wijzigingen NIET hier, maar in migrations/trainingsschema/NNN_beschrijving.sql
-- (vanaf 003).

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

-- Welke training(en) een atleet kiest als er op een weekdag meerdere zijn (in
-- verschillende groepen, of meerdere tijden van één groep).
--
-- Eén rij per gekozen training: weekdag + groep + begintijd. Staat er voor een
-- weekdag niets, dan geldt "alle trainingen van mijn groepen op die dag". De
-- tabel wordt alleen gevuld als de atleet een deel van de trainingen op die
-- dag kiest.
--
-- groep_id verwijst naar personen.db: groep(id); dat is geen persoonsgegeven
-- en SQLite kan het tussen bestanden niet afdwingen, dus db/queries.py slaat
-- keuzes van verdwenen groepen over.
CREATE TABLE IF NOT EXISTS trainingskeuze (
    atleet_ref TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    dag        TEXT    NOT NULL CHECK (dag IN ('maandag', 'dinsdag', 'woensdag', 'donderdag',
                                               'vrijdag', 'zaterdag', 'zondag')),
    groep_id   INTEGER NOT NULL,
    starttijd  TEXT    NOT NULL CHECK (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]'
                                       AND starttijd <= '23:59'),
    PRIMARY KEY (atleet_ref, dag, groep_id, starttijd)
) WITHOUT ROWID;

INSERT INTO schema_version (versie) VALUES (2);
