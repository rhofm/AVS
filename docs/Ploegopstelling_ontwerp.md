# Ontwerp: ploegopstellingen voor de competitie

Ontwerp voor `src/ploeg/` en `config/ploeg_regels/`. Bronnen:
`Ploegopstellingen.md` (wensen), *Wedstrijdbepalingen Competitie 2026-2027*
(regels), *Formules & Constanten december 2025* (puntentelling) en de
Mastersploeg-spreadsheet (age grading).

## Besluiten

| Vraag | Besluit |
|-------|---------|
| Solver | `scipy.optimize.milp` (HiGHS). Zit in scipy, geen los binary nodig, werkt met PyInstaller. |
| Standaard prestatiebasis | Beste windlegale prestatie van het **huidige + vorige seizoen** (sluit aan bij bepaling 17.5). Per ploeg te wijzigen naar PR of laatste 12 maanden. |
| Athletics Champs | Valt **buiten** dit ontwerp (andere teamopbouw: 6-11 kinderen, iedereen doet alles, beste 5 tellen). |
| 1e divisie / NK Teams | Wél ondersteund. Daar telt punten naar plaats (18.1, 18.6); omdat we de tegenstanders niet kennen, optimaliseren we met **prestatiepunten (AU-senioren) als benadering**. De UI zegt dat erbij. |
| Opslag | Ploegen blijven in `personen.db` (`ploeg`, `ploeg_opstelling` + nieuwe tabellen, zie onder). |
| Regels en constanten | In YAML, zodat een ploegleider ze zonder code kan aanpassen. |

## Lagen

Elke laag weet niets van de lagen erboven en is los te testen.

```
config/puntentelling/au_2025.yaml   ← AU-constanten (data, geen code)
config/ploeg_regels/*.yaml          ← competitieregels per competitie + seizoen
        │
ploeg/punten.py        1. prestatie ↔ punten (pure rekenkunde)
ploeg/regels.py        2. YAML inlezen + opstelling controleren
ploeg/vergelijk.py     3. matrix atleten × onderdelen (prestatie / voorspelling → punten)
ploeg/voorspeller.py      └ vult gaten als er geen prestatie is
ploeg/opstelling.py    4. Opstelling: opslaan/laden, totalen
ploeg/optimaliseer.py     └ ILP-model; strategieen/ voegt doel + extra eisen toe
ploeg/export.py           └ csv voor atletiek.nu
```

## 1. Punten: `punten.py` + constanten als data

- Constanten staan in `config/puntentelling/au_2025.yaml`, één bestand per
  uitgave van *Formules & Constanten*. Nieuwe uitgave = nieuw bestand, geen
  codewijziging. Per tabel (`au_senioren`, `au_u14_u16`, `au_u12_klassiek`,
  `wa_meerkamp`) per geslacht per onderdeel: formuletype + constanten.
- Formuletypes:
  - `au_loop`: `INT(A / tijd - B)`
  - `au_techn`: `INT(A * sqrt(afstand) - B)`, met stukken:
    - vrouwen hoog ≤ 1,40 m andere A/B;
    - U14/U16 hoog ≤ 1,35 m: `INT((afstand - 0.67) * 733.33333 + 0.7)`;
    - U14/U16 ver ≤ 4,41 m: `INT((afstand - 1.91) * 200 + 0.5)`.
  - `wa_loop`: `INT(A * (B - tijd)^C)`, `wa_spring`: `INT(A * (100*(afstand - B))^C)`,
    `wa_werp`: `INT(A * (afstand - B)^C)`.
- Functies:
  - `punten(tabel, onderdeel, geslacht, prestatie, handtijd=False) -> int`:
    afkappen (`INT`, niet afronden), minimaal 0, handtijdcorrectie +0,24 s
    (t/m 300 m, horden daarover, estafettes t/m 4×80 m) of +0,14 s (400 m,
    400 m horden, 4×100 m).
  - `prestatie_voor(tabel, onderdeel, geslacht, punten) -> float`: de inverse,
    nodig voor de voorspeller. Alle formules zijn om te keren.
