-- prestaties.db, migratie 003: het tijdschema (chronoloog) van een wedstrijd.
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
