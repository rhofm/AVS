-- Atleet Volg Systeem - prestaties.db, basisschema (versie 1)
-- Onderdelen, wedstrijden, prestaties en PR's. Bevat GEEN namen of master_ids:
-- een atleet staat hier alleen als pseudoniem (atleet_ref), berekend met
-- pseudoniem(master_id, 'prestaties') uit init_db.py.
-- Latere wijzigingen NIET hier, maar in migrations/prestaties/NNN_beschrijving.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS onderdeel (
    id              INTEGER PRIMARY KEY,
    naam            TEXT NOT NULL UNIQUE,      -- bijv. '100m', 'Verspringen', '60m horden 76,2cm'
    categorie       TEXT,                      -- sprint, horden, midden, springen, werpen, meerkamp
    eenheid         TEXT NOT NULL CHECK (eenheid IN ('tijd', 'afstand', 'hoogte', 'punten')),
    lager_is_beter  INTEGER NOT NULL           -- 1 voor looponderdelen, 0 voor technische
);

CREATE TABLE IF NOT EXISTS wedstrijd (
    id          INTEGER PRIMARY KEY,
    naam        TEXT NOT NULL,
    datum       TEXT NOT NULL,                 -- ISO 'YYYY-MM-DD'
    locatie     TEXT,
    bron        TEXT CHECK (bron IN ('atletieknu', 'seltec', 'handmatig')),
    bron_url    TEXT UNIQUE                    -- uitslagpagina van de wedstrijd, niet van een atleet
);

-- Geen bron_url per prestatie: een PR-pagina op atletiek.nu bevat het
-- atleetnummer en zou het pseudoniem weer aan een persoon koppelen.
CREATE TABLE IF NOT EXISTS prestatie (
    id              INTEGER PRIMARY KEY,
    atleet_ref      TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    onderdeel_id    INTEGER NOT NULL REFERENCES onderdeel(id),
    wedstrijd_id    INTEGER REFERENCES wedstrijd(id) ON DELETE SET NULL,
    datum           TEXT NOT NULL,
    waarde          REAL NOT NULL,             -- seconden / meters / punten
    wind            REAL,
    ronde           TEXT NOT NULL DEFAULT '',  -- serie, finale, ... ('' i.p.v. NULL, anders werkt UNIQUE niet)
    bron            TEXT CHECK (bron IN ('atletieknu', 'seltec', 'handmatig')),
    UNIQUE (atleet_ref, onderdeel_id, datum, waarde, ronde)   -- voorkomt dubbele imports
);
CREATE INDEX IF NOT EXISTS idx_prestatie_atleet ON prestatie(atleet_ref, onderdeel_id);

-- Geplande wedstrijden per atleet
CREATE TABLE IF NOT EXISTS inschrijving (
    atleet_ref      TEXT    NOT NULL CHECK (length(atleet_ref) = 32),
    wedstrijd_id    INTEGER NOT NULL REFERENCES wedstrijd(id) ON DELETE CASCADE,
    onderdeel_id    INTEGER REFERENCES onderdeel(id),
    PRIMARY KEY (atleet_ref, wedstrijd_id, onderdeel_id)
);

-- PR per atleet per onderdeel (afgeleid, dus geen aparte tabel nodig)
CREATE VIEW IF NOT EXISTS pr AS
SELECT  p.atleet_ref,
        p.onderdeel_id,
        CASE WHEN o.lager_is_beter = 1 THEN MIN(p.waarde) ELSE MAX(p.waarde) END AS waarde
FROM prestatie p
JOIN onderdeel o ON o.id = p.onderdeel_id
GROUP BY p.atleet_ref, p.onderdeel_id;

INSERT INTO schema_version (versie) VALUES (1);
