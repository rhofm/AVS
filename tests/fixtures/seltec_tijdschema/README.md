# Fixtures: Seltec tijdschema, geanonimiseerd

Ingekorte kopieën van de pagina `https://uitslagen.atletiek.nl/Competitions/Details/<id>`
('Tijdschema'), voor de tests van `src/importers/seltec_tijdschema.py`. Een tijdschema
bevat geen atleten; alleen wedstrijdnaam en plaats zijn vervangen:

| Bestand        | Wedstrijd                                          | Plaats    |
|----------------|----------------------------------------------------|-----------|
| `nk_dag1.html` | `Test Kampioenschappen U18 & U20`, dag 1 van 3     | Teststad  |
| `nk_dag2.html` | idem, dag 2                                        | Teststad  |
| `club.html`    | `Testclubkampioenschappen 2026` (één dag)          | Proefdorp |

Scripts, stijlen, logo's, de tab 'Blokindeling' en de meeste regels zijn verwijderd. De
structuur die de importer leest is intact:

* `h1`: '18 - 20 sep 2026 Naam - Plaats' (eerste en laatste dag).
* `#EventMenuHeader`: bij een meerdaagse wedstrijd 'Dag 1', 'Dag 2', ... met links
  `/Competitions/Details/<id>/<dag>`; de getoonde dag heeft class `selected`.
* `table.roundlisttimetable` > `tbody tr`: vier cellen, elk met een link naar
  `/Competitions/CurrentList/<lijst>/<id>` en daarin `<div>`-regels:
  tijd | onderdeel / ronde | categorieën / '(6 Series, 43 Atleten)' | status.

## Verwachte uitkomsten

```
nk_dag1 -> 8 regels op 18-09-2026; 14:00 100 m Series U20M -> categorie 'U20-M', opmerking '6 series, 43 atleten'
nk_dag2 -> 6 regels op 19-09-2026; 11:00 Verspringen Kwalificatie U18M -> ronde 'kwalificatie', '2 groepen, 27 atleten'
club    -> 8 regels op 10-10-2026; 'U18M, U16J' -> 'U18-M, U16-M'; 'U16M, U14J' -> 'U16-V, U14-M';
           ronde 'Meerkamp' -> geen ronde, opmerking begint met 'meerkamp'
```

Seltec: bij U18, U20, senioren en masters is M = mannen en V = vrouwen; bij U16 en jonger
J = jongens en M = meisjes. Gecontroleerd met de tab 'Blokindeling' van de echte pagina's
('100 m U18M, U16J' staat bij de mannen, '80 m U16M, U14J' bij mixed).
