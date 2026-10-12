-- Atleet Volg Systeem - basisschema (versie 1)
-- Wordt uitgevoerd door init_db.py op een lege database.
-- Latere wijzigingen NIET hier, maar als nieuw bestand in migrations/
-- (bijv. 002_iets_toevoegen.sql).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie      INTEGER NOT NULL,
    toegepast_op TEXT   NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Atleet
-- ============================================================
CREATE TABLE IF NOT EXISTS atleet (
    id              INTEGER PRIMARY KEY,
    voornaam        TEXT NOT NULL,
    achternaam      TEXT NOT NULL,
    geslacht        TEXT CHECK (geslacht IN ('M', 'V', 'X')),
    geboortedatum   TEXT,              -- ISO 'YYYY-MM-DD' (of alleen jaar: 'YYYY')
    club            TEXT,
    atletieknu_id   TEXT UNIQUE,       -- om imports aan de juiste atleet te koppelen
    specialisatie   TEXT,
    actief          INTEGER NOT NULL DEFAULT 1,
    notities        TEXT,
    aangemaakt_op   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Onderdelen, wedstrijden, prestaties
-- ============================================================
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
    bron_url    TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS prestatie (
    id              INTEGER PRIMARY KEY,
    atleet_id       INTEGER NOT NULL REFERENCES atleet(id) ON DELETE CASCADE,
    onderdeel_id    INTEGER NOT NULL REFERENCES onderdeel(id),
    wedstrijd_id    INTEGER REFERENCES wedstrijd(id) ON DELETE SET NULL,
    datum           TEXT NOT NULL,
    waarde          REAL NOT NULL,             -- seconden / meters / punten
    wind            REAL,
    ronde           TEXT NOT NULL DEFAULT '',  -- serie, finale, ... ('' i.p.v. NULL, anders werkt UNIQUE niet)
    bron            TEXT CHECK (bron IN ('atletieknu', 'seltec', 'handmatig')),
    bron_url        TEXT,
    UNIQUE (atleet_id, onderdeel_id, datum, waarde, ronde)   -- voorkomt dubbele imports
);
CREATE INDEX IF NOT EXISTS idx_prestatie_atleet ON prestatie(atleet_id, onderdeel_id);

-- Geplande wedstrijden per atleet
CREATE TABLE IF NOT EXISTS inschrijving (
    atleet_id       INTEGER NOT NULL REFERENCES atleet(id) ON DELETE CASCADE,
    wedstrijd_id    INTEGER NOT NULL REFERENCES wedstrijd(id) ON DELETE CASCADE,
    onderdeel_id    INTEGER REFERENCES onderdeel(id),
    PRIMARY KEY (atleet_id, wedstrijd_id, onderdeel_id)
);

-- PR per atleet per onderdeel (afgeleid, dus geen aparte tabel nodig)
CREATE VIEW IF NOT EXISTS pr AS
SELECT  p.atleet_id,
        p.onderdeel_id,
        CASE WHEN o.lager_is_beter = 1 THEN MIN(p.waarde) ELSE MAX(p.waarde) END AS waarde
FROM prestatie p
JOIN onderdeel o ON o.id = p.onderdeel_id
GROUP BY p.atleet_id, p.onderdeel_id;

-- ============================================================
-- Testen
-- ============================================================
CREATE TABLE IF NOT EXISTS test (
    id              INTEGER PRIMARY KEY,
    naam            TEXT NOT NULL UNIQUE,      -- bijv. '30m vliegend', 'Kogelstoten achterwaarts'
    eenheid         TEXT NOT NULL,
    lager_is_beter  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS testresultaat (
    id          INTEGER PRIMARY KEY,
    atleet_id   INTEGER NOT NULL REFERENCES atleet(id) ON DELETE CASCADE,
    test_id     INTEGER NOT NULL REFERENCES test(id),
    datum       TEXT NOT NULL,
    waarde      REAL NOT NULL,
    notities    TEXT
);

-- ============================================================
-- Groepen, trainingen, absentie, periodeplannen
-- ============================================================
CREATE TABLE IF NOT EXISTS groep (
    id          INTEGER PRIMARY KEY,
    naam        TEXT NOT NULL,
    seizoen     TEXT,                          -- bijv. '2026-2027'
    UNIQUE (naam, seizoen)
);

CREATE TABLE IF NOT EXISTS groep_lid (
    groep_id    INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    atleet_id   INTEGER NOT NULL REFERENCES atleet(id) ON DELETE CASCADE,
    PRIMARY KEY (groep_id, atleet_id)
);

CREATE TABLE IF NOT EXISTS periodeplan (
    id          INTEGER PRIMARY KEY,
    groep_id    INTEGER REFERENCES groep(id) ON DELETE CASCADE,
    naam        TEXT NOT NULL,                 -- bijv. 'Algemene voorbereiding'
    startdatum  TEXT NOT NULL,
    einddatum   TEXT NOT NULL,
    doel        TEXT
);

CREATE TABLE IF NOT EXISTS training (
    id              INTEGER PRIMARY KEY,
    groep_id        INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    periodeplan_id  INTEGER REFERENCES periodeplan(id) ON DELETE SET NULL,
    datum           TEXT NOT NULL,
    onderwerp       TEXT,
    inhoud          TEXT
);

CREATE TABLE IF NOT EXISTS absentie (
    training_id INTEGER NOT NULL REFERENCES training(id) ON DELETE CASCADE,
    atleet_id   INTEGER NOT NULL REFERENCES atleet(id) ON DELETE CASCADE,
    status      TEXT NOT NULL CHECK (status IN ('aanwezig', 'afgemeld', 'afwezig', 'blessure')),
    reden       TEXT,
    PRIMARY KEY (training_id, atleet_id)
);

-- ============================================================
-- Leerlijnen
-- ============================================================
CREATE TABLE IF NOT EXISTS leerlijn (
    id          INTEGER PRIMARY KEY,
    naam        TEXT NOT NULL UNIQUE,
    beschrijving TEXT
);

CREATE TABLE IF NOT EXISTS leerlijn_stap (
    id          INTEGER PRIMARY KEY,
    leerlijn_id INTEGER NOT NULL REFERENCES leerlijn(id) ON DELETE CASCADE,
    volgorde    INTEGER NOT NULL,
    naam        TEXT NOT NULL,
    beschrijving TEXT,
    UNIQUE (leerlijn_id, volgorde)
);

CREATE TABLE IF NOT EXISTS atleet_leerlijn (
    atleet_id   INTEGER NOT NULL REFERENCES atleet(id) ON DELETE CASCADE,
    stap_id     INTEGER NOT NULL REFERENCES leerlijn_stap(id) ON DELETE CASCADE,
    behaald_op  TEXT,
    notities    TEXT,
    PRIMARY KEY (atleet_id, stap_id)
);

-- ============================================================
-- Ploegen (competitie)
-- ============================================================
CREATE TABLE IF NOT EXISTS ploeg (
    id          INTEGER PRIMARY KEY,
    naam        TEXT NOT NULL,
    competitie  TEXT,
    wedstrijd_id INTEGER REFERENCES wedstrijd(id) ON DELETE SET NULL,
    regelset    TEXT,                          -- bestandsnaam in config/ploeg_regels/
    strategie   TEXT,                          -- welke 'mentaliteit' is gebruikt
    aangemaakt_op TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ploeg_opstelling (
    ploeg_id     INTEGER NOT NULL REFERENCES ploeg(id) ON DELETE CASCADE,
    atleet_id    INTEGER NOT NULL REFERENCES atleet(id) ON DELETE CASCADE,
    onderdeel_id INTEGER NOT NULL REFERENCES onderdeel(id),
    reserve      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ploeg_id, atleet_id, onderdeel_id)
);

INSERT INTO schema_version (versie) VALUES (1);
