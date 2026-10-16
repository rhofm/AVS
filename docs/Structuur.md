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



## Groepen

* Functionaliteit om atleten te combineren tot groep
* Absentie tool: lijst per training, vooraf ingevuld met 'aanwezig' volgens het trainingsschema; trainer past alleen de uitzonderingen aan
* Tool voor opstellen periodeplannen en dergelijke op basis van tijd in jaar en leerlijnen



## Leerlijnen

* Leerlijnen integreren en volgbaar maken
* Per atleet in te stellen waar ze zitten



## UI

* Makkelijk rond te klikken
* Zeer uitgebreide achterkant



## ?

*