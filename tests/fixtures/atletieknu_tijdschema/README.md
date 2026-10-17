# Fixtures: atletiek.nu tijdschema (chronoloog), geanonimiseerd

Ingekorte kopieën van de pagina `https://www.atletiek.nu/wedstrijd/chronoloog/<id>/`,
voor de tests van `src/importers/atletieknu_tijdschema.py`. Een tijdschema bevat geen
atleten; alleen wedstrijdnaam en plaats zijn vervangen:

| Bestand         | Wedstrijd                                  | Plaats    |
|-----------------|--------------------------------------------|-----------|
| `meerkamp.html` | `Testmeerkamp 2026` (twee dagen)           | Proefdorp |
| `teams.html`    | `Test Teamwedstrijd 2026` (één dag)        | Teststad  |

Scripts, menu's, zoekbalk, knoppen ('Uitslagen'), vlaggen en de tab 'per groep' zijn
verwijderd; per dag zijn alleen de eerste regels bewaard. De structuur die de importer
leest is intact:

* `div#day<N>chronologischtab` > `table.chronoloogtabel`: één regel per onderdeel per
  startgroep. Kolommen: tijd (link-tekst, `n/a` = geen tijd), startgroep (categorie, soms
  met `groep A`/`groep B`), onderdeel (code in `.visible-xs-inline`, naam in `.hidden-xs`),
  met eronder in grijs het aantal series (`2 series`) of de plek (`hoog 1`, `ver 2`).
* `div#day<N>visueeltab` (alleen bij `meerkamp.html`): tijdlijn met per onderdeel een balk
  `title="10:55 - 11:10<br>80mH"` en een `onclick` naar dezelfde startlijst-URL als de regel
  in de lijst. Daaruit komt de duur. In de kop staat de datum van die dag.

## Verwachte uitkomsten

```
meerkamp -> 15 regels: 9 op za 29-08-2026, 6 op zo 30-08-2026
meerkamp, 10:55 80mH VU20+V Masters -> duur 15, opmerking "2 series", categorie "VU20+V Masters"
meerkamp, 11:05 Hoog SEN-V          -> duur 65, opmerking "hoog 1"
meerkamp, zo 9:15 80mH en 110mH MU20 -> geen balk in de tijdlijn: duur onbekend (2 regels)
teams    -> 7 regels (de reserve-regel met tijd n/a valt weg)
teams, 11:46 Hoog "Vrouwen groep A" -> categorie "Vrouwen", groep 1
teams, 14:49 Ver "Mannen groep B"   -> categorie "Mannen", groep 2; geen tijdlijn: duur onbekend
```
