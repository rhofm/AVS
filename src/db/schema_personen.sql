-- Atleet Volg Systeem - personen.db, basisschema (versie 11)
-- Alles wat direct naar een persoon wijst: persoonsgegevens, groepen,
-- trainingen, periodisering, roosters, leerlijnen en ploegen.
-- Wordt uitgevoerd door init_db.py op een lege database.
--
-- Samengevoegd: dit is versie 1 + de migraties 002 t/m 011, zodat een nieuwe
-- installatie niet alle oude stappen hoeft te doorlopen. Een database die
-- ouder is dan versie 11 kan deze AVS niet meer bijwerken (init_db.basisversie()).
-- De volgorde van de kolommen is gelijk aan die van een bijgewerkte database
-- (toegevoegde kolommen staan achteraan); houd dat zo.
-- Latere wijzigingen NIET hier, maar in migrations/personen/NNN_beschrijving.sql
-- (vanaf 012).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Atleet
-- master_id is een willekeurige id (32 hex-tekens, zie nieuw_master_id()).
-- Hij is NIET afgeleid van naam, geboortedatum of bondsnummer.
-- In de andere databases staat nooit de master_id zelf, alleen een
-- pseudoniem dat met de hoofdsleutel uit de master_id wordt berekend.
--
-- au_licentienummer: licentienummer van de Atletiekunie (AU). Optioneel (NULL =
-- niet bekend of geen licentie). Alleen cijfers; db/queries.py en
-- atleten/nieuw.py controleren dat. Uniek (meerdere NULL's mag wel).
-- Persoonsgegeven: staat daarom alleen in personen.db, net als naam en atletiek.nu-id.
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
    aangemaakt_op   TEXT NOT NULL DEFAULT (datetime('now')),
    au_licentienummer TEXT             -- licentienummer Atletiekunie, zie boven
);
CREATE UNIQUE INDEX IF NOT EXISTS atleet_au_licentienummer ON atleet (au_licentienummer);

-- ============================================================
-- Groepen
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

-- Trainingstijden per groep: één rij per groep, per weekdag de begintijd
-- ('HH:MM', 24 uur) of leeg (NULL) = de groep traint die dag niet. Een groep
-- zonder rij heeft (nog) geen vaste trainingsdagen; de app leidt ze dan af uit
-- de trainingen of de trainingsschema's. Geen persoonsgegevens.
CREATE TABLE IF NOT EXISTS groep_trainingstijden (
    groep_id  INTEGER PRIMARY KEY REFERENCES groep(id) ON DELETE CASCADE,
    maandag   TEXT CHECK (maandag IS NULL OR (length(maandag) = 5 AND maandag GLOB '[0-2][0-9]:[0-5][0-9]' AND maandag <= '23:59')),
    dinsdag   TEXT CHECK (dinsdag IS NULL OR (length(dinsdag) = 5 AND dinsdag GLOB '[0-2][0-9]:[0-5][0-9]' AND dinsdag <= '23:59')),
    woensdag  TEXT CHECK (woensdag IS NULL OR (length(woensdag) = 5 AND woensdag GLOB '[0-2][0-9]:[0-5][0-9]' AND woensdag <= '23:59')),
    donderdag TEXT CHECK (donderdag IS NULL OR (length(donderdag) = 5 AND donderdag GLOB '[0-2][0-9]:[0-5][0-9]' AND donderdag <= '23:59')),
    vrijdag   TEXT CHECK (vrijdag IS NULL OR (length(vrijdag) = 5 AND vrijdag GLOB '[0-2][0-9]:[0-5][0-9]' AND vrijdag <= '23:59')),
    zaterdag  TEXT CHECK (zaterdag IS NULL OR (length(zaterdag) = 5 AND zaterdag GLOB '[0-2][0-9]:[0-5][0-9]' AND zaterdag <= '23:59')),
    zondag    TEXT CHECK (zondag IS NULL OR (length(zondag) = 5 AND zondag GLOB '[0-2][0-9]:[0-5][0-9]' AND zondag <= '23:59'))
);

