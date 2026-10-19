"""Atleten toevoegen, bijwerken, zoeken, (de)activeren en verwijderen."""

from __future__ import annotations

from db.queries import Opslag
from models import Atleet

from .koppelen import normaliseer


def mogelijke_dubbelen(db: Opslag, voornaam: str, achternaam: str,
                       geboortedatum: str | None = None, *,
                       tussenvoegsel: str | None = None) -> list[Atleet]:
    """Bestaande atleten met dezelfde naam (en, als bekend, hetzelfde geboortejaar).

    Voor een waarschuwing in de UI voordat een nieuwe atleet wordt aangemaakt.
    """
    doel = normaliseer(Atleet(voornaam, achternaam, tussenvoegsel=tussenvoegsel).naam)
    jaar = int(geboortedatum[:4]) if geboortedatum else None
    return [a for a in db.atleten(alleen_actief=False)
            if normaliseer(a.naam) == doel and (jaar is None or a.geboortejaar in (None, jaar))]


def nieuwe_atleet(db: Opslag, voornaam: str, achternaam: str, *,
                  toch_aanmaken: bool = False, **gegevens) -> Atleet:
    """Maak een nieuwe atleet aan.

    Bestaat er al iemand met dezelfde naam (en hetzelfde geboortejaar), dan
    volgt een DubbeleAtleet-fout, tenzij toch_aanmaken=True.
    Extra gegevens: tussenvoegsel, geslacht, geboortedatum, club, atletieknu_id,
    au_licentienummer, specialisatie, notities.
    """
    voornaam, achternaam = voornaam.strip(), achternaam.strip()
    if not voornaam or not achternaam:
        raise ValueError("Voor- en achternaam zijn verplicht.")
    if not toch_aanmaken:
        dubbel = mogelijke_dubbelen(db, voornaam, achternaam, gegevens.get("geboortedatum"),
                                    tussenvoegsel=gegevens.get("tussenvoegsel"))
        if dubbel:
            raise DubbeleAtleet(dubbel)
    return db.atleet_opslaan(Atleet(voornaam, achternaam, **gegevens))


class DubbeleAtleet(ValueError):
    """Er bestaat al een atleet met deze naam. `bestaande` bevat de kandidaten."""

    def __init__(self, bestaande: list[Atleet]) -> None:
        super().__init__(f"Er bestaan al {len(bestaande)} atleet/atleten met deze naam.")
        self.bestaande = bestaande


def bijwerken(db: Opslag, atleet: Atleet) -> Atleet:
    if atleet.master_id is None or db.atleet(atleet.master_id) is None:
        raise ValueError("Deze atleet bestaat nog niet; gebruik nieuwe_atleet().")
    return db.atleet_opslaan(atleet)


def zoeken(db: Opslag, tekst: str = "", alleen_actief: bool = False) -> list[Atleet]:
    """Zoek op een deel van de naam. Lege tekst: alle atleten."""
    if not tekst.strip():
        return db.atleten(alleen_actief=alleen_actief)
    return db.atleten_zoeken(tekst, alleen_actief=alleen_actief)


def _haal(db: Opslag, master_id: str) -> Atleet:
    atleet = db.atleet(master_id)
    if atleet is None:
        raise ValueError("Onbekende atleet.")
    return atleet


def zet_actief(db: Opslag, master_id: str, actief: bool) -> Atleet:
    """Inactief = traint niet meer, maar alle gegevens blijven bewaard."""
    atleet = _haal(db, master_id)
    atleet.actief = actief
    return db.atleet_opslaan(atleet)


def zet_specialisatie(db: Opslag, master_id: str, specialisatie: str | None) -> Atleet:
    atleet = _haal(db, master_id)
    atleet.specialisatie = specialisatie.strip() if specialisatie and specialisatie.strip() else None
    return db.atleet_opslaan(atleet)


def verwijderen(db: Opslag, master_id: str, *, bevestigd: bool = False) -> None:
    """Verwijder een atleet en AL zijn gegevens uit alle databases (verzoek tot verwijdering).

    Kan niet ongedaan worden gemaakt, daarom moet bevestigd=True worden meegegeven.
    Wie alleen stopt met trainen: zet_actief(db, master_id, False).
    """
    if not bevestigd:
        raise ValueError("Verwijderen moet bevestigd worden (bevestigd=True).")
    _haal(db, master_id)
    db.atleet_verwijderen(master_id)