- Rekenen in `float` (dubbele precisie), zoals het document vraagt.
- **Masters**: AU-seniorenformule op de leeftijdsgecorrigeerde prestatie
  (bepaling 65.2). De factoren komen uit de Mastersploeg-spreadsheet in een
  databestand (`config/puntentelling/masters_agegrading.yaml`). Let op: de
  factoren in *Formules & Constanten* zijn voor masters-meerkampen (WA-tabel),
  niet voor de competitie. **Open punt:** factoren controleren tegen de
  spreadsheet.
- **Tests** (uit het document zelf):
  - U12 jongen 60 m handtijd 8,7 → 87 punten (Athletics Champs-formule; alleen
    als controle van de formule-engine);
  - mannen 100 m 11,5 s (AU-senioren) → 688 punten (zie spreadsheet);
  - grenzen van de stukken (hoog 1,35/1,40, ver 4,41) aan beide kanten.

## 2. Regels: één YAML per competitie per seizoen

Bestanden: `config/ploeg_regels/<competitie>_<seizoen>.yaml`, bijvoorbeeld
`u14_u16_2026.yaml`, `u18_u20_2026.yaml`, `masters_2026.yaml`,
`senioren_2026.yaml`, `nk_teams_2026.yaml`.

```yaml
naam: U14/U16-competitie
seizoen: 2026
puntentelling: au_2025/au_u14_u16
puntentoekenning: prestatie            # of 'plaats' (1e divisie, NK Teams)
algemeen:
  max_onderdelen_per_atleet: 3         # 4.1, inclusief estafettes
  max_reserves: 4                      # 9.3
  een_ploeg_per_dag: true              # 10.10
  tellend: {loop: 2, technisch: 1}     # 70 *): beste 2 bij lopen, beste 1 technisch
  een_atleet_per_groep: true           # 9.1, technische onderdelen in groepen
ploegen:
  U16-V:
    toegestaan: [U14-V, U16-V]         # wie mag in deze ploeg
    programma:
      wedstrijd_1: {80m: 3, 800m: 3, 80mH: 3, 4x80m: 1, hoog: 2, ver: 2, kogel: 2, discus: 2}
      wedstrijd_2: {150m: 3, 1500m: 3, 80mH: 3, 4x80m: 1, hoog: 2, ver: 2, kogel: 2, discus: 2, speer: 2}
      wedstrijd_3: {80m: 3, 800m: 3, 300mH: 3, 4x80m: 1, hoog: 2, ver: 2, kogel: 2, speer: 2}
      finale: {80m: 3, 1500m: 3, 80mH: 3, 4x80m: 1, hoog: 2, ver: 2, kogel: 2, speer: 2}
onderdelen:                            # programmasleutel → onderdeel in prestaties.db, per atleetcategorie
  kogel: {U14-V: "Kogelstoten 2kg", U16-V: "Kogelstoten 3kg"}
  80mH:  {U16-V: "80m horden 76,2cm"}
estafettes:
  4x80m: {benen: [80m, 80m, 80m, 80m], correctie_s: -1.2}
```

Waarom de `onderdelen`-koppeling: een U16 die in de U18/U20-ploeg uitkomt, of
een U18 met de 5 kg-kogel in een U18/U20-ploeg, vult **hetzelfde
programmaonderdeel** met een ander `onderdeel` (naam + specificatie).

Per competitie:

| Competitie | Bijzonderheden in de YAML |
|------------|---------------------------|
| U14/U16 | Aparte jongens-/meisjesploegen; lopen tellen beste 2, technisch beste 1; tabel `au_u14_u16` (zelfde voor jongens en meisjes). |
| U18/U20 | U16 mag als U18 meedoen (bepaling 4.5 slot); U18 eigen hordehoogte en werpmateriaal; 2000 m steeple alleen U18. Tabel `au_senioren`. |
| Masters | Aparte mannen-/vrouwenploegen; age grading; eigen werpmateriaal per leeftijdsklasse (65.1). Finale: één ploeg per vereniging per geslacht (62.3). |
| Senioren 2e/3e divisie | **Gemengd**: mannen- en vrouwenonderdelen in één ploeg, punten opgeteld (5, 18.5). Elk programmaonderdeel krijgt `geslacht`. 4×400 m gemengd = 2 M + 2 V. Geen U16 (4.5 slot). |
| 1e divisie / NK Teams | `puntentoekenning: plaats`; we optimaliseren met AU-seniorenpunten als benadering. NK Teams: 1 atleet per onderdeel. Eén ploeg per vereniging (10.2). |

