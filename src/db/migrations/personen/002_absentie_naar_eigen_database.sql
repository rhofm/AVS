-- personen.db, migratie 002: absentie verhuist naar absentie.db.
--
-- De absentie (met de status 'blessure', een gezondheidsgegeven) stond hier
-- direct naast de namen. Voortaan staat hij gepseudonimiseerd in absentie.db.
--
-- Deze migratie hernoemt de oude tabel alleen. init_db.py kopieert daarna de
-- rijen naar absentie.db (met het pseudoniem in plaats van de master_id) en
-- verwijdert de oude tabel pas als dat gelukt is. Er gaan dus geen gegevens
-- verloren, ook niet als het halverwege misgaat: dan gaat het bij de volgende
-- start verder.

ALTER TABLE absentie RENAME TO absentie_te_verplaatsen;
