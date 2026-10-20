# Atleet Volg Systeem

## Ideeën \& Features

* Volgt atleten (PRs, prestaties, geplande wedstrijden, test resultaten, plaats in leerlijnen/ontwikkeling, ...)
* Iets dat de resultaten en prs van atletiek.nu en seltec importeert
* Feature voor het maken van competitieploegen
* Absentie feature voor groepen
* Ruimte voor plannen trainingsperiodes en trainingen
* Database bestanden in de .gitignore!!!! (ivm privacy van atleten)



## Link voor project:

\--

(Bouw elke feature in een losse branch, merge die in dev branch (development), merge die in staging (generale auditie), merge die in main (productie/gepubliceerd).
### Structuur
Dit staat in het [Structuur](docs/Structuur.md) bestand.

### Installeren (ontwikkelen)
In de conda-omgeving met Python 3.13, vanuit de root van de repo:

```
pip install -e .[dev]     # afhankelijkheden + pytest en PyInstaller
python -m pytest          # tests
python src                # AVS starten (opent de browser)
python src --zelftest     # controleren of alles werkt (ook: AVS.exe --zelftest)
python build.py           # de .exe bouwen: tests, bouwen, controle, zelftest -> dist/AVS.exe
```

Het plan voor de .exe staat in [Exe_bouwplan](docs/Exe_bouwplan.md).




## Opmerkingen

* Database management in SQL, verwerking in python
* Databases zijn versleuteld (SQLCipher) en gesplitst in acht bestanden: personen, prestaties, testen, trainingsschema, absentie, leerlijnen, leerdoelscores en notities
* Alleen in de personen-database staan namen; in de andere twee staat een atleet onder een pseudoniem
* **Bewaar de herstelsleutel!** (`python src/db/init_db.py --herstelsleutel`) Zonder die sleutel is alle data weg, bijv. na een nieuwe computer of herinstallatie van Windows
* Makkelijke User Interface (moet zonder terminal kunnen worden gebruikt) (bouwen in C++? of iets met HTML?)
* Het liefst met 1 command te compilen en dan als een .exe te runnen op locale machine
