"""Alle SQL op één plek: zet databaserijen om naar modellen en terug.

De rest van de app praat alleen met `Opslag` en krijgt/geeft modellen uit
models/. Buiten dit bestand is geen SQL nodig, en niemand buiten db/ hoeft te
weten dat de gegevens over vijf versleutelde bestanden verdeeld zijn.

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
    Leerlijn,
    LeerlijnStap,
    LeerlijnVoortgang,
    Onderdeel,
    Periodeplan,
    Prestatie,
    Test,
    Testresultaat,
    Training,
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
    """Toegang tot de vijf AVS-databases met modellen in en modellen uit."""

    def __init__(self, map: Path | None = None, hoofd: str | bytes | None = None) -> None:
        self._map = Path(map) if map else None
        # Eén keer de sleutel ophalen, niet bij elk pseudoniem opnieuw.
        self._hoofd = hoofd if hoofd is not None else hoofdsleutel()
        self.personen = verbind("personen", self._map, self._hoofd)
        self.prestaties_db = verbind("prestaties", self._map, self._hoofd)
        self.testen_db = verbind("testen", self._map, self._hoofd)
        self.trainingsschema_db = verbind("trainingsschema", self._map, self._hoofd)
        self.absentie_db = verbind("absentie", self._map, self._hoofd)
        self._terug: dict[str, dict[str, str]] = {}

    # ---------- openen / sluiten ----------
    def sluit(self) -> None:
        for conn in (self.personen, self.prestaties_db, self.testen_db, self.trainingsschema_db, self.absentie_db):
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
        """Verwijdert een atleet en AL zijn gegevens uit alle vijf de databases.

        Bedoeld voor een verzoek tot verwijdering (AVG). Wie alleen niet meer
        traint: zet `actief = False` en sla op.
        """
        ref_p = self._ref(master_id, "prestaties")
        ref_t = self._ref(master_id, "testen")
        ref_s = self._ref(master_id, "trainingsschema")
        ref_a = self._ref(master_id, "absentie")
        with self.prestaties_db:
            self.prestaties_db.execute("DELETE FROM prestatie WHERE atleet_ref = ?", (ref_p,))
            self.prestaties_db.execute("DELETE FROM inschrijving WHERE atleet_ref = ?", (ref_p,))
        with self.testen_db:
            self.testen_db.execute("DELETE FROM testresultaat WHERE atleet_ref = ?", (ref_t,))
        with self.trainingsschema_db:
            self.trainingsschema_db.execute("DELETE FROM trainingsschema WHERE atleet_ref = ?", (ref_s,))
        with self.absentie_db:
            self.absentie_db.execute("DELETE FROM absentie WHERE atleet_ref = ?", (ref_a,))
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
        return Trainingsschema(master_id, **{d: bool(r[d]) for d in DAGEN})

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
        """Groep en ledenlijst opslaan. De leden in de database worden precies g.leden."""
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
        return Groep(r["naam"], r["seizoen"], leden, r["id"])

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

    def training_opslaan(self, t: Training) -> Training:
        waarden = (t.groep_id, t.periodeplan_id, _naar_tekst(t.datum), t.onderwerp, t.inhoud)
        with self.personen:
            if t.id is None:
                t.id = self.personen.execute(
                    "INSERT INTO training (groep_id, periodeplan_id, datum, onderwerp, inhoud) VALUES (?, ?, ?, ?, ?)",
                    waarden,
                ).lastrowid
            else:
                self.personen.execute(
                    "UPDATE training SET groep_id = ?, periodeplan_id = ?, datum = ?, onderwerp = ?, inhoud = ? WHERE id = ?",
                    (*waarden, t.id),
                )
        return t

    def trainingen(self, groep_id: int, van: date | None = None, tot: date | None = None) -> list[Training]:
        sql, args = "SELECT * FROM training WHERE groep_id = ?", [groep_id]
        if van:
            sql += " AND datum >= ?"
            args.append(_naar_tekst(van))
        if tot:
            sql += " AND datum <= ?"
            args.append(_naar_tekst(tot))
        sql += " ORDER BY datum"
        return [Training(r["groep_id"], _naar_datum(r["datum"]), r["onderwerp"], r["inhoud"],
                         r["periodeplan_id"], r["id"])
                for r in self.personen.execute(sql, args)]

    def training(self, training_id: int) -> Training | None:
        r = self.personen.execute("SELECT * FROM training WHERE id = ?", (training_id,)).fetchone()
        if r is None:
            return None
        return Training(r["groep_id"], _naar_datum(r["datum"]), r["onderwerp"], r["inhoud"],
                        r["periodeplan_id"], r["id"])

    def training_verwijderen(self, training_id: int) -> None:
        """Verwijdert een training en de absentie die erbij hoort (die staat in een ander bestand)."""
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
            if self.training(tid) is None:
                raise OpslagFout(f"Training {tid} bestaat niet.")
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
