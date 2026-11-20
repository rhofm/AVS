-- Groep die de trainer zelf voor een atleet bij een onderdeel heeft gekozen, bijv. 'Mannen|2'
-- (categorie zoals in het tijdschema, '|', groepsnummer). NULL = automatisch: de categorie van
-- de atleet bepaalt welke regel van het tijdschema bij hem hoort. Een gekozen groep gaat voor
-- op de categorie. Dit is een tekst uit het tijdschema, geen persoonsgegeven.
ALTER TABLE inschrijving ADD COLUMN tijdschema_groep TEXT;
