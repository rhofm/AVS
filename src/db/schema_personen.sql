-- Atleet Volg Systeem - personen.db, basisschema (versie 1)
-- Alles wat direct naar een persoon wijst: persoonsgegevens, groepen,
-- trainingen/absentie, leerlijnen en ploegen.
-- Wordt uitgevoerd door init_db.py op een lege database.
-- Latere wijzigingen NIET hier, maar in migrations/personen/NNN_beschrijving.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Atleet
-- master_id is een willekeurige id (32 hex-tekens, zie nieuw_master_id()).
-- Hij is NIET afgeleid van naam, geboortedatum of bondsnummer.
-- In prestaties.db en testen.db staat nooit de master_id zelf, alleen een
-- pseudoniem dat met de hoofdsleutel uit de master_id wordt berekend.
-- ============================================================
CREATE TABLE IF NOT EXISTS atleet (
    master_id       TEXT PRIMARY KEY
                    DEFAULT (lower(hex(randomblob(16))))
                    CHECK (length(master_id) = 32),
    voornaam        TEXT NOT NULL,
    tussenvoegsel   TEXT,              -- bijv. 'de', 'van der'; NULL als er geen is
    achternaam      TEXT NOT NULL,     -- zonder tussenvoegsel (sorteren gaat op achternaam)
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
    atleet_id   TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
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
    atleet_id   TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    status      TEXT NOT NULL CHECK (status IN ('aanwezig', 'afgemeld', 'afwezig', 'blessure')),
    reden       TEXT,
    PRIMARY KEY (training_id, atleet_id)
);

-- ============================================================
-- Leerlijnen
-- ============================================================
CREATE TABLE IF NOT EXISTS leerlijn (
    id           INTEGER PRIMARY KEY,
    naam         TEXT NOT NULL UNIQUE,
    beschrijving TEXT
);

CREATE TABLE IF NOT EXISTS leerlijn_stap (
    id           INTEGER PRIMARY KEY,
    leerlijn_id  INTEGER NOT NULL REFERENCES leerlijn(id) ON DELETE CASCADE,
    volgorde     INTEGER NOT NULL,
    naam         TEXT NOT NULL,
    beschrijving TEXT,
    UNIQUE (leerlijn_id, volgorde)
);

CREATE TABLE IF NOT EXISTS atleet_leerlijn (
    atleet_id   TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    stap_id     INTEGER NOT NULL REFERENCES leerlijn_stap(id) ON DELETE CASCADE,
    behaald_op  TEXT,
    notities    TEXT,
    PRIMARY KEY (atleet_id, stap_id)
);

-- ============================================================
-- Ploegen (competitie)
-- wedstrijd_id en onderdeel_id verwijzen naar prestaties.db. SQLite kan geen
-- foreign keys tussen bestanden afdwingen; de Python-code controleert ze.
-- ============================================================
CREATE TABLE IF NOT EXISTS ploeg (
    id            INTEGER PRIMARY KEY,
    naam          TEXT NOT NULL,
    competitie    TEXT,
    wedstrijd_id  INTEGER,                     -- prestaties.db: wedstrijd(id)
    regelset      TEXT,                        -- bestandsnaam in config/ploeg_regels/
    strategie     TEXT,                        -- welke 'mentaliteit' is gebruikt
    aangemaakt_op TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ploeg_opstelling (
    ploeg_id     INTEGER NOT NULL REFERENCES ploeg(id) ON DELETE CASCADE,
    atleet_id    TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    onderdeel_id INTEGER NOT NULL,             -- prestaties.db: onderdeel(id)
    reserve      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ploeg_id, atleet_id, onderdeel_id)
);

INSERT INTO schema_version (versie) VALUES (1);
