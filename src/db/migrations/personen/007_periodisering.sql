-- personen.db, migratie 007: periodisering van een groep (megacyclus en mesocyclus).
--
-- Regel voor allebei: een rij heeft een startdatum en geldt tot de volgende rij
-- van dezelfde soort (zelfde groep) begint. Er staan dus alleen startdatums in,
-- geen einddatums die gelijk moeten blijven. Geen rijen = de groep gebruikt het
-- niet. In welke fase en mesoweek een datum valt, rekent de app uit
-- (models/periodisering.py); dat staat nooit per training opgeslagen.
-- Geen persoonsgegevens.
--
-- groep_fase: megacyclus (het hele jaar). Een fase kan vaker per jaar voorkomen
-- (bijv. V1 - WP indoor - V2 - WP baan - Rust). 'Geen' stopt de periodisering
-- (bijv. einde seizoen); zonder 'Geen' loopt de laatste fase door.
--
-- mesocyclus: een blok van een paar weken dat zich herhaalt vanaf startdatum
-- tot de volgende mesocyclus van de groep. startdatum = eerste dag van week 1
-- (de app zet hem op het begin van de week). mesocyclus_week: de naam per week.
--
-- Het oude periodeplan (naam, start, eind, doel) maakt plaats voor de
-- megacyclus. Het doel ervan (doelen voor groep/atleten bij een wedstrijd)
-- krijgt een eigen tabel `doel` in prestaties.db (migratie prestaties/004).
-- init_db.py kopieert de oude rijen naar `doel` en maakt de tabel periodeplan
-- daarna leeg; daarbij wordt training.periodeplan_id overal leeg (ON DELETE
-- SET NULL). De tabel en de kolom blijven bestaan maar worden niet meer
-- gebruikt: training.periodeplan_id verwijst ernaar, en zonder de tabel weigert
-- SQLite elke nieuwe training. Weghalen kan alleen door training opnieuw op te
-- bouwen, en dat is het risico niet waard.

CREATE TABLE IF NOT EXISTS groep_fase (
    groep_id   INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    startdatum TEXT    NOT NULL CHECK (length(startdatum) = 10 AND startdatum GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    fase       TEXT    NOT NULL CHECK (fase IN ('V1', 'V2', 'WP', 'Rust', 'Geen')),
    PRIMARY KEY (groep_id, startdatum)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS mesocyclus (
    id           INTEGER PRIMARY KEY,
    groep_id     INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    startdatum   TEXT    NOT NULL CHECK (length(startdatum) = 10 AND startdatum GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    aantal_weken INTEGER NOT NULL CHECK (aantal_weken BETWEEN 1 AND 12),
    UNIQUE (groep_id, startdatum)
);

CREATE TABLE IF NOT EXISTS mesocyclus_week (
    mesocyclus_id INTEGER NOT NULL REFERENCES mesocyclus(id) ON DELETE CASCADE,
    weeknummer    INTEGER NOT NULL CHECK (weeknummer BETWEEN 1 AND 12),
    naam          TEXT    NOT NULL,
    PRIMARY KEY (mesocyclus_id, weeknummer)
) WITHOUT ROWID;
