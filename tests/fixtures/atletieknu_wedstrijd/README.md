# Fixtures: atletiek.nu wedstrijduitslagen (geanonimiseerd)

Ingekorte, **geanonimiseerde** kopieën van echte uitslagpagina's van atletiek.nu, voor de
tests van `src/importers/atletieknu_wedstrijd.py`. Er staan geen echte namen, verenigingen,
teams, wedstrijdnamen, plaatsen of id's in:

| Wat              | Vervangen door |
|------------------|----------------|
| Atleten          | nepnamen (`Anna Voorbeeld`, `Bas van Proefstra`, lange namen als `Ruben van den Langenaamhoeve`) |
| Verenigingen     | `Atletiek Teststad` (de "eigen" club) en `Vereniging 01` t/m `20` |
| Teams            | `Teststad Heren 1`, `Teststad Vrouwen 1` en `Testteam 01` t/m `10` |
| Wedstrijden      | `Testmeerkamp 2026` (Proefdorp, id 90001), `Test Teamwedstrijd 2026` (Teststad, id 90002) |
| Id's             | deelnemers 8000001+, verenigingen 101+, teams 501+ |

Prestaties, wind, punten en pogingen zijn ongewijzigd (zonder naam of club zijn ze niet
herleidbaar). Per onderdeel zijn maximaal 2–3 categorieën en ±5 rijen bewaard; scripts, menu's,
vlaggen en opmaak zijn verwijderd. De HTML-structuur die de importer leest is intact.

## Bestanden

Elke map is één wedstrijd: `00_uitslagen.html` is de uitslagenpagina (lijst met onderdelen),
de andere bestanden zijn onderdeelpagina's. Bestandsnaam = onderdeelcode, met `_` i.p.v. spatie
(`2000m_SC.html` hoort bij `.../uitslagenonderdeel/90002/2000m SC/`).

**`meerkamp/`** — individuele meerkamp, twee dagen
- `100m` wind · `110mH` hordehoogte + DNF · `400m` DNF, 3 categorieën
- `Kogel` gewicht, pogingen, X, PB · `Hoog` hoogtes met O/XO/XXX en `r` (gestopt), SB · `Ver` wind per poging, `-` (niet gestart)

**`teams/`** — teamwedstrijd (competitie)
- Team-kolom in elke rij, teampunten i.p.v. meerkamppunten
- **Lange namen** (naam alleen in `<span class="hidden-xs">`): in `100m`, `3000m`, `2000m_SC`, `Kogel`, `HSS`, `Ver`, `Resv`
- `3000m` handtijden (`10:10,1h`) · `2000m_SC` code met spatie + hordehoogte · `100m` fotofinish-icoon
- `4x100m` estafettes met 4 lopers · `Resv` reserves (horen **niet** in de uitslagen)

## Verwachte uitkomsten (ter controle in tests)

```
meerkamp, --vereniging "Atletiek Teststad"          -> 24 uitslagen van 8 atleten
meerkamp, Anna Voorbeeld Kogel                       -> 10,85 (7.26kg), pogingen "10,74 | 10,48 | 10,85", 537 punten
meerkamp, Anna Voorbeeld Hoog                        -> 1,72, pogingen "1.60 O | 1.66 O | 1.72 O | 1.75 XXX"
meerkamp, Anna Voorbeeld Ver                         -> 6,19, wind "-0,4 m/s", pogingen "- | 6,01 | 6,19"
meerkamp, Floris Voorbeeld 400m                      -> DNF, waarde None, positie ""
meerkamp, datum / einddatum                          -> 2026-08-29 / 2026-08-30
teams, --team "Teststad Heren 1"                     -> 6 uitslagen van 4 atleten, waarvan 1 estafette, geen reserves
teams, --vereniging "Atletiek Teststad"              -> 8 uitslagen van 4 atleten, waarvan 2 estafettes
teams, estafette "Teststad Heren 1 (4x100m)"         -> 44,49, lopers "Bodil Voorbeeld, Anna Voorbeeld, Cees Voorbeeld, Dewi Voorbeeld"
teams, Tijn Voorbeeld 3000m                          -> "10:10,1h", waarde 610.1
teams, alle uitslagen                                -> geen lege atleetnamen, geen "Reserve atleet"
```

Gebruik in tests: geef de map als bron (`laad_uitslagen("tests/fixtures/atletieknu_wedstrijd/teams")`)
of vervang `requests.Session` door een nep-sessie die URL's naar deze bestanden vertaalt.
