-- Atleet Volg Systeem - prestaties.db, basisschema (versie 4)
-- Onderdelen, wedstrijden (met tijdschema), prestaties, inschrijvingen, doelen
-- en PR's. Bevat GEEN namen of master_ids: een atleet staat hier alleen als
-- pseudoniem (atleet_ref), berekend met pseudoniem(master_id, 'prestaties')
-- uit init_db.py.
--
-- Samengevoegd: dit is versie 1 + de migraties 002 t/m 004, zodat een nieuwe
-- installatie niet alle oude stappen hoeft te doorlopen. Een database die
-- ouder is dan versie 4 kan deze AVS niet meer bijwerken (init_db.basisversie()).
-- De volgorde van de kolommen is gelijk aan die van een bijgewerkte database
-- (toegevoegde kolommen staan achteraan); houd dat zo.
-- Latere wijzigingen NIET hier, maar in migrations/prestaties/NNN_beschrijving.sql
-- (vanaf 005).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- windmeting: 1 = dit onderdeel heeft windmeting (sprints t/m 200 m, horden
-- t/m 200 m, verspringen en hinkstapspringen), zie heeft_windmeting() in
-- src/models/prestatie.py.
CREATE TABLE IF NOT EXISTS onderdeel (
    id              INTEGER PRIMARY KEY,
    naam            TEXT NOT NULL UNIQUE,      -- bijv. '100m', 'Verspringen', '60m horden 76,2cm'
    categorie       TEXT,                      -- sprint, horden, midden, springen, werpen, meerkamp
    eenheid         TEXT NOT NULL CHECK (eenheid IN ('tijd', 'afstand', 'hoogte', 'punten')),
    lager_is_beter  INTEGER NOT NULL,          -- 1 voor looponderdelen, 0 voor technische
    windmeting      INTEGER NOT NULL DEFAULT 0
);