`regels.py` laadt dit in een `Regelset`-dataclass en heeft
`controleer(opstelling) -> list[Overtreding]`. Dezelfde controle draait bij
handmatige opstellingen én op de uitkomst van de optimalisatie. Waarschuwingen
op seizoensniveau gebruiken de opgeslagen ploegen van hetzelfde jaar:

- 10.5: eerder uitgekomen in een hogere divisie (uitzondering 10.6: alleen
  estafette bij senioren);
- 10.9: eerder dit jaar voor een andere vereniging (alleen als bekend).

## 3. Matrix: `vergelijk.py` + `voorspeller.py`

Per beschikbare atleet × programmaonderdeel een cel met prestatie, punten en
bron (`prestatie` of `voorspeld`):

- **Prestatie**: beste windlegale prestatie volgens de prestatiebasis van de
  ploeg; standaard huidig + vorig seizoen. Zelfde windregel als de `pr`-view
  (migratie prestaties/002).
- **Categorie** op de wedstrijddag via de bestaande logica in
  `wedstrijden/chronoloog.py`. Masters: leeftijd op de wedstrijddag.
- **Voorspelling** als er geen prestatie is (altijd zichtbaar gemarkeerd):
  - buuronderdeel via puntengelijkwaardigheid: 80 m → punten →
    `prestatie_voor(100m)` × veiligheidsfactor uit de YAML;
  - ander werpmateriaal of hordehoogte: verhoudingsfactor uit de YAML;
  - estafette: som van de vlakke tijden van de lopers + `correctie_s`. Voor
    de optimalisatie worden de **top-K kwartetten** voorgerekend (bijv. alle
    combinaties van de 8 snelste: 70 opties), elk met hun punten.
- Pseudoniemen worden in Python berekend zoals elders; namen blijven in
  `personen.db`.

In beeld lijkt de matrix op de Mastersploeg-spreadsheet: atleten als rijen,
onderdelen als kolommen, punten in de cellen.

## 4. Opstelling en optimalisatie

### Database (migratie `personen/009_ploeg_opstelling.sql`)

- `ploeg` krijgt erbij: `categorie` (bijv. `U16-V`), `programma`
  (bijv. `wedstrijd_2`), `prestatiebasis` (`seizoen`/`pr`/`12mnd`,
  standaard `seizoen`), `volgorde` (A/B-ploeg).
- `ploeg_opstelling` wordt opnieuw opgebouwd (is nog leeg), met sleutel op de
  **programmasleutel** in plaats van `onderdeel_id`:
  `ploeg_id`, `atleet_id` (master_id), `programma_onderdeel` (tekst uit de
  YAML), `groep` (technische groep), `vast` (vastgezet door de trainer).
  Het `onderdeel_id` wordt per atleet afgeleid uit de YAML.
- Nieuw `ploeg_lid`: `ploeg_id`, `atleet_id`, `rol` (`deelnemer`/`reserve`),
  `beschikbaar` (`hele_dag`/`ochtend`/`middag`).
- Nieuw `ploeg_voorkeur`: `ploeg_id`, `atleet_id`, `programma_onderdeel`,
  `voorkeur` (`wil_niet`/`voorkeur`/`moet`).

### Het ILP-model (`optimaliseer.py`, scipy `milp`)

Variabelen:

- `x[a,e]` = atleet *a* staat op onderdeel *e*;
- `s[a,e] ≤ x[a,e]` = *a* is een van de tellende atleten op *e*;
- `w[k]` = estafette-optie *k* gekozen.

Eisen:

