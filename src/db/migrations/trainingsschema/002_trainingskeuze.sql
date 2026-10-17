-- trainingsschema.db, migratie 002: welke training(en) een atleet kiest als er
-- op een weekdag meerdere zijn (in verschillende groepen, of meerdere tijden
-- van één groep).
--
-- Eén rij per gekozen training: weekdag + groep + begintijd. Staat er voor een
-- weekdag niets, dan geldt "alle trainingen van mijn groepen op die dag" (zo
-- werkte het al). De tabel wordt alleen gevuld als de atleet een deel van de
-- trainingen op die dag kiest.
--
-- De atleet staat hier alleen als pseudoniem (atleet_ref), net als in
-- trainingsschema. groep_id verwijst naar personen.db: groep(id); dat is geen
-- persoonsgegeven en SQLite kan het tussen bestanden niet afdwingen, dus
-- db/queries.py slaat keuzes van verdwenen groepen over.

CREATE TABLE IF NOT EXISTS trainingskeuze (
    atleet_ref TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    dag        TEXT    NOT NULL CHECK (dag IN ('maandag', 'dinsdag', 'woensdag', 'donderdag',
                                               'vrijdag', 'zaterdag', 'zondag')),
    groep_id   INTEGER NOT NULL,
    starttijd  TEXT    NOT NULL CHECK (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]'
                                       AND starttijd <= '23:59'),
    PRIMARY KEY (atleet_ref, dag, groep_id, starttijd)
) WITHOUT ROWID;
