"""Alle SQL op één plek: zet databaserijen om naar modellen en terug.

De rest van de app praat alleen met `Opslag` en krijgt/geeft modellen uit
models/. Buiten dit bestand is geen SQL nodig, en niemand buiten db/ hoeft te
weten dat de gegevens over acht versleutelde bestanden verdeeld zijn.

Pseudoniemen
------------
In alle databases behalve personen.db staat een atleet als atleet_ref (een
pseudoniem per database). Modellen gebruiken altijd de master_id. Opslag rekent:

  * heen:  master_id -> atleet_ref met pseudoniem() uit init_db;
  * terug: atleet_ref -> master_id via een tabel die in het geheugen wordt
           opgebouwd uit alle master_ids in personen.db. Die tabel wordt nooit
           opgeslagen.

Gebruik
-------
    from db.queries import Opslag

    with Opslag() as db:                      # sleutel uit de sleutelkluis, map data/
        anna = db.atleet_opslaan(Atleet("Anna", "Voorbeeld", geslacht="V"))
        for pr in db.prs(anna.master_id):
            ...

Tests geven een eigen map en testsleutel mee: Opslag(map=tmp, hoofd="00" * 32).
De databases moeten al bestaan (init_db.init_db()).

Regels
------
  * Alleen geparametriseerde queries (?), nooit strings in SQL plakken.
  * Elke schrijf-methode is één transactie.
  * Verwijzingen tussen bestanden (bijv. ploeg -> wedstrijd, absentie -> training) dwingt SQLite niet
    af; die controleert deze module in Python.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

from models import (
    DAGEN,
    PR,
    Absentie,
    Atleet,
    Groep,
    Inschrijving,
    CATEGORIEEN,
    Leerdoel,
    LeerdoelScore,
    Leerlijn,
    LeerlijnStap,
    LeerlijnVoortgang,
    Notitie,
    Onderdeel,
    Periodeplan,
    Prestatie,
    Test,
    Testresultaat,
    Training,
    normaliseer_tijd,
    Trainingsschema,
    Wedstrijd,
)

from .init_db import hoofdsleutel, nieuw_master_id, pseudoniem, verbind


class OpslagFout(ValueError):
    """Iets kan niet worden opgeslagen, bijv. een onbekend onderdeel of een ongekoppelde prestatie."""


# ============================================================
# Omzetten tussen Python en SQLite
# ============================================================
def _naar_tekst(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _naar_datum(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _vraagtekens(n: int) -> str:
    """'?, ?, ?' voor een IN (...)-lijst. Alleen vraagtekens, dus veilig."""
    return ", ".join("?" * n)


class Opslag:
    """Toegang tot de acht AVS-databases met modellen in en modellen uit."""

    def __init__(self, map: Path | None = None, hoofd: str | bytes | None = None) -> None:
        self._map = Path(map) if map else None
        # Eén keer de sleutel ophalen, niet bij elk pseudoniem opnieuw.
        self._hoofd = hoofd if hoofd is not None else hoofdsleutel()
        self.personen = verbind("personen", self._map, self._hoofd)
        self.prestaties_db = verbind("prestaties", self._map, self._hoofd)
        self.testen_db = verbind("testen", self._map, self._hoofd)
        self.trainingsschema_db = verbind("trainingsschema", self._map, self._hoofd)
        self.absentie_db = verbind("absentie", self._map, self._hoofd)
        self.leerlijnen_db = verbind("leerlijnen", self._map, self._hoofd)
        self.leerdoelscores_db = verbind("leerdoelscores", self._map, self._hoofd)
        self.notities_db = verbind("notities", self._map, self._hoofd)
        self._terug: dict[str, dict[str, str]] = {}

    # ---------- openen / sluiten ----------
    def sluit(self) -> None:
        for conn in (self.personen, self.prestaties_db, self.testen_db, self.trainingsschema_db, self.absentie_db,
                     self.leerlijnen_db, self.leerdoelscores_db, self.notities_db):
            conn.close()

    def __enter__(self) -> Opslag:
        return self

    def __exit__(self, *_) -> None:
        self.sluit()

    # ---------- pseudoniemen ----------
    def _ref(self, master_id: str, database: str) -> str:
        return pseudoniem(master_id, database, self._hoofd)

    def _master_id(self, atleet_ref: str, database: str) -> str | None:
        """atleet_ref -> master_id. None als de atleet niet (meer) bestaat."""
        if database not in self._terug:
            ids = [r[0] for r in self.personen.execute("SELECT master_id FROM atleet")]
            self._terug[database] = {self._ref(m, database): m for m in ids}
        return self._terug[database].get(atleet_ref)

    def _vergeet_pseudoniemen(self) -> None:
        self._terug.clear()

    # ============================================================
    # Atleten (personen.db)
    # ============================================================
    @staticmethod
    def _atleet(r) -> Atleet:
        return Atleet(
            voornaam=r["voornaam"], tussenvoegsel=r["tussenvoegsel"], achternaam=r["achternaam"],
            geslacht=r["geslacht"],
            geboortedatum=r["geboortedatum"], club=r["club"], atletieknu_id=r["atletieknu_id"],
            specialisatie=r["specialisatie"], actief=bool(r["actief"]), notities=r["notities"],
            master_id=r["master_id"], aangemaakt_op=r["aangemaakt_op"],
        )

    def atleet_opslaan(self, a: Atleet) -> Atleet:
        """Nieuwe atleet toevoegen of een bestaande bijwerken. Een nieuwe atleet krijgt een master_id."""
        nieuw = a.master_id is None
        if nieuw:
            a.master_id = nieuw_master_id()
        with self.personen:
            self.personen.execute(
                """INSERT INTO atleet (master_id, voornaam, tussenvoegsel, achternaam, geslacht,
                                       geboortedatum, club, atletieknu_id, specialisatie, actief, notities)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (master_id) DO UPDATE SET
                       voornaam = excluded.voornaam, tussenvoegsel = excluded.tussenvoegsel,
                       achternaam = excluded.achternaam,
                       geslacht = excluded.geslacht, geboortedatum = excluded.geboortedatum,
                       club = excluded.club, atletieknu_id = excluded.atletieknu_id,
                       specialisatie = excluded.specialisatie, actief = excluded.actief,
                       notities = excluded.notities""",
                (a.master_id, a.voornaam, a.tussenvoegsel, a.achternaam, a.geslacht, a.geboortedatum,
                 a.club, a.atletieknu_id, a.specialisatie, int(a.actief), a.notities),
            )
        if nieuw:
            self._vergeet_pseudoniemen()
            a.aangemaakt_op = self.personen.execute(
                "SELECT aangemaakt_op FROM atleet WHERE master_id = ?", (a.master_id,)
            ).fetchone()[0]
        return a

    def atleet(self, master_id: str) -> Atleet | None:
        r = self.personen.execute("SELECT * FROM atleet WHERE master_id = ?", (master_id,)).fetchone()
        return self._atleet(r) if r else None

    def atleet_op_atletieknu_id(self, atletieknu_id: str) -> Atleet | None:
        r = self.personen.execute(
            "SELECT * FROM atleet WHERE atletieknu_id = ?", (atletieknu_id,)
        ).fetchone()
        return self._atleet(r) if r else None

    def atleten(self, alleen_actief: bool = True) -> list[Atleet]:
        sql = "SELECT * FROM atleet"
        if alleen_actief:
            sql += " WHERE actief = 1"
        sql += " ORDER BY achternaam, voornaam"
        return [self._atleet(r) for r in self.personen.execute(sql)]

    def atleten_zoeken(self, tekst: str, alleen_actief: bool = False) -> list[Atleet]:
        """Zoek op (een deel van) de volledige naam, hoofdletterongevoelig."""
        patroon = f"%{tekst.strip()}%"
        sql = ("SELECT * FROM atleet "
               "WHERE (voornaam || ' ' || COALESCE(tussenvoegsel || ' ', '') || achternaam) LIKE ?")
        if alleen_actief:
            sql += " AND actief = 1"
        sql += " ORDER BY achternaam, voornaam"
        return [self._atleet(r) for r in self.personen.execute(sql, (patroon,))]

    def atleet_verwijderen(self, master_id: str) -> None:
        """Verwijdert een atleet en AL zijn gegevens uit alle databases.

        Bedoeld voor een verzoek tot verwijdering (AVG). Wie alleen niet meer
        traint: zet `actief = False` en sla op.
        """
        ref_p = self._ref(master_id, "prestaties")
        ref_t = self._ref(master_id, "testen")
        ref_s = self._ref(master_id, "trainingsschema")
        ref_a = self._ref(master_id, "absentie")
        ref_l = self._ref(master_id, "leerdoelscores")
        ref_n = self._ref(master_id, "notities")
        with self.prestaties_db:
            self.prestaties_db.execute("DELETE FROM prestatie WHERE atleet_ref = ?", (ref_p,))
            self.prestaties_db.execute("DELETE FROM inschrijving WHERE atleet_ref = ?", (ref_p,))
        with self.testen_db:
            self.testen_db.execute("DELETE FROM testresultaat WHERE atleet_ref = ?", (ref_t,))
        with self.trainingsschema_db:
            self.trainingsschema_db.execute("DELETE FROM trainingsschema WHERE atleet_ref = ?", (ref_s,))
            self.trainingsschema_db.execute("DELETE FROM trainingskeuze WHERE atleet_ref = ?", (ref_s,))
        with self.absentie_db:
            self.absentie_db.execute("DELETE FROM absentie WHERE atleet_ref = ?", (ref_a,))
        with self.leerdoelscores_db:
            self.leerdoelscores_db.execute("DELETE FROM leerdoelscore WHERE atleet_ref = ?", (ref_l,))
        with self.notities_db:
            self.notities_db.execute("DELETE FROM notitie WHERE atleet_ref = ?", (ref_n,))
        with self.personen:  # groep_lid, voortgang, opstellingen gaan mee (CASCADE)
            self.personen.execute("DELETE FROM atleet WHERE master_id = ?", (master_id,))
        self._vergeet_pseudoniemen()

    # ============================================================
    # Onderdelen en wedstrijden (prestaties.db)
    # ============================================================
    @staticmethod
    def _onderdeel(r) -> Onderdeel:
        return Onderdeel(naam=r["naam"], eenheid=r["eenheid"], lager_is_beter=bool(r["lager_is_beter"]),
                         categorie=r["categorie"], id=r["id"], windmeting=bool(r["windmeting"]))

    def onderdeel_opslaan(self, o: Onderdeel) -> Onderdeel:
        """Toevoegen of bijwerken. Bestaat de naam al, dan wordt die rij bijgewerkt.

        windmeting (vanaf migratie prestaties/003) bepaalt of de wind moet
        kloppen voor een PR; zonder opgave volgt hij uit de naam.
        """
        with self.prestaties_db:
            r = self.prestaties_db.execute(
                """INSERT INTO onderdeel (naam, categorie, eenheid, lager_is_beter, windmeting)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (naam) DO UPDATE SET categorie = excluded.categorie,
                       eenheid = excluded.eenheid, lager_is_beter = excluded.lager_is_beter,
                       windmeting = excluded.windmeting
                   RETURNING id""",
                (o.naam, o.categorie, o.eenheid, int(o.lager_is_beter), int(bool(o.windmeting))),
            ).fetchone()
        o.id = r[0]
        return o

    def onderdeel(self, naam_of_id: str | int) -> Onderdeel | None:
        kolom = "id" if isinstance(naam_of_id, int) else "naam"
        r = self.prestaties_db.execute(
            f"SELECT * FROM onderdeel WHERE {kolom} = ?", (naam_of_id,)  # kolom is een vaste naam
        ).fetchone()
        return self._onderdeel(r) if r else None

    def onderdelen(self) -> list[Onderdeel]:
        return [self._onderdeel(r) for r in
                self.prestaties_db.execute("SELECT * FROM onderdeel ORDER BY categorie, naam")]

    @staticmethod
    def _wedstrijd(r) -> Wedstrijd:
        return Wedstrijd(naam=r["naam"], datum=_naar_datum(r["datum"]), locatie=r["locatie"],
                         bron=r["bron"], bron_url=r["bron_url"], id=r["id"], indoor=bool(r["indoor"]))

    def wedstrijd_opslaan(self, w: Wedstrijd) -> Wedstrijd:
        """Toevoegen of bijwerken. Een wedstrijd met dezelfde bron_url wordt hergebruikt,
        zodat dezelfde link twee keer importeren geen dubbele wedstrijd oplevert.

        `indoor` geldt voor alle prestaties op deze wedstrijd: ook prestaties die
        er al stonden krijgen de nieuwe waarde (indoor telt altijd voor een PR).
        """
        if w.id is None and w.bron_url:
            r = self.prestaties_db.execute(
                "SELECT id FROM wedstrijd WHERE bron_url = ?", (w.bron_url,)
            ).fetchone()
            if r:
                w.id = r[0]
        with self.prestaties_db:
            waarden = (w.naam, _naar_tekst(w.datum), w.locatie, w.bron, w.bron_url, int(w.indoor))
            if w.id is None:
                w.id = self.prestaties_db.execute(
                    "INSERT INTO wedstrijd (naam, datum, locatie, bron, bron_url, indoor) VALUES (?, ?, ?, ?, ?, ?)",
                    waarden,
                ).lastrowid
            else:
                self.prestaties_db.execute(
                    """UPDATE wedstrijd SET naam = ?, datum = ?, locatie = ?, bron = ?, bron_url = ?, indoor = ?
                       WHERE id = ?""",
                    (*waarden, w.id),
                )
                self.prestaties_db.execute(
                    "UPDATE prestatie SET indoor = ? WHERE wedstrijd_id = ?", (int(w.indoor), w.id)
                )
        return w

    def wedstrijd(self, wedstrijd_id: int) -> Wedstrijd | None:
        r = self.prestaties_db.execute("SELECT * FROM wedstrijd WHERE id = ?", (wedstrijd_id,)).fetchone()
        return self._wedstrijd(r) if r else None

    def wedstrijden(self, van: date | None = None, tot: date | None = None) -> list[Wedstrijd]:
        sql, args = "SELECT * FROM wedstrijd WHERE 1 = 1", []
        if van:
            sql += " AND datum >= ?"
            args.append(_naar_tekst(van))
        if tot:
            sql += " AND datum <= ?"
            args.append(_naar_tekst(tot))
        sql += " ORDER BY datum"
        return [self._wedstrijd(r) for r in self.prestaties_db.execute(sql, args)]

    # ============================================================
    # Prestaties, PR's, inschrijvingen (prestaties.db)
    # ============================================================
    def _prestatie(self, r, atleet_id: str | None) -> Prestatie:
        return Prestatie(
            onderdeel=r["onderdeel_naam"], datum=_naar_datum(r["datum"]), waarde=r["waarde"],
            atleet_id=atleet_id, onderdeel_id=r["onderdeel_id"], wedstrijd_id=r["wedstrijd_id"],
            wind=r["wind"], ronde=r["ronde"], bron=r["bron"], id=r["id"], indoor=bool(r["indoor"]),
        )

    _PRESTATIE_SELECT = """SELECT p.*, o.naam AS onderdeel_naam
                           FROM prestatie p JOIN onderdeel o ON o.id = p.onderdeel_id"""

    def prestatie_opslaan(self, p: Prestatie) -> bool:
        """Sla een gekoppelde prestatie op. Geeft False als hij er al stond (dubbele import).

        De tijdelijke importvelden (bron_naam, bron_atletieknu_id) worden nooit opgeslagen.
        """
        if not p.is_gekoppeld:
            raise OpslagFout("Prestatie is nog niet aan een atleet gekoppeld (atleet_id ontbreekt).")
        if p.onderdeel_id is None:
            o = self.onderdeel(p.onderdeel)
            if o is None:
                raise OpslagFout(f"Onbekend onderdeel {p.onderdeel!r}; voeg het eerst toe met onderdeel_opslaan().")
            p.onderdeel_id = o.id
        if p.wedstrijd_id is not None:
            w = self.wedstrijd(p.wedstrijd_id)
            if w is None:
                raise OpslagFout(f"Wedstrijd {p.wedstrijd_id} bestaat niet.")
            p.indoor = w.indoor  # een prestatie op een indoorwedstrijd is indoor

        ref = self._ref(p.atleet_id, "prestaties")
        sleutel = (ref, p.onderdeel_id, _naar_tekst(p.datum), p.waarde, p.ronde or "")
        with self.prestaties_db:
            cur = self.prestaties_db.execute(
                """INSERT OR IGNORE INTO prestatie
                       (atleet_ref, onderdeel_id, datum, waarde, ronde, wedstrijd_id, wind, bron, indoor)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*sleutel, p.wedstrijd_id, p.wind, p.bron, int(p.indoor)),
            )
        nieuw = cur.rowcount == 1
        p.id = self.prestaties_db.execute(
            """SELECT id FROM prestatie WHERE atleet_ref = ? AND onderdeel_id = ?
               AND datum = ? AND waarde = ? AND ronde = ?""",
            sleutel,
        ).fetchone()[0]
        return nieuw

    def prestaties_opslaan(self, prestaties: Iterable[Prestatie]) -> tuple[int, int]:
        """Meerdere prestaties (bijv. na een import). Geeft (nieuw, al_bekend)."""
        nieuw = bekend = 0
        for p in prestaties:
            if self.prestatie_opslaan(p):
                nieuw += 1
            else:
                bekend += 1
        return nieuw, bekend

    def prestaties(self, master_id: str, onderdeel_id: int | None = None) -> list[Prestatie]:
        """Alle prestaties van één atleet, nieuwste eerst."""
        sql = self._PRESTATIE_SELECT + " WHERE p.atleet_ref = ?"
        args: list = [self._ref(master_id, "prestaties")]
        if onderdeel_id is not None:
            sql += " AND p.onderdeel_id = ?"
            args.append(onderdeel_id)
        sql += " ORDER BY p.datum DESC"
        return [self._prestatie(r, master_id) for r in self.prestaties_db.execute(sql, args)]

    def prestaties_van_wedstrijd(self, wedstrijd_id: int) -> list[Prestatie]:
        """Alle prestaties op een wedstrijd van atleten die in personen.db staan."""
        uit = []
        for r in self.prestaties_db.execute(
            self._PRESTATIE_SELECT + " WHERE p.wedstrijd_id = ? ORDER BY o.naam, p.waarde", (wedstrijd_id,)
        ):
            master_id = self._master_id(r["atleet_ref"], "prestaties")
            if master_id is not None:
                uit.append(self._prestatie(r, master_id))
        return uit

    def prestatie_verwijderen(self, prestatie_id: int) -> None:
        with self.prestaties_db:
            self.prestaties_db.execute("DELETE FROM prestatie WHERE id = ?", (prestatie_id,))

    def prs(self, master_id: str) -> list[PR]:
        """Alle PR's van één atleet (uit de view `pr`)."""
        rijen = self.prestaties_db.execute(
            "SELECT onderdeel_id, waarde FROM pr WHERE atleet_ref = ?", (self._ref(master_id, "prestaties"),)
        )
        return [PR(master_id, r["onderdeel_id"], r["waarde"]) for r in rijen]

    def prs_van_groep(self, master_ids: Iterable[str], onderdeel_id: int) -> list[PR]:
        """PR's op één onderdeel voor meerdere atleten, beste eerst. Voor ploeg/vergelijk."""
        per_ref = {self._ref(m, "prestaties"): m for m in master_ids}
        if not per_ref:
            return []
        rijen = self.prestaties_db.execute(
            f"""SELECT pr.atleet_ref, pr.waarde, o.lager_is_beter FROM pr
                JOIN onderdeel o ON o.id = pr.onderdeel_id
                WHERE pr.onderdeel_id = ? AND pr.atleet_ref IN ({_vraagtekens(len(per_ref))})""",
            (onderdeel_id, *per_ref),
        ).fetchall()
        prs = [PR(per_ref[r["atleet_ref"]], onderdeel_id, r["waarde"]) for r in rijen]
        lager_beter = bool(rijen[0]["lager_is_beter"]) if rijen else True
        return sorted(prs, key=lambda pr: pr.waarde, reverse=not lager_beter)

    def inschrijving_opslaan(self, i: Inschrijving) -> None:
        if self.wedstrijd(i.wedstrijd_id) is None:
            raise OpslagFout(f"Wedstrijd {i.wedstrijd_id} bestaat niet.")
        ref = self._ref(i.atleet_id, "prestaties")
        with self.prestaties_db:
            # `IS` i.p.v. `=` omdat onderdeel_id leeg mag zijn (NULL telt niet als dubbel in een PRIMARY KEY).
            bestaat = self.prestaties_db.execute(
                "SELECT 1 FROM inschrijving WHERE atleet_ref = ? AND wedstrijd_id = ? AND onderdeel_id IS ?",
                (ref, i.wedstrijd_id, i.onderdeel_id),
            ).fetchone()
            if not bestaat:
                self.prestaties_db.execute(
                    "INSERT INTO inschrijving (atleet_ref, wedstrijd_id, onderdeel_id) VALUES (?, ?, ?)",
                    (ref, i.wedstrijd_id, i.onderdeel_id),
                )

    def inschrijving_verwijderen(self, i: Inschrijving) -> None:
        """Afmelden. Met onderdeel_id=None verdwijnen ALLE inschrijvingen van deze atleet voor deze wedstrijd."""
        ref = self._ref(i.atleet_id, "prestaties")
        with self.prestaties_db:
            if i.onderdeel_id is None:
                self.prestaties_db.execute(
                    "DELETE FROM inschrijving WHERE atleet_ref = ? AND wedstrijd_id = ?", (ref, i.wedstrijd_id))
            else:
                self.prestaties_db.execute(
                    "DELETE FROM inschrijving WHERE atleet_ref = ? AND wedstrijd_id = ? AND onderdeel_id = ?",
                    (ref, i.wedstrijd_id, i.onderdeel_id))

    def deelnemers(self, wedstrijd_id: int) -> list[Inschrijving]:
        """Alle inschrijvingen voor één wedstrijd (atleten die niet meer bestaan worden overgeslagen)."""
        uit = []
        for r in self.prestaties_db.execute(
            "SELECT atleet_ref, onderdeel_id FROM inschrijving WHERE wedstrijd_id = ?", (wedstrijd_id,)
        ):
            master_id = self._master_id(r["atleet_ref"], "prestaties")
            if master_id is not None:
                uit.append(Inschrijving(master_id, wedstrijd_id, r["onderdeel_id"]))
        return uit

    def wedstrijd_verwijderen(self, wedstrijd_id: int) -> None:
        """Een (afgelaste) geplande wedstrijd weghalen, met zijn inschrijvingen.

        Weigert als er al prestaties aan hangen: dan is hij gewoon gehouden.
        """
        if self.prestaties_db.execute(
            "SELECT 1 FROM prestatie WHERE wedstrijd_id = ? LIMIT 1", (wedstrijd_id,)
        ).fetchone():
            raise OpslagFout(f"Wedstrijd {wedstrijd_id} heeft al prestaties en wordt niet verwijderd.")
        with self.prestaties_db:   # inschrijvingen gaan mee (ON DELETE CASCADE)
            self.prestaties_db.execute("DELETE FROM wedstrijd WHERE id = ?", (wedstrijd_id,))

    def inschrijvingen(self, master_id: str) -> list[Inschrijving]:
        rijen = self.prestaties_db.execute(
            """SELECT i.wedstrijd_id, i.onderdeel_id FROM inschrijving i
               JOIN wedstrijd w ON w.id = i.wedstrijd_id
               WHERE i.atleet_ref = ? ORDER BY w.datum""",
            (self._ref(master_id, "prestaties"),),
        )
        return [Inschrijving(master_id, r["wedstrijd_id"], r["onderdeel_id"]) for r in rijen]

    # ============================================================
    # Testen (testen.db)
    # ============================================================
    def test_opslaan(self, t: Test) -> Test:
        with self.testen_db:
            r = self.testen_db.execute(
                """INSERT INTO test (naam, eenheid, lager_is_beter) VALUES (?, ?, ?)
                   ON CONFLICT (naam) DO UPDATE SET eenheid = excluded.eenheid,
                       lager_is_beter = excluded.lager_is_beter
                   RETURNING id""",
                (t.naam, t.eenheid, int(t.lager_is_beter)),
            ).fetchone()
        t.id = r[0]
        return t

    def testen(self) -> list[Test]:
        return [Test(r["naam"], r["eenheid"], bool(r["lager_is_beter"]), r["id"])
                for r in self.testen_db.execute("SELECT * FROM test ORDER BY naam")]

    def testresultaat_opslaan(self, t: Testresultaat) -> Testresultaat:
        ref = self._ref(t.atleet_id, "testen")
        with self.testen_db:
            waarden = (ref, t.test_id, _naar_tekst(t.datum), t.waarde, t.notities)
            if t.id is None:
                t.id = self.testen_db.execute(
                    "INSERT INTO testresultaat (atleet_ref, test_id, datum, waarde, notities) VALUES (?, ?, ?, ?, ?)",
                    waarden,
                ).lastrowid
            else:
                self.testen_db.execute(
                    "UPDATE testresultaat SET atleet_ref = ?, test_id = ?, datum = ?, waarde = ?, notities = ? WHERE id = ?",
                    (*waarden, t.id),
                )
        return t

    def testresultaten(self, master_id: str, test_id: int | None = None) -> list[Testresultaat]:
        """Testresultaten van één atleet, oudste eerst (handig voor een verloop)."""
        sql = "SELECT * FROM testresultaat WHERE atleet_ref = ?"
        args: list = [self._ref(master_id, "testen")]
        if test_id is not None:
            sql += " AND test_id = ?"
            args.append(test_id)
        sql += " ORDER BY datum"
        return [Testresultaat(master_id, r["test_id"], _naar_datum(r["datum"]), r["waarde"], r["notities"], r["id"])
                for r in self.testen_db.execute(sql, args)]

    # ============================================================
    # Trainingsschema (trainingsschema.db)
    # ============================================================
    def trainingsschema_opslaan(self, s: Trainingsschema) -> Trainingsschema:
        """Trainingsdagen van een atleet opslaan; een bestaand schema wordt overschreven."""
        if self.atleet(s.atleet_id) is None:
            raise OpslagFout(f"Atleet {s.atleet_id} bestaat niet.")
        dagen = [int(bool(getattr(s, d))) for d in DAGEN]
        with self.trainingsschema_db:
            self.trainingsschema_db.execute(
                f"""INSERT INTO trainingsschema (atleet_ref, {", ".join(DAGEN)})
                    VALUES (?, {_vraagtekens(len(DAGEN))})
                    ON CONFLICT (atleet_ref) DO UPDATE SET
                        {", ".join(f"{d} = excluded.{d}" for d in DAGEN)}""",  # DAGEN zijn vaste namen
                (self._ref(s.atleet_id, "trainingsschema"), *dagen),
            )
        return s

    def trainingsschema(self, master_id: str) -> Trainingsschema:
        """Het schema van één atleet. Zonder opgeslagen schema: alle dagen False."""
        r = self.trainingsschema_db.execute(
            "SELECT * FROM trainingsschema WHERE atleet_ref = ?", (self._ref(master_id, "trainingsschema"),)
        ).fetchone()
        if r is None:
            return Trainingsschema(master_id)
        return Trainingsschema(master_id, **{d: bool(r[d]) for d in DAGEN}, keuze=self.trainingskeuze(master_id))

    def trainingskeuze(self, master_id: str) -> dict[str, set[tuple[int, str]]]:
        """Gekozen trainingen per weekdag: {'zaterdag': {(groep_id, '10:30')}}.

        Een dag die er niet in staat: geen keuze gemaakt = alle trainingen van de
        groepen van de atleet op die dag. Keuzes voor een groep waar de atleet niet
        (meer) in zit, of een tijd die de groep niet meer heeft, tellen niet mee.
        """
        rijen = self.trainingsschema_db.execute(
            "SELECT dag, groep_id, starttijd FROM trainingskeuze WHERE atleet_ref = ?",
            (self._ref(master_id, "trainingsschema"),)).fetchall()
        if not rijen:
            return {}
        # Alleen keuzes die nog kloppen: de atleet zit in de groep en de groep traint dan
        # (nog) op die tijd. Blijft er voor een dag niets over, dan geldt weer 'alles'.
        groepen = {g.id: g for g in self.groepen_van_atleet(master_id)}
        uit: dict[str, set[tuple[int, str]]] = {}
        for r in rijen:
            g = groepen.get(r["groep_id"])
            if g is not None and r["starttijd"] in g.tijden(r["dag"]):
                uit.setdefault(r["dag"], set()).add((r["groep_id"], r["starttijd"]))
        return uit

    def trainingskeuze_opslaan(self, master_id: str, keuze: dict[str, Iterable[tuple[int, str]]]) -> None:
        """Vervang alle keuzes van de atleet. Een dag zonder (of met lege) keuze = alle trainingen."""
        if self.atleet(master_id) is None:
            raise OpslagFout(f"Atleet {master_id} bestaat niet.")
        ref = self._ref(master_id, "trainingsschema")
        rijen = []
        for d, paren in keuze.items():
            if d not in DAGEN:
                raise OpslagFout(f"Onbekende dag {d!r}; kies uit {DAGEN}.")
            for groep_id, tijd in paren:
                try:
                    tijd = normaliseer_tijd(tijd)
                except ValueError as e:
                    raise OpslagFout(str(e)) from None
                if tijd is None:
                    raise OpslagFout("Een gekozen training heeft een begintijd nodig.")
                rijen.append((ref, d, int(groep_id), tijd))
        with self.trainingsschema_db:
            self.trainingsschema_db.execute("DELETE FROM trainingskeuze WHERE atleet_ref = ?", (ref,))
            self.trainingsschema_db.executemany(
                "INSERT OR IGNORE INTO trainingskeuze (atleet_ref, dag, groep_id, starttijd) VALUES (?, ?, ?, ?)", rijen)

    def atleten_op_dag(self, dag: str, master_ids: Iterable[str] | None = None) -> list[str]:
        """master_ids van de atleten die op `dag` ('dinsdag') trainen.

        Met master_ids alleen binnen die atleten (bijv. de leden van een groep).
        Atleten die niet (meer) in personen.db staan, worden overgeslagen.
        """
        dag = dag.lower()
        if dag not in DAGEN:
            raise OpslagFout(f"Onbekende dag {dag!r}; kies uit {DAGEN}.")
        refs = self.trainingsschema_db.execute(
            f"SELECT atleet_ref FROM trainingsschema WHERE {dag} = 1"  # dag is gecontroleerd tegen DAGEN
        ).fetchall()
        ids = [m for m in (self._master_id(r[0], "trainingsschema") for r in refs) if m is not None]
        if master_ids is not None:
            binnen = set(master_ids)
            ids = [m for m in ids if m in binnen]
        return ids

    # ============================================================
    # Groepen, periodeplannen, trainingen, absentie (personen.db)
    # ============================================================
    def groep_opslaan(self, g: Groep) -> Groep:
        """Groep en ledenlijst opslaan. De leden in de database worden precies g.leden.

        De trainingstijden worden hier NIET opgeslagen (zie groep_trainingsdagen_opslaan),
        zodat alleen de leden opslaan (bijv. bij een CSV-import) de tijden niet wist.
        """
        with self.personen:
            if g.id is None:
                g.id = self.personen.execute(
                    "INSERT INTO groep (naam, seizoen) VALUES (?, ?)", (g.naam, g.seizoen)
                ).lastrowid
            else:
                self.personen.execute("UPDATE groep SET naam = ?, seizoen = ? WHERE id = ?",
                                      (g.naam, g.seizoen, g.id))
            self.personen.execute("DELETE FROM groep_lid WHERE groep_id = ?", (g.id,))
            self.personen.executemany("INSERT INTO groep_lid (groep_id, atleet_id) VALUES (?, ?)",
                                      [(g.id, m) for m in g.leden])
        return g

    def _groep(self, r) -> Groep:
        leden = [x[0] for x in self.personen.execute(
            """SELECT gl.atleet_id FROM groep_lid gl JOIN atleet a ON a.master_id = gl.atleet_id
               WHERE gl.groep_id = ? ORDER BY a.achternaam, a.voornaam""", (r["id"],))]
        t = self.personen.execute("SELECT * FROM groep_trainingstijden WHERE groep_id = ?", (r["id"],)).fetchone()
        tijden = {d: t[d] for d in DAGEN if t[d]} if t else {}
        extra: dict[str, list[str]] = {}
        for x in self.personen.execute(
                "SELECT dag, starttijd FROM groep_extra_trainingstijd WHERE groep_id = ? ORDER BY starttijd", (r["id"],)):
            if x["dag"] in tijden and x["starttijd"] != tijden[x["dag"]]:
                extra.setdefault(x["dag"], []).append(x["starttijd"])
        return Groep(r["naam"], r["seizoen"], leden, r["id"], trainingsdagen=tijden, extra_tijden=extra)

    def groep_trainingsdagen_opslaan(self, groep_id: int, dagen: dict[str, str]) -> None:
        """Trainingstijden van een groep opslaan (tabel groep_trainingstijden: één rij per groep).

        dagen: {'dinsdag': '18:30', 'donderdag': '19:00'}; elke dag heeft een begintijd.
        Dagen die er niet in staan: geen training. {} = geen vaste dagen (rij weg).
        """
        tijden: dict[str, str] = {}
        for d, t in dagen.items():
            if d not in DAGEN:
                raise OpslagFout(f"Onbekende dag {d!r}; kies uit {DAGEN}.")
            try:
                tijd = normaliseer_tijd(t)
            except ValueError as e:
                raise OpslagFout(str(e)) from None
            if tijd is None:
                raise OpslagFout(f"Geef een begintijd op voor {d}.")
            tijden[d] = tijd
        if self.groep(groep_id) is None:
            raise OpslagFout(f"Groep {groep_id} bestaat niet.")
        with self.personen:
            # Extra tijden horen bij een dag met een vaste tijd: vervalt de dag, dan vervallen ze ook.
            vervallen = [d for d in DAGEN if d not in tijden]
            if vervallen:
                self.personen.execute(
                    f"DELETE FROM groep_extra_trainingstijd WHERE groep_id = ? AND dag IN ({_vraagtekens(len(vervallen))})",
                    (groep_id, *vervallen))
            if not tijden:
                self.personen.execute("DELETE FROM groep_trainingstijden WHERE groep_id = ?", (groep_id,))
                return
            kolommen = ", ".join(DAGEN)                                   # DAGEN zijn vaste namen
            self.personen.execute(
                f"""INSERT INTO groep_trainingstijden (groep_id, {kolommen})
                    VALUES (?, {_vraagtekens(len(DAGEN))})
                    ON CONFLICT (groep_id) DO UPDATE SET {", ".join(f"{d} = excluded.{d}" for d in DAGEN)}""",
                (groep_id, *[tijden.get(d) for d in DAGEN]),
            )

    def groep_extra_tijden_opslaan(self, groep_id: int, extra: dict[str, list[str]]) -> None:
        """Extra begintijden per dag opslaan (tabel groep_extra_trainingstijd); vervangt alle extra tijden.

        extra: {'zaterdag': ['10:30']}. Alleen op dagen met een vaste begintijd
        (groep_trainingsdagen_opslaan eerst); een tijd gelijk aan de vaste tijd telt niet.
        """
        groep = self.groep(groep_id)
        if groep is None:
            raise OpslagFout(f"Groep {groep_id} bestaat niet.")
        rijen = set()
        for d, lijst in extra.items():
            if d not in DAGEN:
                raise OpslagFout(f"Onbekende dag {d!r}; kies uit {DAGEN}.")
            if lijst and d not in groep.trainingsdagen:
                raise OpslagFout(f"Een extra tijd op {d} kan alleen als {d} een vaste trainingsdag is.")
            for t in lijst:
                try:
                    tijd = normaliseer_tijd(t)
                except ValueError as e:
                    raise OpslagFout(str(e)) from None
                if tijd is not None and tijd != groep.trainingsdagen[d]:
                    rijen.add((groep_id, d, tijd))
        with self.personen:
            self.personen.execute("DELETE FROM groep_extra_trainingstijd WHERE groep_id = ?", (groep_id,))
            self.personen.executemany(
                "INSERT INTO groep_extra_trainingstijd (groep_id, dag, starttijd) VALUES (?, ?, ?)", sorted(rijen))

    def groep(self, groep_id: int) -> Groep | None:
        r = self.personen.execute("SELECT * FROM groep WHERE id = ?", (groep_id,)).fetchone()
        return self._groep(r) if r else None

    def groepen(self, seizoen: str | None = None) -> list[Groep]:
        if seizoen is None:
            rijen = self.personen.execute("SELECT * FROM groep ORDER BY seizoen DESC, naam").fetchall()
        else:
            rijen = self.personen.execute("SELECT * FROM groep WHERE seizoen = ? ORDER BY naam", (seizoen,)).fetchall()
        return [self._groep(r) for r in rijen]

    def groepen_van_atleet(self, master_id: str) -> list[Groep]:
        rijen = self.personen.execute(
            """SELECT g.* FROM groep g JOIN groep_lid gl ON gl.groep_id = g.id
               WHERE gl.atleet_id = ? ORDER BY g.seizoen DESC, g.naam""", (master_id,)
        ).fetchall()
        return [self._groep(r) for r in rijen]

    def periodeplan_opslaan(self, p: Periodeplan) -> Periodeplan:
        waarden = (p.groep_id, p.naam, _naar_tekst(p.startdatum), _naar_tekst(p.einddatum), p.doel)
        with self.personen:
            if p.id is None:
                p.id = self.personen.execute(
                    "INSERT INTO periodeplan (groep_id, naam, startdatum, einddatum, doel) VALUES (?, ?, ?, ?, ?)",
                    waarden,
                ).lastrowid
            else:
                self.personen.execute(
                    "UPDATE periodeplan SET groep_id = ?, naam = ?, startdatum = ?, einddatum = ?, doel = ? WHERE id = ?",
                    (*waarden, p.id),
                )
        return p

    def periodeplannen(self, groep_id: int) -> list[Periodeplan]:
        return [Periodeplan(r["naam"], _naar_datum(r["startdatum"]), _naar_datum(r["einddatum"]),
                            r["groep_id"], r["doel"], r["id"])
                for r in self.personen.execute(
                    "SELECT * FROM periodeplan WHERE groep_id = ? ORDER BY startdatum", (groep_id,))]

    _TRAINING_VELDEN = ("groep_id", "periodeplan_id", "datum", "onderwerp", "warming_up", "kern_a",
                        "kern_b", "cooling_down", "notities", "hoofdtraining_id", "starttijd")   # vaste kolomnamen

    def _training(self, r) -> Training:
        atleten = [x[0] for x in self.personen.execute(
            """SELECT ta.atleet_id FROM training_atleet ta JOIN atleet a ON a.master_id = ta.atleet_id
               WHERE ta.training_id = ? ORDER BY a.achternaam, a.voornaam""", (r["id"],))]
        return Training(r["groep_id"], _naar_datum(r["datum"]), r["onderwerp"], r["notities"],
                        r["periodeplan_id"], r["id"], r["warming_up"], r["kern_a"], r["kern_b"],
                        r["cooling_down"], r["hoofdtraining_id"], atleten, r["starttijd"])

    def training_opslaan(self, t: Training) -> Training:
        """Training toevoegen of bijwerken (met id).

        Gewone training: geen `atleten`. Afwijkende training: hoofdtraining_id =
        een gewone training; groep en datum worden daarvan overgenomen, en
        `atleten` (minstens één, allemaal lid van de groep) volgen deze variant.
        Een atleet kan per training maar in één variant zitten.
        """
        if t.hoofdtraining_id is None:
            if t.atleten:
                raise OpslagFout("Alleen een afwijkende training (met hoofdtraining) heeft eigen atleten.")
        else:
            hoofd = self.training(t.hoofdtraining_id)
            if hoofd is None or hoofd.is_afwijkend:
                raise OpslagFout(f"Training {t.hoofdtraining_id} is geen gewone training van een groep.")
            if t.id is not None and t.id == hoofd.id:
                raise OpslagFout("Een training kan geen variant van zichzelf zijn.")
            t.groep_id, t.datum, t.starttijd = hoofd.groep_id, hoofd.datum, hoofd.starttijd
            t.atleten = list(dict.fromkeys(t.atleten))
            if not t.atleten:
                raise OpslagFout("Kies minstens één atleet voor de afwijkende training.")
            groep = self.groep(t.groep_id)
            buiten = [m for m in t.atleten if groep is None or m not in groep.leden]
            if buiten:
                raise OpslagFout("Een afwijkende training is alleen voor atleten uit de groep.")
            al_elders = {m for v in self.varianten(hoofd.id) if v.id != t.id for m in v.atleten}
            if al_elders & set(t.atleten):
                raise OpslagFout("Een atleet staat al bij een andere afwijkende training op deze dag.")

        waarden = tuple(_naar_tekst(t.datum) if v == "datum" else getattr(t, v) for v in self._TRAINING_VELDEN)
        with self.personen:
            if t.id is None:
                t.id = self.personen.execute(
                    f"INSERT INTO training ({', '.join(self._TRAINING_VELDEN)}) "
                    f"VALUES ({_vraagtekens(len(self._TRAINING_VELDEN))})", waarden,
                ).lastrowid
            else:
                self.personen.execute(
                    f"UPDATE training SET {', '.join(f'{v} = ?' for v in self._TRAINING_VELDEN)} WHERE id = ?",
                    (*waarden, t.id),
                )
            self.personen.execute("DELETE FROM training_atleet WHERE training_id = ?", (t.id,))
            self.personen.executemany("INSERT INTO training_atleet (training_id, atleet_id) VALUES (?, ?)",
                                      [(t.id, m) for m in t.atleten])
        return t

    def trainingen(self, groep_id: int, van: date | None = None, tot: date | None = None) -> list[Training]:
        """De gewone trainingen van een groep (zonder afwijkende varianten), oudste eerst."""
        sql, args = "SELECT * FROM training WHERE groep_id = ? AND hoofdtraining_id IS NULL", [groep_id]
        if van:
            sql += " AND datum >= ?"
            args.append(_naar_tekst(van))
        if tot:
            sql += " AND datum <= ?"
            args.append(_naar_tekst(tot))
        sql += " ORDER BY datum, starttijd, id"      # zonder eigen tijd (= vaste tijd) eerst
        return [self._training(r) for r in self.personen.execute(sql, args).fetchall()]

    def training(self, training_id: int) -> Training | None:
        r = self.personen.execute("SELECT * FROM training WHERE id = ?", (training_id,)).fetchone()
        return self._training(r) if r else None

    def varianten(self, training_id: int) -> list[Training]:
        """De afwijkende trainingen bij een gewone training."""
        return [self._training(r) for r in self.personen.execute(
            "SELECT * FROM training WHERE hoofdtraining_id = ? ORDER BY id", (training_id,)).fetchall()]

    def training_voor_atleet(self, training_id: int, master_id: str) -> Training | None:
        """Wat deze atleet op deze training doet: zijn afwijkende training, anders de gewone."""
        t = self.training(training_id)
        if t is None:
            return None
        hoofd_id = t.hoofdtraining_id or t.id
        return next((v for v in self.varianten(hoofd_id) if master_id in v.atleten), self.training(hoofd_id))

    def training_verwijderen(self, training_id: int) -> None:
        """Verwijdert een training, zijn afwijkende varianten (CASCADE) en de absentie
        die erbij hoort (die staat in een ander bestand)."""
        with self.absentie_db:
            self.absentie_db.execute("DELETE FROM absentie WHERE training_id = ?", (training_id,))
        with self.personen:
            self.personen.execute("DELETE FROM training WHERE id = ?", (training_id,))

    # ============================================================
    # Absentie (absentie.db), lang formaat: één rij per atleet per training
    # ============================================================
    def absentie_opslaan(self, a: Absentie) -> None:
        """Status van één atleet op één training opslaan; een bestaande status wordt overschreven."""
        self.absenties_opslaan([a])

    def absenties_opslaan(self, absenties: Iterable[Absentie]) -> None:
        """Meerdere statuses in één transactie, bijv. een hele absentielijst."""
        absenties = list(absenties)
        for tid in {a.training_id for a in absenties}:
            t = self.training(tid)
            if t is None:
                raise OpslagFout(f"Training {tid} bestaat niet.")
            if t.is_afwijkend:
                raise OpslagFout("Aanwezigheid hoort bij de gewone training, niet bij een afwijkende variant.")
        for mid in {a.atleet_id for a in absenties}:
            if self.atleet(mid) is None:
                raise OpslagFout(f"Atleet {mid} bestaat niet.")
        with self.absentie_db:
            self.absentie_db.executemany(
                """INSERT INTO absentie (training_id, atleet_ref, status, reden) VALUES (?, ?, ?, ?)
                   ON CONFLICT (training_id, atleet_ref) DO UPDATE SET
                       status = excluded.status, reden = excluded.reden""",
                [(a.training_id, self._ref(a.atleet_id, "absentie"), a.status, a.reden) for a in absenties],
            )

    def absenties(self, training_id: int) -> list[Absentie]:
        """Alle ingevulde statuses van één training (atleten die niet meer bestaan worden overgeslagen)."""
        uit = []
        for r in self.absentie_db.execute("SELECT * FROM absentie WHERE training_id = ?", (training_id,)):
            master_id = self._master_id(r["atleet_ref"], "absentie")
            if master_id is not None:
                uit.append(Absentie(r["training_id"], master_id, r["status"], r["reden"]))
        return uit

    def absenties_van_atleet(self, master_id: str, groep_id: int | None = None) -> list[Absentie]:
        """Alle statuses van één atleet, oudste training eerst. Met groep_id alleen die groep."""
        rijen = self.absentie_db.execute(
            "SELECT * FROM absentie WHERE atleet_ref = ?", (self._ref(master_id, "absentie"),)
        ).fetchall()
        if not rijen:
            return []
        ids = sorted({r["training_id"] for r in rijen})
        sql = f"SELECT id, datum, groep_id FROM training WHERE id IN ({_vraagtekens(len(ids))})"
        trainingen = {t["id"]: t for t in self.personen.execute(sql, ids)}
        uit = [r for r in rijen if r["training_id"] in trainingen
               and (groep_id is None or trainingen[r["training_id"]]["groep_id"] == groep_id)]
        uit.sort(key=lambda r: (trainingen[r["training_id"]]["datum"], r["training_id"]))
        return [Absentie(r["training_id"], master_id, r["status"], r["reden"]) for r in uit]

    # ============================================================
    # Leerlijnen (personen.db)
    # ============================================================
    def leerlijn_opslaan(self, lijn: Leerlijn) -> Leerlijn:
        """Leerlijn en stappen opslaan. Stappen die niet meer in de lijst staan worden
        NIET verwijderd (dat zou de voortgang van atleten wissen)."""
        with self.personen:
            if lijn.id is None:
                lijn.id = self.personen.execute(
                    "INSERT INTO leerlijn (naam, beschrijving) VALUES (?, ?)", (lijn.naam, lijn.beschrijving)
                ).lastrowid
            else:
                self.personen.execute("UPDATE leerlijn SET naam = ?, beschrijving = ? WHERE id = ?",
                                      (lijn.naam, lijn.beschrijving, lijn.id))
            for s in lijn.stappen:
                s.leerlijn_id = lijn.id
                if s.id is None:
                    s.id = self.personen.execute(
                        "INSERT INTO leerlijn_stap (leerlijn_id, volgorde, naam, beschrijving) VALUES (?, ?, ?, ?)",
                        (lijn.id, s.volgorde, s.naam, s.beschrijving),
                    ).lastrowid
                else:
                    self.personen.execute(
                        "UPDATE leerlijn_stap SET leerlijn_id = ?, volgorde = ?, naam = ?, beschrijving = ? WHERE id = ?",
                        (lijn.id, s.volgorde, s.naam, s.beschrijving, s.id),
                    )
        return lijn

    def _leerlijn(self, r) -> Leerlijn:
        stappen = [LeerlijnStap(s["volgorde"], s["naam"], s["beschrijving"], s["leerlijn_id"], s["id"])
                   for s in self.personen.execute(
                       "SELECT * FROM leerlijn_stap WHERE leerlijn_id = ? ORDER BY volgorde", (r["id"],))]
        return Leerlijn(r["naam"], r["beschrijving"], stappen, r["id"])

    def leerlijn(self, leerlijn_id: int) -> Leerlijn | None:
        r = self.personen.execute("SELECT * FROM leerlijn WHERE id = ?", (leerlijn_id,)).fetchone()
        return self._leerlijn(r) if r else None

    def leerlijnen(self) -> list[Leerlijn]:
        return [self._leerlijn(r) for r in self.personen.execute("SELECT * FROM leerlijn ORDER BY naam").fetchall()]

    def voortgang_opslaan(self, v: LeerlijnVoortgang) -> None:
        with self.personen:
            self.personen.execute(
                """INSERT INTO atleet_leerlijn (atleet_id, stap_id, behaald_op, notities) VALUES (?, ?, ?, ?)
                   ON CONFLICT (atleet_id, stap_id) DO UPDATE SET
                       behaald_op = excluded.behaald_op, notities = excluded.notities""",
                (v.atleet_id, v.stap_id, _naar_tekst(v.behaald_op), v.notities),
            )

    def voortgang(self, master_id: str) -> list[LeerlijnVoortgang]:
        return [LeerlijnVoortgang(r["atleet_id"], r["stap_id"], _naar_datum(r["behaald_op"]), r["notities"])
                for r in self.personen.execute(
                    "SELECT * FROM atleet_leerlijn WHERE atleet_id = ?", (master_id,))]

    # ============================================================
    # Leerdoelen (leerlijnen.db): de catalogus, zonder persoonsgegevens
    # ============================================================
    @staticmethod
    def _leerdoel(r) -> Leerdoel:
        return Leerdoel(r["id"], r["leerlijn"], r["categorie"], r["volgorde"], r["omschrijving"],
                        r["bron"], r["fase"], bool(r["alleen_specialisten"]), bool(r["actief"]))

    def leerdoel_leerlijnen(self) -> list[tuple[str, str]]:
        """Alle leerlijnen als (code, naam), in vaste volgorde. Bijv. ('SPR', 'Sprint')."""
        return [(r["code"], r["naam"]) for r in self.leerlijnen_db.execute(
            "SELECT code, naam FROM leerlijn ORDER BY volgorde")]

    def scoreschaal(self) -> dict[int, str]:
        """Betekenis van de scores: {1: 'Nog niet', ..., 5: 'Beheerst'}."""
        return {r["score"]: r["label"] for r in self.leerlijnen_db.execute(
            "SELECT score, label FROM scoreschaal ORDER BY score")}

    def leerdoel(self, leerdoel_id: str) -> Leerdoel | None:
        r = self.leerlijnen_db.execute("SELECT * FROM leerdoel WHERE id = ?", (leerdoel_id,)).fetchone()
        return self._leerdoel(r) if r else None

    def leerdoelen(self, categorie: str | None = None, leerlijn: str | None = None,
                   doorlopend: bool = False, alleen_actief: bool = True) -> list[Leerdoel]:
        """Leerdoelen gesorteerd op categorie, leerlijn en volgorde.

        categorie:  alleen de doelen die in die categorie beginnen, bijv. 'U12'.
        doorlopend: met categorie: ook de doelen uit eerdere categorieën (wat een
                    atleet in die categorie allemaal zou moeten kunnen).
        leerlijn:   alleen één leerlijn, bijv. 'SPR'.
        """
        sql = ("SELECT d.* FROM leerdoel d JOIN categorie c ON c.code = d.categorie "
               "JOIN leerlijn l ON l.code = d.leerlijn WHERE 1 = 1")
        param: list = []
        if categorie is not None:
            if categorie not in CATEGORIEEN:
                raise OpslagFout(f"Onbekende categorie {categorie!r}; kies uit {CATEGORIEEN}.")
            sql += " AND c.volgorde <= (SELECT volgorde FROM categorie WHERE code = ?)" if doorlopend \
                else " AND d.categorie = ?"
            param.append(categorie)
        if leerlijn is not None:
            sql += " AND d.leerlijn = ?"
            param.append(leerlijn)
        if alleen_actief:
            sql += " AND d.actief = 1"
        sql += " ORDER BY c.volgorde, l.volgorde, d.volgorde"
        return [self._leerdoel(r) for r in self.leerlijnen_db.execute(sql, param)]

    # ============================================================
    # Leerdoelscores (leerdoelscores.db), lang formaat:
    # één rij per atleet per leerdoel per datum
    # ============================================================
    def leerdoelscore_opslaan(self, s: LeerdoelScore) -> None:
        """Eén score opslaan. Op dezelfde dag opnieuw scoren overschrijft die dag."""
        self.leerdoelscores_opslaan([s])

    def leerdoelscores_opslaan(self, scores: Iterable[LeerdoelScore]) -> None:
        """Meerdere scores in één transactie, bijv. een hele groep na een training."""
        scores = list(scores)
        bekend = {r[0] for r in self.leerlijnen_db.execute("SELECT id FROM leerdoel")}
        for lid in {s.leerdoel_id for s in scores}:
            if lid not in bekend:
                raise OpslagFout(f"Leerdoel {lid!r} bestaat niet.")
        for mid in {s.atleet_id for s in scores}:
            if self.atleet(mid) is None:
                raise OpslagFout(f"Atleet {mid} bestaat niet.")
        with self.leerdoelscores_db:
            self.leerdoelscores_db.executemany(
                """INSERT INTO leerdoelscore (atleet_ref, leerdoel_id, score, datum, notities)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (atleet_ref, leerdoel_id, datum) DO UPDATE SET
                       score = excluded.score, notities = excluded.notities""",
                [(self._ref(s.atleet_id, "leerdoelscores"), s.leerdoel_id, s.score,
                  _naar_tekst(s.datum), s.notities) for s in scores],
            )

    def leerdoelscore_verwijderen(self, master_id: str, leerdoel_id: str, datum: date) -> None:
        with self.leerdoelscores_db:
            self.leerdoelscores_db.execute(
                "DELETE FROM leerdoelscore WHERE atleet_ref = ? AND leerdoel_id = ? AND datum = ?",
                (self._ref(master_id, "leerdoelscores"), leerdoel_id, _naar_tekst(datum)))

    def leerdoelscores(self, master_id: str, leerdoel_id: str | None = None) -> list[LeerdoelScore]:
        """De hele geschiedenis van één atleet (oudste eerst), eventueel voor één leerdoel."""
        sql = "SELECT * FROM leerdoelscore WHERE atleet_ref = ?"
        param: list = [self._ref(master_id, "leerdoelscores")]
        if leerdoel_id is not None:
            sql += " AND leerdoel_id = ?"
            param.append(leerdoel_id)
        sql += " ORDER BY datum, leerdoel_id"
        return [LeerdoelScore(master_id, r["leerdoel_id"], r["score"], _naar_datum(r["datum"]), r["notities"])
                for r in self.leerdoelscores_db.execute(sql, param)]

    def laatste_leerdoelscores(self, master_id: str) -> dict[str, LeerdoelScore]:
        """De meest recente score per leerdoel van één atleet: {leerdoel_id: LeerdoelScore}."""
        return {r["leerdoel_id"]: LeerdoelScore(master_id, r["leerdoel_id"], r["score"],
                                                _naar_datum(r["datum"]), r["notities"])
                for r in self.leerdoelscores_db.execute(
                    "SELECT * FROM laatste_leerdoelscore WHERE atleet_ref = ?",
                    (self._ref(master_id, "leerdoelscores"),))}

    def leerdoelscores_breed(self, master_ids: Iterable[str], leerdoel_ids: Iterable[str] | None = None,
                             ) -> dict[str, dict[str, int | None]]:
        """Overzicht in breed formaat voor het scherm: per atleet per leerdoel de laatste score.

        Geeft {master_id: {leerdoel_id: score of None}}. Zonder leerdoel_ids: alle
        leerdoelen die minstens één van deze atleten een score heeft. Wordt alleen
        berekend, nooit opgeslagen.
        """
        master_ids = list(master_ids)
        laatste = {m: self.laatste_leerdoelscores(m) for m in master_ids}
        if leerdoel_ids is None:
            leerdoel_ids = sorted({lid for scores in laatste.values() for lid in scores})
        leerdoel_ids = list(leerdoel_ids)
        return {m: {lid: (laatste[m][lid].score if lid in laatste[m] else None) for lid in leerdoel_ids}
                for m in master_ids}

    # ============================================================
    # Notities (notities.db): vrije tekst per atleet per datum
    # ============================================================
    @staticmethod
    def _notitie(r, master_id: str) -> Notitie:
        return Notitie(master_id, _naar_datum(r["datum"]), r["inhoud"], r["id"],
                       r["aangemaakt_op"], r["bijgewerkt_op"])

    def notitie_opslaan(self, n: Notitie) -> Notitie:
        """Nieuwe notitie toevoegen, of een bestaande (met id) aanpassen."""
        if self.atleet(n.atleet_id) is None:
            raise OpslagFout(f"Atleet {n.atleet_id} bestaat niet.")
        ref = self._ref(n.atleet_id, "notities")
        with self.notities_db:
            if n.id is None:
                n.id = self.notities_db.execute(
                    "INSERT INTO notitie (atleet_ref, datum, inhoud) VALUES (?, ?, ?)",
                    (ref, _naar_tekst(n.datum), n.inhoud),
                ).lastrowid
            else:
                cur = self.notities_db.execute(
                    """UPDATE notitie SET atleet_ref = ?, datum = ?, inhoud = ?, bijgewerkt_op = datetime('now')
                       WHERE id = ?""",
                    (ref, _naar_tekst(n.datum), n.inhoud, n.id),
                )
                if cur.rowcount == 0:
                    raise OpslagFout(f"Notitie {n.id} bestaat niet.")
        r = self.notities_db.execute(
            "SELECT aangemaakt_op, bijgewerkt_op FROM notitie WHERE id = ?", (n.id,)).fetchone()
        n.aangemaakt_op, n.bijgewerkt_op = r["aangemaakt_op"], r["bijgewerkt_op"]
        return n

    def notitie(self, notitie_id: int) -> Notitie | None:
        r = self.notities_db.execute("SELECT * FROM notitie WHERE id = ?", (notitie_id,)).fetchone()
        if r is None:
            return None
        master_id = self._master_id(r["atleet_ref"], "notities")
        return self._notitie(r, master_id) if master_id is not None else None

    def notities(self, master_id: str | None = None, van: date | None = None, tot: date | None = None,
                 zoek: str | None = None) -> list[Notitie]:
        """Notities, nieuwste eerst.

        master_id: alleen van deze atleet (anders van iedereen, bijv. alles van één training).
        van / tot: datumbereik (beide inclusief).
        zoek:      tekst die in de notitie voorkomt (hoofdletterongevoelig).
        """
        sql, args = "SELECT * FROM notitie WHERE 1 = 1", []
        if master_id is not None:
            sql += " AND atleet_ref = ?"
            args.append(self._ref(master_id, "notities"))
        if van:
            sql += " AND datum >= ?"
            args.append(_naar_tekst(van))
        if tot:
            sql += " AND datum <= ?"
            args.append(_naar_tekst(tot))
        if zoek and zoek.strip():
            sql += " AND inhoud LIKE ?"
            args.append(f"%{zoek.strip()}%")
        sql += " ORDER BY datum DESC, id DESC"
        uit = []
        for r in self.notities_db.execute(sql, args):
            mid = master_id or self._master_id(r["atleet_ref"], "notities")
            if mid is not None:
                uit.append(self._notitie(r, mid))
        return uit

    def notitie_verwijderen(self, notitie_id: int) -> None:
        with self.notities_db:
            self.notities_db.execute("DELETE FROM notitie WHERE id = ?", (notitie_id,))