- maximum per onderdeel: `Σa x[a,e] ≤ max_e`;
- tellend: `Σa s[a,e] ≤ tellend_e`;
- drie onderdelen: `Σe x[a,e] + Σ(k∋a) w[k] ≤ 3`;
- één estafetteploeg: `Σk w[k] ≤ 1` per estafette;
- botsingen uit de chronoloog (`chronoloog.py`): `x[a,e1] + x[a,e2] ≤ 1`;
- beschikbaarheid (dagdeel) en `wil_niet`: `x = 0`; `vast` en `moet`: `x = 1`.
  De optimalisatie vult dus alleen in wat de trainer openliet;
- technische groepen: per groep max. één atleet per ploeg (9.1), groep wordt
  na het oplossen toegewezen.

### Strategieën (`strategieen/`)

Elke strategie is een module met `naam`, `uitleg` en een functie die doel en
extra eisen aan het model toevoegt. Ontdekt zoals de importers in
`importers/detect.py`. `ploeg.strategie` bewaart welke gebruikt is.

| Module | Doel |
|--------|------|
| `max_punten` | Maximaliseer Σ punten·s, ook als een atleet maar 1 onderdeel doet. |
| `iedereen_meedoen` | Eerst zoveel mogelijk deelnames (Σ x), dan punten (lexicografisch via gewichten). |
| `minimaal_twee` | Maximaliseer punten met `2·z[a] ≤ Σe x[a,e] ≤ 3·z[a]` (`z[a]` = atleet doet mee). |

### Meer ploegen

Na elkaar oplossen: A-ploeg eerst, dan de B-ploeg uit wie over is. Elke ploeg
mag een eigen strategie hebben; niemand komt in twee ploegen (10.10). Samen
oplossen kan later als dat uitmaakt.

### Export (`export.py`)

Csv voor atletiek.nu, kolommen: AU-nummer (`au_licentienummer`), Naam,
Geslacht, Geboortedatum, Vereniging, Categorie, Team, Onderdeel 1 … n. Per
onderdeelkolom de prestatie (voorkeur) of `x`, anders leeg. Bevat
persoonsgegevens: wordt in het geheugen gemaakt en als download gegeven, nooit
in `data/` of de repo opgeslagen.

Bij opslaan van een ploeg worden ook `inschrijving`-rijen in `prestaties.db`
gezet, zodat de wedstrijdpagina en de botsingencontrole meteen werken.

## UI-stappen

1. Kies de wedstrijd (datum en chronoloog komen mee).
2. Competitie + welke wedstrijd (vult het programma uit de YAML; of importeer
   het tijdschema van atletiek.nu met de bestaande importer).
3. Categorie.
4. Vink aan wie er is (vooringevuld uit de inschrijvingen; hele dag / ochtend /
   middag).
5. **Matrixscherm**: klik om in te delen; totalen per onderdeel en voor de
   ploeg lopen mee; regelovertredingen in rood; voorspelde waarden gemarkeerd.
6. **Optimaliseer** met strategiekeuze; vastgezette cellen blijven staan.
7. Exporteer de csv.

## Volgorde van bouwen

1. `punten.py` + `au_2025.yaml` + tests tegen de voorbeelden uit het document.
2. `u14_u16_2026.yaml` + `regels.py` (U14/U16 heeft de interessantste
   telregel, goede test voor het ontwerp).
3. Matrix + handmatige opstelling + regelcontrole in de UI.
4. Csv-export.
5. Optimalisatie + de drie strategieën.
6. Voorspeller en estafettes.
7. Meer ploegen, botsingen uit de chronoloog, U18/U20 (werpmateriaal),
   masters (age grading), senioren (gemengd), 1e divisie / NK Teams.

## Open punten

- Masters age-grading-factoren controleren tegen de spreadsheet.
- Standaardwaarden voor de voorspeller (veiligheidsfactor, estafettecorrectie)
  bepalen met echte data.
- Later mogelijk: een "verzekering"-optie (tweede atleet op hoog/polsstok voor
  het geval de eerste geen hoogte haalt).
