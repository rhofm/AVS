-- Meerdaagse wedstrijden: laatste dag van de wedstrijd (ISO 'YYYY-MM-DD').
-- NULL = eendaags (alleen `datum`).
ALTER TABLE wedstrijd ADD COLUMN einddatum TEXT;
