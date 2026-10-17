# Structuur \&  Features Atleet Volg Systeem



## Atleet

* Persoonsgegevens (Naam, Geslacht, Leeftijd/Geboortejaar/Geboortedatum, ...)
* PR's
* Specialisatie (?)
* Testresultaten
* Trainingsschema: op welke dagen van de week de atleet traint
* Notities: vrije tekst per atleet per datum (wat opviel op training of wedstrijd), zoekbaar op tekst en datum
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
  * notities.db: één rij per notitie (atleet, datum, tekst zonder lengtegrens). Feitelijk houden: de tekst zelf is alleen versleuteld, niet gepseudonimiseerd
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
* Pagina 'Wedstrijden': komende wedstrijden (datum, naam, locatie, aantal atleten); afgelopen wedstrijden verborgen onder het vinkje 'Afgelopen wedstrijden', met of de uitslag al is geïmporteerd
* Nog te doen: formulier achter de knop '+ Nieuwe wedstrijd' (/wedstrijden/nieuw)
* Geplande wedstrijd en uitslag zijn dezelfde wedstrijd: importeer je later de uitslag via dezelfde link, dan komen de prestaties erbij
* Staat in prestaties.db (tabellen wedstrijd en inschrijving), geen aparte database



## Groepen

* Functionaliteit om atleten te combineren tot groep; een atleet kan in meerdere groepen zitten (groep_lid: één rij per atleet per groep)
* Trainingstijden per groep (tabel groep_trainingstijden): één rij per groep met de groep-id en per weekdag een begintijd of leeg (= geen training). Elke trainingsdag heeft een begintijd. De id is intern, de naam is wat de app toont
* Lid worden van een groep vult de trainingsdagen van de groep aan in het trainingsschema van de atleet; per atleet blijft het aan te passen
* Weekrooster per atleet over al zijn groepen (dag, tijd, groep)
* Tijden invullen: bij 'Nieuwe groep' en 'Wijzigen' op de groepspagina
* Nog te doen: weekrooster tonen op de atleetpagina
* Absentie tool: lijst per training, vooraf ingevuld met 'aanwezig' volgens het trainingsschema; trainer past alleen de uitzonderingen aan
* Tool voor opstellen periodeplannen en dergelijke op basis van tijd in jaar en leerlijnen
* Trainingen: per training groep, datum, warming-up, kern A, kern B, cooling-down en notities. Tekstvelden met meerdere regels; eenvoudige markdown (**vet**, *schuin*, - lijstjes, # kopjes) wordt opgemaakt getoond
* Afwijkende training voor enkele atleten: een variant van de gewone training met eigen inhoud en een lijst atleten (één rij per atleet). Aanwezigheid blijft bij de gewone training
* Nog te doen: formulier om de inhoud van een training en de varianten in te vullen



## Leerlijnen

* ~~Leerlijnen integreren en volgbaar maken~~ Gedaan: leerlijnen.db (215 leerdoelen) + leerdoelscores.db
* Per atleet per leerdoel een score 1-5 met datum; geschiedenis blijft bewaard
* Nog te doen: scherm om een hele groep in één keer te scoren, voortgangsgrafiek per atleet



## UI

* Makkelijk rond te klikken
* Zeer uitgebreide achterkant



## ?

*