-- indoor: indoor wordt geen wind gemeten. De prestaties op een indoorwedstrijd
-- nemen dat over (db/queries.py regelt dat).
CREATE TABLE IF NOT EXISTS wedstrijd (
    id          INTEGER PRIMARY KEY,
    naam        TEXT NOT NULL,
    datum       TEXT NOT NULL,                 -- ISO 'YYYY-MM-DD'
    locatie     TEXT,
    bron        TEXT CHECK (bron IN ('atletieknu', 'seltec', 'handmatig')),
    bron_url    TEXT UNIQUE,                   -- uitslagpagina van de wedstrijd, niet van een atleet
    indoor      INTEGER NOT NULL DEFAULT 0
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
    indoor          INTEGER NOT NULL DEFAULT 0,
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

-- ============================================================
-- Het tijdschema (chronoloog) van een wedstrijd.
--
-- Lang formaat: één rij per onderdeel in het tijdschema, bijv.
--   za 14 mrt  10:30  60m horden 76,2cm  Meisjes U16  serie  groep 2  20 min
-- Geen persoonsgegevens: het tijdschema hoort bij de wedstrijd. Wie wanneer
-- moet, volgt uit de inschrijvingen (zelfde database) en de categorie van de
-- atleet (personen.db); dat rekent wedstrijden/chronoloog.py uit en wordt
-- nooit opgeslagen.
--
-- onderdeel_id    het onderdeel uit de lijst (voor koppelen aan inschrijvingen);
--                 leeg als het onderdeel (nog) niet in de lijst staat.
-- onderdeel_tekst de naam zoals in het tijdschema; verplicht als onderdeel_id leeg is.
-- categorie       zoals in het tijdschema ('Meisjes U16', 'JU14'); leeg = voor iedereen.
-- ronde           'serie', 'finale', ... ('' als het niet van toepassing is).
-- groep           1e, 2e, ... groep van dit onderdeel; leeg = er is maar één groep.
-- duur            in minuten; leeg = onbekend.
-- ============================================================
CREATE TABLE IF NOT EXISTS wedstrijd_programma (
    id              INTEGER PRIMARY KEY,
    wedstrijd_id    INTEGER NOT NULL REFERENCES wedstrijd(id) ON DELETE CASCADE,
    datum           TEXT    NOT NULL CHECK (datum GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    starttijd       TEXT    NOT NULL CHECK (length(starttijd) = 5
                                            AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]' AND starttijd <= '23:59'),
    duur            INTEGER CHECK (duur IS NULL OR duur BETWEEN 1 AND 720),
    onderdeel_id    INTEGER REFERENCES onderdeel(id) ON DELETE SET NULL,
    onderdeel_tekst TEXT,
    categorie       TEXT,
    ronde           TEXT    NOT NULL DEFAULT '',
    groep           INTEGER CHECK (groep IS NULL OR groep >= 1),
    opmerking       TEXT,
    CHECK (onderdeel_id IS NOT NULL OR length(trim(coalesce(onderdeel_tekst, ''))) > 0)
);
CREATE INDEX IF NOT EXISTS idx_programma_wedstrijd ON wedstrijd_programma(wedstrijd_id, datum, starttijd);
CREATE INDEX IF NOT EXISTS idx_programma_onderdeel ON wedstrijd_programma(onderdeel_id);

-- ============================================================
-- Doelen voor een groep of een atleet, meestal bij een wedstrijd.
--
-- doel: wat willen we bereiken, en wanneer / bij welke wedstrijd.
--   groep_id verwijst naar personen.db: groep(id) (geen persoonsgegeven; SQLite
--   kan het tussen bestanden niet afdwingen, db/queries.py controleert het).
--   groep_id NULL = persoonlijk doel van één atleet.
--   datum NULL = de datum van de wedstrijd.
-- doel_regel: wat precies, en voor wie. atleet_ref = pseudoniem(master_id,
--   'prestaties'), zoals in prestatie; NULL = de hele groep.
--   soort 'prestatie': onderdeel + streefwaarde (seconden/meters/punten, zoals
--   prestatie.waarde; beter = onderdeel.lager_is_beter).
--   soort 'leerdoel': leerdoel_id (leerlijnen.db) + streefwaarde = score 1-5.
--   soort 'vrij': alleen een omschrijving.
--   Of een regel behaald is, rekent de app uit; beoordeling (met de hand) gaat voor.
--
-- titel, beschrijving, omschrijving en evaluatie zijn vrije tekst: feitelijk
-- houden, geen namen van andere atleten, geen diagnoses (zoals bij notities).
-- ============================================================
CREATE TABLE IF NOT EXISTS doel (
    id            INTEGER PRIMARY KEY,
    groep_id      INTEGER,
    titel         TEXT    NOT NULL,
    wedstrijd_id  INTEGER REFERENCES wedstrijd(id) ON DELETE SET NULL,
    startdatum    TEXT    NOT NULL DEFAULT (date('now')),
    datum         TEXT,
    beschrijving  TEXT,
    evaluatie     TEXT,
    aangemaakt_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS doel_regel (
    id           INTEGER PRIMARY KEY,
    doel_id      INTEGER NOT NULL REFERENCES doel(id) ON DELETE CASCADE,
    atleet_ref   TEXT    CHECK (atleet_ref IS NULL OR length(atleet_ref) = 32),
    soort        TEXT    NOT NULL CHECK (soort IN ('prestatie', 'leerdoel', 'vrij')),
    onderdeel_id INTEGER REFERENCES onderdeel(id),
    leerdoel_id  TEXT,
    streefwaarde REAL,
    omschrijving TEXT,
    beoordeling  TEXT    CHECK (beoordeling IN ('behaald', 'deels', 'niet')),
    CHECK (soort <> 'prestatie' OR (onderdeel_id IS NOT NULL AND streefwaarde IS NOT NULL)),
    CHECK (soort <> 'leerdoel'  OR (leerdoel_id  IS NOT NULL AND streefwaarde IS NOT NULL)),
    CHECK (soort <> 'vrij'      OR omschrijving IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_doel_groep      ON doel(groep_id);
CREATE INDEX IF NOT EXISTS idx_doel_regel_doel ON doel_regel(doel_id);
CREATE INDEX IF NOT EXISTS idx_doel_regel_atl  ON doel_regel(atleet_ref);

-- ============================================================
-- PR per atleet per onderdeel (afgeleid, dus geen aparte tabel nodig).
-- Alleen windlegale prestaties tellen (World Athletics):
--   * Bij onderdelen MET windmeting telt een prestatie alleen als de wind
--     gemeten is en hoogstens +2,0 m/s was; zonder windmeting telt hij niet.
--   * Bij alle andere onderdelen telt elke prestatie.
--   * Indoor wordt geen wind gemeten: een indoorprestatie telt altijd.
-- ============================================================
CREATE VIEW IF NOT EXISTS pr AS
SELECT  p.atleet_ref,
        p.onderdeel_id,
        CASE WHEN o.lager_is_beter = 1 THEN MIN(p.waarde) ELSE MAX(p.waarde) END AS waarde
FROM prestatie p
JOIN onderdeel o ON o.id = p.onderdeel_id
WHERE o.windmeting = 0
   OR p.indoor = 1
   OR (p.wind IS NOT NULL AND p.wind <= 2.0)
GROUP BY p.atleet_ref, p.onderdeel_id;

INSERT INTO schema_version (versie) VALUES (4);
