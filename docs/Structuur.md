# Structuur \&  Features Atleet Volg Systeem



## Atleet

* Persoonsgegevens (Naam, Geslacht, Leeftijd/Geboortejaar/Geboortedatum, ...)
* PR's
* Specialisatie (?)
* Testresultaten
* Trainingsschema: op welke dagen van de week de atleet traint
* Geplande/verwachte prestaties (?) (eigen database?)



## Resultaten importeren

* Geef link
* Versie voor PRs van atletiek.nu
* Versie voor wedstrijd van atletiek.nu
* Versie voor wedstrijd van seltec
* Automatische detectie welke versie te gebruiken
* Zoekfunctie op club voor atletiek.nu?



## Databases

* Gemaakt voor SQL, versleuteld met SQLCipher
* Wat staat waar:
  * personen.db: persoonsgegevens, groepen, trainingen, periodeplannen, leerlijnen, ploegen
  * prestaties.db: onderdelen, wedstrijden, prestaties, PR's
  * testen.db: testen en testresultaten
  * trainingsschema.db: per atleet een kolom per weekdag (maandag t/m zondag) of hij/zij die dag traint
  * leerlijnen.db: leerlijnen en leerdoelen van de club (Leerlijn baanatletiek jeugd NA), aangevuld met de Atletiekunie-leerlijnen (dec 2013), per categorie U10 t/m U20, elk met een vaste id (bijv. SPR-U10-01). Geen persoonsgegevens
  * leerdoelscores.db: lang formaat, één rij per atleet per leerdoel per datum met een score 1-5. Het overzicht atleten x leerdoelen (breed) wordt berekend, niet opgeslagen
  * absentie.db: lang formaat, één rij per atleet per training met status (aanwezig, afgemeld, afwezig, blessure) en korte reden. Apart omdat blessures gezondheidsgegevens zijn
* Elke atleet krijgt een willekeurige master\_id in personen.db; in de andere databases staat een eigen pseudoniem per database
* Eén hoofdsleutel in de sleutelkluis van Windows, met herstelsleutel als back-up
* ~~Functies die database kunnen initialiseren (want niet in github)~~ Gedaan: src/db/init\_db.py



## Ploeg

* Functie voor vergelijken prs/prestaties van groep atleten
* Testfunctie voor chronoloog
* Makkelijk aan te passen
* Verschillende 'mentaliteiten' van ploegenopstelling
* Opstellingsregels makkelijk aan te passen voor de ploegleider



## Wedstrijden

* Komende wedstrijden plannen: datum, naam, locatie, link naar de wedstrijdpagina
* Per atleet inschrijven voor één of meer onderdelen (of 'gaat mee, onderdelen volgen later'), en afmelden
* Overzicht van komende wedstrijden met deelnemers, ook per onderdeel (handig voor ploegen)
* Geplande wedstrijd en uitslag zijn dezelfde wedstrijd: importeer je later de uitslag via dezelfde link, dan komen de prestaties erbij
* Staat in prestaties.db (tabellen wedstrijd en inschrijving), geen aparte database



## Groepen

* Functionaliteit om atleten te combineren tot groep
* Absentie tool: lijst per training, vooraf ingevuld met 'aanwezig' volgens het trainingsschema; trainer past alleen de uitzonderingen aan
* Tool voor opstellen periodeplannen en dergelijke op basis van tijd in jaar en leerlijnen



## Leerlijnen

* ~~Leerlijnen integreren en volgbaar maken~~ Gedaan: leerlijnen.db (215 leerdoelen) + leerdoelscores.db
* Per atleet per leerdoel een score 1-5 met datum; geschiedenis blijft bewaard
* Nog te doen: scherm om een hele groep in één keer te scoren, voortgangsgrafiek per atleet



## UI

* Makkelijk rond te klikken
* Zeer uitgebreide achterkant



## ?

*
