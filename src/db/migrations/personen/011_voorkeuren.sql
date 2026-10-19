-- personen.db, migratie 011: voorkeuren van atleten voor ploegopstellingen.
--
-- atleet_voorkeur: een vaste voorkeur van een atleet voor alle ploegen.
--   onderdeel = naam zoals in de regelbestanden en bij atletiek.nu, zonder
--   specificatie ('800 meter', '80 meter horden', 'Kogelstoten', '4 x 80 meter'),
--   zodat hij geldt in elke competitie en elke leeftijdscategorie.
-- ploeg_voorkeur: voor één ploeg (één wedstrijd), per programmasleutel uit het
--   regelbestand ('800m', 'kogelstoten'). Gaat voor de vaste voorkeur;
--   'neutraal' zet een vaste voorkeur voor deze ploeg uit.
--
-- voorkeur: 'voorkeur' (doet dit graag: de optimalisatie geeft het waar het geen
-- punten kost), 'wil_niet' (nooit inplannen), 'moet' (altijd inplannen als de
-- atleet meedoet).
-- Persoonsgegevens: alleen master_id's, net als de rest van personen.db.

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
