"""Overzicht van de leerlijnen: alle leerdoelen per onderdeel of per categorie.

Voor de pagina 'Leerlijnen' in het hoofdmenu. Alleen de catalogus
(leerlijnen.db), dus geen persoonsgegevens en geen scores.

Twee keuzes, elk optioneel:
  onderdeel  – een leerlijn, bijv. 'SPR' (Sprint): alle doelen van U10 t/m U20,
               per categorie gegroepeerd (zo zie je de opbouw over de jaren);
  categorie  – bijv. 'U14': alle doelen die in die categorie beginnen, per
               onderdeel gegroepeerd; met `doorlopend` ook die van eerdere
               categorieën (wat een U14-atleet allemaal zou moeten kunnen).
Beide samen = de doelen van één onderdeel in één categorie. Geen keuze =
een telling onderdelen x categorieën om mee te beginnen.

Onbekende waarden (bijv. een oude link) tellen als 'geen keuze', zodat de
pagina nooit vastloopt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from db.queries import Opslag
from models import CATEGORIEEN, Leerdoel

#: Bronnen zoals ze op de pagina heten (zie schema_leerlijnen.sql).
BRONNEN = {
    "NA": "Leerlijn baanatletiek jeugd NA",
    "AU": "Atletiekunie, Leerlijnen binnen de atletiek (2013)",
    "eigen": "Door de club toegevoegd",
}
#: LTAD-fasen van de Atletiekunie, leesbaar.
FASEN = {
    "fundament": "fundament",
    "leren_trainen": "leren trainen",
    "trainen_omvang": "trainen voor omvang",
    "trainen_niveau": "trainen op niveau",
    "stabiel_element": "stabiel element",
}


@dataclass
class Groep:
    """Eén tabel op de pagina: een categorie (bij een gekozen onderdeel) of een onderdeel."""
    sleutel: str                         # 'U12' of 'SPR' (voor het anker #ll-...)
    titel: str                           # 'U12' of 'Sprint'
    doelen: list[Leerdoel] = field(default_factory=list)

    @property
    def aantal(self) -> int:
        return len(self.doelen)


@dataclass
class Overzicht:
    leerlijnen: list[tuple[str, str]]    # alle onderdelen (code, naam), vaste volgorde
    categorieen: tuple[str, ...]         # 'U10' … 'U20'
    onderdeel: str | None                # gekozen code of None
    categorie: str | None                # gekozen categorie of None
    doorlopend: bool                     # alleen zinvol met een categorie
    groepen: list[Groep]                 # leeg als er niets gekozen is
    telling: dict[tuple[str, str], int]  # (leerlijn, categorie) -> aantal actieve doelen
    groeperen_op: str | None             # 'categorie' of 'onderdeel': waar de tabellen per gaan

    @property
    def gekozen(self) -> bool:
        return self.onderdeel is not None or self.categorie is not None

    @property
    def onderdeel_naam(self) -> str | None:
        return dict(self.leerlijnen).get(self.onderdeel) if self.onderdeel else None

    @property
    def aantal(self) -> int:
        return sum(g.aantal for g in self.groepen)

    @property
    def totaal(self) -> int:
        return sum(self.telling.values())

    def per_onderdeel(self, code: str) -> int:
        return sum(n for (l, _c), n in self.telling.items() if l == code)

    def per_categorie(self, cat: str) -> int:
        return sum(n for (_l, c), n in self.telling.items() if c == cat)

    @property
    def toon_categorie(self) -> bool:
        """Of de tabellen een kolom 'Cat.' nodig hebben (doelen uit meer categorieën door elkaar)."""
        return self.groeperen_op == "onderdeel" and self.doorlopend

    def link(self, **wijzig) -> str:
        """Querystring voor deze pagina met één keuze anders, bijv. link(categorie='U12').
        Een waarde None haalt die keuze weg; 'doorlopend' valt weg zonder categorie."""
        waarden = {"onderdeel": self.onderdeel, "categorie": self.categorie,
                   "doorlopend": "1" if self.doorlopend else None}
        waarden.update(wijzig)
        if not waarden.get("categorie"):
            waarden["doorlopend"] = None
        delen = [f"{k}={v}" for k, v in waarden.items() if v]
        return "?" + "&".join(delen) if delen else "?"


def leerlijnoverzicht(db: Opslag, onderdeel: str | None = None, categorie: str | None = None,
                      doorlopend: bool = False) -> Overzicht:
    """Het overzicht voor de gekozen onderdeel en/of categorie (zie module-docstring)."""
    leerlijnen = db.leerdoel_leerlijnen()
    codes = {c for c, _ in leerlijnen}
    onderdeel = (onderdeel or "").strip().upper() or None
    categorie = (categorie or "").strip().upper() or None
    if onderdeel not in codes:
        onderdeel = None
    if categorie not in CATEGORIEEN:
        categorie = None
    doorlopend = bool(doorlopend and categorie)

    alle = db.leerdoelen()                                  # actief, gesorteerd op categorie, leerlijn, volgorde
    telling: dict[tuple[str, str], int] = {}
    for d in alle:
        telling[(d.leerlijn, d.categorie)] = telling.get((d.leerlijn, d.categorie), 0) + 1

    groepen: list[Groep] = []
    groeperen_op: str | None = None
    if onderdeel or categorie:
        doelen = db.leerdoelen(categorie, leerlijn=onderdeel, doorlopend=doorlopend)
        if onderdeel and not (categorie and not doorlopend):
            # Eén onderdeel over meerdere categorieën: per categorie, zo zie je de opbouw.
            groeperen_op = "categorie"
            per = {c: Groep(c, c) for c in CATEGORIEEN}
            for d in doelen:
                per[d.categorie].doelen.append(d)
            groepen = [g for g in per.values() if g.doelen]
        else:
            # Eén categorie (eventueel met eerdere): per onderdeel, in de vaste volgorde.
            groeperen_op = "onderdeel"
            per = {c: Groep(c, naam) for c, naam in leerlijnen}
            for d in doelen:
                per[d.leerlijn].doelen.append(d)
            for g in per.values():                          # binnen een onderdeel: oudste categorie eerst
                g.doelen.sort(key=lambda d: (CATEGORIEEN.index(d.categorie), d.volgorde))
            groepen = [g for g in per.values() if g.doelen]

    return Overzicht(leerlijnen=leerlijnen, categorieen=CATEGORIEEN, onderdeel=onderdeel, categorie=categorie,
                     doorlopend=doorlopend, groepen=groepen, telling=telling, groeperen_op=groeperen_op)