-- Extra begintijden op een weekdag, naast de vaste begintijd in
-- groep_trainingstijden (bijv. zaterdag 09:00 staat daar, 10:30 hier). Eén rij
-- per extra tijd. Een dag heeft alleen extra tijden als hij ook een vaste
-- begintijd heeft; dat controleert db/queries.py. Geen persoonsgegevens.
CREATE TABLE IF NOT EXISTS groep_extra_trainingstijd (
    groep_id  INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    dag       TEXT    NOT NULL CHECK (dag IN ('maandag', 'dinsdag', 'woensdag', 'donderdag',
                                              'vrijdag', 'zaterdag', 'zondag')),
    starttijd TEXT    NOT NULL CHECK (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]'
                                      AND starttijd <= '23:59'),
    PRIMARY KEY (groep_id, dag, starttijd)
);

-- ============================================================
-- Periodeplan (VEROUDERD, altijd leeg)
-- Vervangen door de periodisering hieronder en door `doel` in prestaties.db.
-- De tabel en training.periodeplan_id blijven bestaan: training verwijst
-- ernaar, en zonder de tabel weigert SQLite elke nieuwe training. Weghalen kan
-- alleen door training opnieuw op te bouwen (in een eigen migratie).
-- Nooit naar schrijven.
-- ============================================================
CREATE TABLE IF NOT EXISTS periodeplan (
    id          INTEGER PRIMARY KEY,
    groep_id    INTEGER REFERENCES groep(id) ON DELETE CASCADE,
    naam        TEXT NOT NULL,
    startdatum  TEXT NOT NULL,
    einddatum   TEXT NOT NULL,
    doel        TEXT
);

-- ============================================================
-- Roosters (geplande trainingsinhoud per week), optioneel per groep.
--
-- rooster: een sjabloon van `aantal_weken` weken; kan door meer groepen en in
--   een volgend seizoen opnieuw worden gebruikt.
-- rooster_regel: wat er in week n op een dag (en begintijd) wordt gedaan: dezelfde
--   tekstvelden als een training. starttijd NULL = de vaste (eerste) begintijd van
--   die dag; een andere tijd is voor een extra training op die dag. Weeknummers
--   tellen vanaf de start van het rooster, los van de mesocyclus.
--   De UNIQUE telt een lege starttijd niet als gelijk; db/queries.py voorkomt dubbele regels.
-- groep_rooster: welk rooster een groep volgt vanaf welke datum (begin van week 1).
--   Zelfde regel als de periodisering: geldt tot de volgende koppeling van de groep.
--   herhalen 1 = na de laatste week weer week 1; 0 = één keer, daarna niets.
--   einddatum (optioneel) = harde stop.
-- Geen persoonsgegevens.
-- ============================================================
CREATE TABLE IF NOT EXISTS rooster (
    id           INTEGER PRIMARY KEY,
    naam         TEXT    NOT NULL,
    aantal_weken INTEGER NOT NULL CHECK (aantal_weken BETWEEN 1 AND 60)
);

CREATE TABLE IF NOT EXISTS rooster_regel (
    id           INTEGER PRIMARY KEY,
    rooster_id   INTEGER NOT NULL REFERENCES rooster(id) ON DELETE CASCADE,
    week         INTEGER NOT NULL CHECK (week >= 1),
    dag          TEXT    NOT NULL CHECK (dag IN ('maandag', 'dinsdag', 'woensdag', 'donderdag',
                                                 'vrijdag', 'zaterdag', 'zondag')),
    starttijd    TEXT    CHECK (starttijd IS NULL OR (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]'
                                                      AND starttijd <= '23:59')),
    onderwerp    TEXT,
    warming_up   TEXT,
    kern_a       TEXT,
    kern_b       TEXT,
    cooling_down TEXT,
    notities     TEXT,
    UNIQUE (rooster_id, week, dag, starttijd)
);
CREATE INDEX IF NOT EXISTS idx_rooster_regel_rooster ON rooster_regel(rooster_id);

CREATE TABLE IF NOT EXISTS groep_rooster (
    groep_id   INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    rooster_id INTEGER NOT NULL REFERENCES rooster(id) ON DELETE CASCADE,
    startdatum TEXT    NOT NULL CHECK (length(startdatum) = 10 AND startdatum GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    herhalen   INTEGER NOT NULL DEFAULT 1 CHECK (herhalen IN (0, 1)),
    einddatum  TEXT    CHECK (einddatum IS NULL OR einddatum >= startdatum),
    PRIMARY KEY (groep_id, startdatum)
) WITHOUT ROWID;

-- ============================================================
-- Trainingen
--
-- Tekstvelden (warming_up, kern_a, kern_b, cooling_down, notities): vrije,
-- meerregelige tekst. Markdown mag (**vet**, *schuin*, '- ' lijstjes, '# ' kopjes);
-- de app toont het opgemaakt. Leeg (NULL) = niet ingevuld.
--
-- Afwijkende training: een rij met hoofdtraining_id = de gewone training van
-- de groep (zelfde groep en datum). Welke atleten die volgen staat in
-- training_atleet (lang formaat, één rij per atleet). De gewone training
-- (hoofdtraining_id leeg) heeft geen rijen in training_atleet: die geldt voor
-- de rest van de groep. Aanwezigheid hoort altijd bij de gewone training
-- (absentie.db).
--
-- starttijd: de begintijd van deze training ('HH:MM'). Nodig om twee
-- trainingen van dezelfde groep op dezelfde datum uit elkaar te houden. Leeg
-- (NULL) = de vaste begintijd van die dag.
--
-- rooster_regel_id: uit welke roosterregel de inhoud is gekopieerd. NULL = niet
-- (of niet meer) uit het rooster: met de hand ingevuld of aangepast. Alleen
-- trainingen die nog naar een regel wijzen, worden bijgewerkt als het rooster
-- verandert; trainingen in het verleden nooit.
--
-- periodeplan_id: verouderd, altijd NULL (zie periodeplan hierboven).
-- ============================================================
CREATE TABLE IF NOT EXISTS training (
    id               INTEGER PRIMARY KEY,
    groep_id         INTEGER NOT NULL REFERENCES groep(id) ON DELETE CASCADE,
    periodeplan_id   INTEGER REFERENCES periodeplan(id) ON DELETE SET NULL,
    datum            TEXT NOT NULL,
    onderwerp        TEXT,
    warming_up       TEXT,
    kern_a           TEXT,
    kern_b           TEXT,
    cooling_down     TEXT,
    notities         TEXT,
    hoofdtraining_id INTEGER REFERENCES training(id) ON DELETE CASCADE,
    starttijd        TEXT
                     CHECK (starttijd IS NULL OR (length(starttijd) = 5 AND starttijd GLOB '[0-2][0-9]:[0-5][0-9]'
                                                  AND starttijd <= '23:59')),
    rooster_regel_id INTEGER REFERENCES rooster_regel(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_training_hoofd ON training(hoofdtraining_id);

CREATE TABLE IF NOT EXISTS training_atleet (
    training_id INTEGER NOT NULL REFERENCES training(id) ON DELETE CASCADE,
    atleet_id   TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    PRIMARY KEY (training_id, atleet_id)
);

-- ============================================================
-- Periodisering van een groep (megacyclus en mesocyclus).
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
-- ============================================================
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

-- ============================================================
-- Leerlijnen (VEROUDERD: vervangen door leerlijnen.db en leerdoelscores.db;
-- de oude Opslag.leerlijn*/voortgang*-methodes gebruiken ze nog)
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
-- Ploegen (competitie), zie docs/Ploegopstelling_ontwerp.md.
-- wedstrijd_id verwijst naar prestaties.db. SQLite kan geen foreign keys
-- tussen bestanden afdwingen; de Python-code controleert ze.
--
-- ploeg:
--   regelset        bestandsnaam in config/ploeg_regels/ (competitie = naam uit dat bestand)
--   categorie       ploeg in het regelbestand, bijv. 'U16-V'
--   programma       welke wedstrijd van de competitie, bijv. 'wedstrijd_2' of 'finale_2027'
--   datum           wedstrijddag 'YYYY-MM-DD' (ook zonder gekoppelde wedstrijd; voor de
--                   categorie van de atleten en 'één ploeg per dag')
--   prestatiebasis  'seizoen' (huidig + vorig seizoen), 'pr' of '12mnd'
--
-- ploeg_lid: wie op het inschrijfformulier staat, als deelnemer of reserve, en of de
--   atleet de hele dag of een dagdeel kan.
--
-- ploeg_opstelling: onderdeel = de programmasleutel uit het regelbestand
--   ('80mH', 'kogelstoten', '4x80m'). Welk onderdeel (met specificatie) dat bij de
--   prestaties is, hangt af van de ploeg en volgt uit het regelbestand. Een regel kan
--   alleen bestaan voor een lid van de ploeg (foreign key naar ploeg_lid).
--
-- atleet_voorkeur: een vaste voorkeur van een atleet voor alle ploegen.
--   onderdeel = naam zoals in de regelbestanden en bij atletiek.nu, zonder
--   specificatie ('800 meter', '80 meter horden', 'Kogelstoten', '4 x 80 meter'),
--   zodat hij geldt in elke competitie en elke leeftijdscategorie.
-- ploeg_voorkeur: voor één ploeg (één wedstrijd), per programmasleutel uit het
--   regelbestand ('800m', 'kogelstoten'). Gaat voor de vaste voorkeur;
--   'neutraal' zet een vaste voorkeur voor deze ploeg uit.
--   voorkeur: 'voorkeur' (doet dit graag: de optimalisatie geeft het waar het geen
--   punten kost), 'wil_niet' (nooit inplannen), 'moet' (altijd inplannen als de
--   atleet meedoet).
-- Persoonsgegevens: alleen master_id's, net als de rest van personen.db.
-- ============================================================
CREATE TABLE IF NOT EXISTS ploeg (
    id             INTEGER PRIMARY KEY,
    naam           TEXT NOT NULL,
    competitie     TEXT,
    wedstrijd_id   INTEGER,                     -- prestaties.db: wedstrijd(id)
    regelset       TEXT,                        -- bestandsnaam in config/ploeg_regels/
    strategie      TEXT,                        -- welke 'mentaliteit' is gebruikt
    aangemaakt_op  TEXT NOT NULL DEFAULT (datetime('now')),
    categorie      TEXT,
    programma      TEXT,
    datum          TEXT,
    prestatiebasis TEXT NOT NULL DEFAULT 'seizoen'
);
CREATE INDEX IF NOT EXISTS idx_ploeg_datum ON ploeg (datum);

CREATE TABLE IF NOT EXISTS ploeg_lid (
    ploeg_id    INTEGER NOT NULL REFERENCES ploeg(id) ON DELETE CASCADE,
    atleet_id   TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    rol         TEXT    NOT NULL DEFAULT 'deelnemer' CHECK (rol IN ('deelnemer', 'reserve')),
    beschikbaar TEXT    NOT NULL DEFAULT 'hele_dag' CHECK (beschikbaar IN ('hele_dag', 'ochtend', 'middag')),
    PRIMARY KEY (ploeg_id, atleet_id)
);

CREATE TABLE IF NOT EXISTS ploeg_opstelling (
    ploeg_id   INTEGER NOT NULL,
    atleet_id  TEXT    NOT NULL,
    onderdeel  TEXT    NOT NULL,                  -- programmasleutel uit het regelbestand
    groep      INTEGER CHECK (groep IS NULL OR groep >= 1),   -- groep bij een technisch onderdeel
    vast       INTEGER NOT NULL DEFAULT 0,        -- vastgezet door de trainer
    PRIMARY KEY (ploeg_id, atleet_id, onderdeel),
    FOREIGN KEY (ploeg_id, atleet_id) REFERENCES ploeg_lid (ploeg_id, atleet_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS atleet_voorkeur (
    atleet_id  TEXT NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    onderdeel  TEXT NOT NULL,
    voorkeur   TEXT NOT NULL CHECK (voorkeur IN ('voorkeur', 'wil_niet', 'moet')),
    PRIMARY KEY (atleet_id, onderdeel)
);

CREATE TABLE IF NOT EXISTS ploeg_voorkeur (
    ploeg_id   INTEGER NOT NULL REFERENCES ploeg(id) ON DELETE CASCADE,
    atleet_id  TEXT    NOT NULL REFERENCES atleet(master_id) ON DELETE CASCADE,
    onderdeel  TEXT    NOT NULL,                  -- programmasleutel uit het regelbestand
    voorkeur   TEXT    NOT NULL CHECK (voorkeur IN ('voorkeur', 'wil_niet', 'moet', 'neutraal')),
    PRIMARY KEY (ploeg_id, atleet_id, onderdeel)
);

INSERT INTO schema_version (versie) VALUES (11);
