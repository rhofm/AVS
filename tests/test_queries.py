"""Tests voor src/db/queries.py, met echte (versleutelde) databases in een tijdelijke map.

Gebruikt een vaste testsleutel: raakt de sleutelkluis en data/ nooit aan.
Alleen nepgegevens.
Vereist: pip install sqlcipher3-wheels keyring
"""

import contextlib
import io
import tempfile
from datetime import date
from pathlib import Path

from db.init_db import DB_DIR, init_db, pseudoniem, verbind
from db.queries import Opslag, OpslagFout
from models import (
    PR, heeft_windmeting, Absentie, Atleet, Groep, Inschrijving, Leerlijn, LeerlijnStap, LeerlijnVoortgang,
    Onderdeel, Prestatie, Test, Testresultaat, Training, Trainingsschema, Wedstrijd, Notitie,
)
from hulp import TESTSLEUTEL, verwacht as _verwacht


@contextlib.contextmanager
def opslag():
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):  # init_db print meldingen
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            yield db


def _basis(db: Opslag):
    anna = db.atleet_opslaan(Atleet("Anna", "Voorbeeld", geslacht="V", geboortedatum="2010", atletieknu_id="123456"))
    tim = db.atleet_opslaan(Atleet("Tim", "Proefmans", geslacht="M"))
    sprint = db.onderdeel_opslaan(Onderdeel("100m", "tijd", True, "sprint"))
    ver = db.onderdeel_opslaan(Onderdeel("Verspringen", "afstand", False, "springen"))
    return anna, tim, sprint, ver


def test_atleten():
    with opslag() as db:
        anna, tim, _, _ = _basis(db)
        assert len(anna.master_id) == 32 and anna.aangemaakt_op
        assert db.atleet(anna.master_id).naam == "Anna Voorbeeld"
        assert db.atleet_op_atletieknu_id("123456").master_id == anna.master_id
        assert [a.voornaam for a in db.atleten_zoeken("proef")] == ["Tim"]

        # Tussenvoegsel: aparte kolom, zoeken op de volledige naam, sorteren op achternaam.
        jan = db.atleet_opslaan(Atleet("Jan", "Vries", tussenvoegsel="de"))
        terug = db.atleet(jan.master_id)
        assert (terug.tussenvoegsel, terug.achternaam, terug.naam) == ("de", "Vries", "Jan de Vries")
        assert [a.voornaam for a in db.atleten_zoeken("jan de vr")] == ["Jan"]
        assert [a.voornaam for a in db.atleten()] == ["Tim", "Anna", "Jan"]
        terug.tussenvoegsel = None
        db.atleet_opslaan(terug)
        assert db.atleet(jan.master_id).naam == "Jan Vries"
        db.atleet_verwijderen(jan.master_id)

        tim.actief = False
        tim.specialisatie = "sprint"
        db.atleet_opslaan(tim)
        assert db.atleet(tim.master_id).specialisatie == "sprint"
        assert [a.voornaam for a in db.atleten()] == ["Anna"]
        assert len(db.atleten(alleen_actief=False)) == 2


def test_prestaties_geen_master_id_of_naam_in_prestaties_db():
    with opslag() as db:
        anna, _, sprint, _ = _basis(db)
        p = Prestatie("100m", date(2026, 6, 1), 13.2, bron="handmatig").gekoppeld(anna.master_id)
        assert db.prestatie_opslaan(p)
        rij = db.prestaties_db.execute("SELECT * FROM prestatie").fetchone()
        assert rij["atleet_ref"] == pseudoniem(anna.master_id, "prestaties", TESTSLEUTEL)
        assert anna.master_id not in [str(v) for v in tuple(rij)]


def test_prestaties_en_prs():
    with opslag() as db:
        anna, tim, sprint, ver = _basis(db)
        w = db.wedstrijd_opslaan(Wedstrijd("Clubkampioenschap", date(2026, 6, 1), bron="atletieknu",
                                           bron_url="https://example.org/wedstrijd/1"))
        # Dezelfde link nog eens: zelfde wedstrijd.
        assert db.wedstrijd_opslaan(Wedstrijd("x", date(2026, 6, 1), bron_url=w.bron_url)).id == w.id

        ps = [
            Prestatie("100m", date(2026, 6, 1), 13.2, wedstrijd_id=w.id, ronde="serie", wind=0.4),
            Prestatie("100m", date(2026, 6, 1), 12.9, wedstrijd_id=w.id, ronde="finale", wind=1.2),
            Prestatie("Verspringen", date(2026, 6, 1), 4.5, wedstrijd_id=w.id, wind=-0.3),
            Prestatie("Verspringen", date(2026, 7, 1), 4.8, wind=1.9),
        ]
        assert db.prestaties_opslaan(p.gekoppeld(anna.master_id) for p in ps) == (4, 0)
        # Zelfde import nog eens: niets dubbel.
        assert db.prestaties_opslaan(p.gekoppeld(anna.master_id) for p in ps) == (0, 4)
        assert db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 13.5, wind=0.0).gekoppeld(tim.master_id))

        assert len(db.prestaties(anna.master_id)) == 4
        assert sorted(p.waarde for p in db.prestaties(anna.master_id, sprint.id)) == [12.9, 13.2]
        assert db.prestaties(anna.master_id)[0].datum == date(2026, 7, 1)  # nieuwste eerst

        prs = {pr.onderdeel_id: pr.waarde for pr in db.prs(anna.master_id)}
        assert prs == {sprint.id: 12.9, ver.id: 4.8}

        groep = db.prs_van_groep([anna.master_id, tim.master_id], sprint.id)
        assert [(pr.atleet_id, pr.waarde) for pr in groep] == [(anna.master_id, 12.9), (tim.master_id, 13.5)]

        van_wedstrijd = db.prestaties_van_wedstrijd(w.id)
        assert len(van_wedstrijd) == 3 and {p.atleet_id for p in van_wedstrijd} == {anna.master_id}


def test_pr_alleen_windlegaal():
    with opslag() as db:
        versie = db.prestaties_db.execute("SELECT MAX(versie) FROM schema_version").fetchone()[0]
        assert versie >= 2, "migratie prestaties/002 is niet toegepast"
        anna, tim, sprint, ver = _basis(db)
        assert sprint.windmeting and ver.windmeting
        for waarde, wind in [(13.2, 1.1), (12.9, 2.6), (13.0, 2.0), (12.8, None)]:
            db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), waarde, wind=wind,
                                           ronde=str(waarde)).gekoppeld(anna.master_id))
        db.prestatie_opslaan(Prestatie("Verspringen", date(2026, 6, 1), 5.1, wind=3.0).gekoppeld(anna.master_id))
        db.prestatie_opslaan(Prestatie("Verspringen", date(2026, 7, 1), 5.3).gekoppeld(anna.master_id))
        prs = {pr.onderdeel_id: pr.waarde for pr in db.prs(anna.master_id)}
        # 12,9 (+2,6) en 12,8 (geen windmeting) tellen niet; 13,0 (precies +2,0) wel.
        assert prs[sprint.id] == 13.0
        assert ver.id not in prs  # te veel wind en geen meting: geen PR
        assert db.prs_van_groep([anna.master_id], ver.id) == []

        # Bij een onderdeel zonder windmeting telt alles, ook met een (onzinnige) windwaarde.
        acht = db.onderdeel_opslaan(Onderdeel("800m", "tijd", True, "midden"))
        assert not acht.windmeting
        db.prestatie_opslaan(Prestatie("800m", date(2026, 6, 1), 140.5).gekoppeld(tim.master_id))
        db.prestatie_opslaan(Prestatie("800m", date(2026, 7, 1), 139.9, wind=4.0).gekoppeld(tim.master_id))
        assert db.prs(tim.master_id) == [PR(tim.master_id, acht.id, 139.9)]


def test_windmeting_handmatig_aan_te_passen():
    with opslag() as db:
        o = db.onderdeel_opslaan(Onderdeel("100m horden", "tijd", True, "horden"))
        assert o.windmeting
        o.windmeting = False
        db.onderdeel_opslaan(o)
        assert not db.onderdeel("100m horden").windmeting


def test_indoor_telt_altijd():
    with opslag() as db:
        anna, _, sprint, ver = _basis(db)
        zestig = db.onderdeel_opslaan(Onderdeel("60m", "tijd", True, "sprint"))
        hal = db.wedstrijd_opslaan(Wedstrijd("Indoor Apeldoorn", date(2026, 1, 10), indoor=True))
        baan = db.wedstrijd_opslaan(Wedstrijd("Baan", date(2026, 5, 10)))
        db.prestatie_opslaan(Prestatie("60m", date(2026, 1, 10), 8.10, wedstrijd_id=hal.id).gekoppeld(anna.master_id))
        db.prestatie_opslaan(Prestatie("60m", date(2026, 5, 10), 8.00, wedstrijd_id=baan.id).gekoppeld(anna.master_id))
        assert db.prestaties(anna.master_id, zestig.id)[1].indoor            # overgenomen van de wedstrijd
        assert {pr.onderdeel_id: pr.waarde for pr in db.prs(anna.master_id)} == {zestig.id: 8.10}

        # Wedstrijd achteraf als indoor markeren: bestaande prestaties volgen.
        baan.indoor = True
        db.wedstrijd_opslaan(baan)
        assert db.wedstrijd(baan.id).indoor
        assert {pr.onderdeel_id: pr.waarde for pr in db.prs(anna.master_id)} == {zestig.id: 8.00}

        # Losse indoorprestatie zonder wedstrijd (bijv. handmatig).
        db.prestatie_opslaan(Prestatie("Verspringen", date(2026, 2, 1), 5.0, indoor=True).gekoppeld(anna.master_id))
        assert db.prs_van_groep([anna.master_id], ver.id)[0].waarde == 5.0


WINDNAMEN = [
    "60m", "100m", "150 m", "200m", "200 meter", "100m sprint", "Verspringen", "Hinkstapspringen",
    "verspringen (zone)", "300m", "400m", "1000m", "80m horden", "100m Hurdles", "4x100m",
    "4 x 60m", "1 mijl", "Hoogspringen", "Kogelstoten", "Speerwerpen 600g", "60m horden 76,2cm",
    "60mH", "110 meter horden", "200m horden", "300m horden", "400mH", "100mh", "4x80m horden",
]


def test_migratie_op_bestaande_database():
    """Een database op versie 1 krijgt migratie 002 bij de volgende init_db().
    De SQL-indeling van bestaande onderdelen moet gelijk zijn aan heeft_windmeting()."""
    import db.init_db as init_mod
    with tempfile.TemporaryDirectory() as tmp:
        echte_map = init_mod.MIGRATIONS_DIR
        try:
            init_mod.MIGRATIONS_DIR = Path(tmp) / "geen_migraties"
            init_mod.MIGRATIONS_DIR.mkdir()           # lege map: wel geïnstalleerd, geen migraties
            with contextlib.redirect_stdout(io.StringIO()):
                init_db(Path(tmp), hoofd=TESTSLEUTEL)
        finally:
            init_mod.MIGRATIONS_DIR = echte_map
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            assert db.prestaties_db.execute("SELECT MAX(versie) FROM schema_version").fetchone()[0] == 1
            # Versie 1 kent de kolom windmeting nog niet: onderdelen rechtstreeks invoeren.
            with db.prestaties_db:
                db.prestaties_db.executemany(
                    "INSERT INTO onderdeel (naam, eenheid, lager_is_beter) VALUES (?, 'tijd', 1)",
                    [(n,) for n in WINDNAMEN],
                )
            honderd = db.prestaties_db.execute("SELECT id FROM onderdeel WHERE naam = '100m'").fetchone()[0]
            # Ook de atleet rechtstreeks: personen.db op versie 1 kent nieuwere kolommen
            # (zoals au_licentienummer, migratie 009) nog niet.
            with db.personen:
                db.personen.execute("INSERT INTO atleet (master_id, voornaam, achternaam) VALUES (?, 'Anna', 'Voorbeeld')",
                                    ("b" * 32,))
            anna = Atleet("Anna", "Voorbeeld", master_id="b" * 32)
            # Ook prestaties rechtstreeks: versie 1 kent de kolom indoor nog niet.
            ref = pseudoniem(anna.master_id, "prestaties", TESTSLEUTEL)
            with db.prestaties_db:
                db.prestaties_db.executemany(
                    "INSERT INTO prestatie (atleet_ref, onderdeel_id, datum, waarde, wind) VALUES (?, ?, ?, ?, ?)",
                    [(ref, honderd, "2026-06-01", 12.9, 2.6), (ref, honderd, "2026-06-02", 13.1, None)],
                )
            assert db.prs(anna.master_id)[0].waarde == 12.9  # oude view telt alles mee
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            assert db.prestaties_db.execute("SELECT MAX(versie) FROM schema_version").fetchone()[0] == 4   # 002 + 003 (tijdschema) + 004 (doelen)
            assert db.prs(anna.master_id) == []                  # te veel wind / geen meting
            assert len(db.prestaties(anna.master_id)) == 2       # de prestaties zelf zijn er nog
            sql = {o.naam: o.windmeting for o in db.onderdelen()}
            python = {n: heeft_windmeting(n) for n in WINDNAMEN}
            assert sql == python, {n: (sql[n], python[n]) for n in WINDNAMEN if sql[n] != python[n]}


def test_prestatie_fouten():
    with opslag() as db:
        anna, _, _, _ = _basis(db)
        _verwacht(OpslagFout, lambda: db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 13.0)))
        _verwacht(OpslagFout, lambda: db.prestatie_opslaan(
            Prestatie("Hamerslingeren", date(2026, 6, 1), 30.0).gekoppeld(anna.master_id)))
        _verwacht(OpslagFout, lambda: db.prestatie_opslaan(
            Prestatie("100m", date(2026, 6, 1), 13.0, wedstrijd_id=999).gekoppeld(anna.master_id)))


def test_inschrijvingen():
    with opslag() as db:
        anna, _, sprint, _ = _basis(db)
        w = db.wedstrijd_opslaan(Wedstrijd("Competitie", date(2026, 9, 1)))
        for _ in range(2):
            db.inschrijving_opslaan(Inschrijving(anna.master_id, w.id))
            db.inschrijving_opslaan(Inschrijving(anna.master_id, w.id, sprint.id))
        assert len(db.inschrijvingen(anna.master_id)) == 2
        _verwacht(OpslagFout, lambda: db.inschrijving_opslaan(Inschrijving(anna.master_id, 999)))


def test_testen():
    with opslag() as db:
        anna, _, _, _ = _basis(db)
        t = db.test_opslaan(Test("30m vliegend", "s", True))
        db.testresultaat_opslaan(Testresultaat(anna.master_id, t.id, date(2026, 10, 1), 3.9))
        db.testresultaat_opslaan(Testresultaat(anna.master_id, t.id, date(2026, 9, 1), 4.1))
        assert [r.waarde for r in db.testresultaten(anna.master_id, t.id)] == [4.1, 3.9]  # oudste eerst
        rij = db.testen_db.execute("SELECT atleet_ref FROM testresultaat").fetchone()
        # Ander pseudoniem dan in prestaties.db.
        assert rij[0] == pseudoniem(anna.master_id, "testen", TESTSLEUTEL)
        assert rij[0] != pseudoniem(anna.master_id, "prestaties", TESTSLEUTEL)


def test_trainingsschema():
    with opslag() as db:
        anna, tim, _, _ = _basis(db)
        # Zonder opgeslagen schema: geen trainingsdagen.
        assert db.trainingsschema(anna.master_id).dagen == []

        db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["dinsdag", "donderdag"]))
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(tim.master_id, ["donderdag", "zaterdag"]))
        assert db.trainingsschema(anna.master_id).dagen == ["dinsdag", "donderdag"]

        # Overschrijven, niet een tweede rij.
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["maandag", "donderdag"]))
        assert db.trainingsschema(anna.master_id).dagen == ["maandag", "donderdag"]
        assert db.trainingsschema_db.execute("SELECT count(*) FROM trainingsschema").fetchone()[0] == 2

        assert sorted(db.atleten_op_dag("Donderdag")) == sorted([anna.master_id, tim.master_id])
        assert db.atleten_op_dag("zaterdag") == [tim.master_id]
        assert db.atleten_op_dag("donderdag", master_ids=[anna.master_id]) == [anna.master_id]
        assert db.atleten_op_dag("zondag") == []
        _verwacht(OpslagFout, lambda: db.atleten_op_dag("maandag; DROP TABLE trainingsschema"))
        _verwacht(OpslagFout, lambda: db.trainingsschema_opslaan(Trainingsschema("0" * 32, maandag=True)))

        # Eigen pseudoniem, anders dan in prestaties.db en testen.db.
        refs = {r[0] for r in db.trainingsschema_db.execute("SELECT atleet_ref FROM trainingsschema")}
        assert pseudoniem(anna.master_id, "trainingsschema", TESTSLEUTEL) in refs
        assert anna.master_id not in refs
        assert pseudoniem(anna.master_id, "prestaties", TESTSLEUTEL) not in refs
        assert pseudoniem(anna.master_id, "testen", TESTSLEUTEL) not in refs


def test_bestaande_installatie_krijgt_trainingsschema():
    """Wie al drie databases heeft, krijgt trainingsschema.db erbij met dezelfde sleutel."""
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
            (Path(tmp) / "trainingsschema.db").unlink()   # zoals vóór deze database bestond
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            anna = db.atleet_opslaan(Atleet("Anna", "Voorbeeld"))
            db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["woensdag"]))
            assert db.trainingsschema(anna.master_id).woensdag


def test_groepen_trainingen_absentie():
    with opslag() as db:
        anna, tim, _, _ = _basis(db)
        g = db.groep_opslaan(Groep("Junioren C", "2026-2027", [anna.master_id, tim.master_id]))
        assert db.groep(g.id).leden == [tim.master_id, anna.master_id]  # op achternaam
        g.verwijder(tim.master_id)
        db.groep_opslaan(g)
        assert db.groep(g.id).leden == [anna.master_id]
        assert [x.naam for x in db.groepen_van_atleet(anna.master_id)] == ["Junioren C"]

        tr = db.training_opslaan(Training(g.id, date(2026, 10, 14), "Starts"))
        db.absentie_opslaan(Absentie(tr.id, anna.master_id, "afgemeld", "school"))
        db.absentie_opslaan(Absentie(tr.id, anna.master_id, "aanwezig"))  # bijwerken
        assert [(a.status, a.reden) for a in db.absenties(tr.id)] == [("aanwezig", None)]
        assert len(db.trainingen(g.id, van=date(2026, 10, 1))) == 1


def test_absentie_eigen_database():
    with opslag() as db:
        anna, tim, _, _ = _basis(db)
        g = db.groep_opslaan(Groep("Junioren C", leden=[anna.master_id, tim.master_id]))
        tr1 = db.training_opslaan(Training(g.id, date(2026, 10, 13)))
        tr2 = db.training_opslaan(Training(g.id, date(2026, 10, 15)))
        db.absenties_opslaan([Absentie(tr1.id, anna.master_id, "aanwezig"),
                              Absentie(tr1.id, tim.master_id, "blessure", "enkel")])
        db.absentie_opslaan(Absentie(tr2.id, anna.master_id, "afgemeld"))

        # Lang formaat in absentie.db, met een eigen pseudoniem en zonder master_id.
        rijen = db.absentie_db.execute("SELECT training_id, atleet_ref, status FROM absentie").fetchall()
        assert len(rijen) == 3
        refs = {r["atleet_ref"] for r in rijen}
        assert pseudoniem(anna.master_id, "absentie", TESTSLEUTEL) in refs
        assert anna.master_id not in refs
        assert refs.isdisjoint({pseudoniem(anna.master_id, d, TESTSLEUTEL)
                                for d in ("prestaties", "testen", "trainingsschema")})
        # personen.db heeft geen absentietabel meer.
        assert db.personen.execute(
            "SELECT count(*) FROM sqlite_master WHERE name LIKE 'absentie%'").fetchone()[0] == 0

        assert {(a.atleet_id, a.status) for a in db.absenties(tr1.id)} == {
            (anna.master_id, "aanwezig"), (tim.master_id, "blessure")}
        assert [a.status for a in db.absenties_van_atleet(anna.master_id)] == ["aanwezig", "afgemeld"]  # op datum
        andere = db.groep_opslaan(Groep("Andere groep"))
        assert db.absenties_van_atleet(anna.master_id, groep_id=andere.id) == []

        # Verwijzingen naar personen.db worden in Python gecontroleerd.
        _verwacht(OpslagFout, lambda: db.absentie_opslaan(Absentie(999, anna.master_id, "aanwezig")))
        _verwacht(OpslagFout, lambda: db.absentie_opslaan(Absentie(tr1.id, "0" * 32, "aanwezig")))
        _verwacht(OpslagFout, lambda: db.absenties_opslaan([   # alles-of-niets
            Absentie(tr2.id, tim.master_id, "afwezig"), Absentie(999, tim.master_id, "afwezig")]))
        assert len(db.absenties(tr2.id)) == 1

        # Training weg -> absentie in het andere bestand ook weg.
        db.training_verwijderen(tr1.id)
        assert db.training(tr1.id) is None
        assert db.absentie_db.execute("SELECT count(*) FROM absentie WHERE training_id = ?",
                                      (tr1.id,)).fetchone()[0] == 0


def test_notities():
    with opslag() as db:
        anna, tim, _, _ = _basis(db)
        lang = "Starthouding:\n" + "Te vroeg rechtop, armen te laag. " * 200   # lange tekst mag
        n1 = db.notitie_opslaan(Notitie(anna.master_id, date(2026, 10, 13), lang))
        n2 = db.notitie_opslaan(Notitie(anna.master_id, date(2026, 10, 15), "Sprong mooi af op de balk."))
        n3 = db.notitie_opslaan(Notitie(tim.master_id, date(2026, 10, 13), "Klaagde over kuit, rustig aan gedaan."))
        assert n1.id and n1.aangemaakt_op and n1.bijgewerkt_op is None

        assert db.notitie(n1.id).inhoud == lang.strip()
        assert [n.id for n in db.notities(anna.master_id)] == [n2.id, n1.id]                  # nieuwste eerst
        assert {n.atleet_id for n in db.notities(van=date(2026, 10, 13), tot=date(2026, 10, 13))} == {
            anna.master_id, tim.master_id}                                                     # alles van één dag
        assert [n.id for n in db.notities(zoek="BALK")] == [n2.id]                             # hoofdletterongevoelig
        assert db.notities(tim.master_id, zoek="balk") == []

        # Aanpassen: zelfde id, bijgewerkt_op gezet.
        n2.inhoud = "Sprong mooi af op de balk, wel te kort aanloop."
        db.notitie_opslaan(n2)
        terug = db.notitie(n2.id)
        assert terug.inhoud.endswith("aanloop.") and terug.bijgewerkt_op is not None
        assert len(db.notities(anna.master_id)) == 2

        # Pseudoniem, geen master_id; tekst niet leesbaar in het bestand.
        refs = {r[0] for r in db.notities_db.execute("SELECT atleet_ref FROM notitie")}
        assert pseudoniem(anna.master_id, "notities", TESTSLEUTEL) in refs and anna.master_id not in refs
        assert refs.isdisjoint({pseudoniem(anna.master_id, d, TESTSLEUTEL) for d in ("prestaties", "absentie")})

        _verwacht(OpslagFout, lambda: db.notitie_opslaan(Notitie("0" * 32, date(2026, 10, 1), "x")))
        _verwacht(OpslagFout, lambda: db.notitie_opslaan(Notitie(anna.master_id, date(2026, 10, 1), "x", id=999)))
        db.notitie_verwijderen(n3.id)
        assert db.notitie(n3.id) is None and db.notities(tim.master_id) == []


def test_oude_absentie_wordt_verplaatst():
    """Een personen.db van vóór absentie.db: de rijen verhuizen bij init_db, niets gaat verloren."""
    with tempfile.TemporaryDirectory() as tmp:
        map_ = Path(tmp)
        mid = "ab" * 16
        # Oude situatie nabootsen: alleen schema v1 van personen.db, met absentie erin.
        with contextlib.closing(verbind("personen", map_, TESTSLEUTEL)) as c:
            c.executescript((DB_DIR / "schema_personen.sql").read_text(encoding="utf-8"))
            c.execute("INSERT INTO atleet (master_id, voornaam, achternaam) VALUES (?, 'Anna', 'Voorbeeld')", (mid,))
            c.execute("INSERT INTO groep (naam) VALUES ('C')")
            c.execute("INSERT INTO training (groep_id, datum) VALUES (1, '2026-10-13')")
            c.execute("INSERT INTO training (groep_id, datum) VALUES (1, '2026-10-15')")
            c.execute("INSERT INTO absentie VALUES (1, ?, 'aanwezig', NULL)", (mid,))
            c.execute("INSERT INTO absentie VALUES (2, ?, 'blessure', 'knie')", (mid,))
            c.commit()
        uitvoer = io.StringIO()
        with contextlib.redirect_stdout(uitvoer):
            init_db(map_, hoofd=TESTSLEUTEL)
            init_db(map_, hoofd=TESTSLEUTEL)   # tweede keer: niets meer te doen
        assert uitvoer.getvalue().count("Absentie verplaatst") == 1
        with Opslag(map=map_, hoofd=TESTSLEUTEL) as db:
            assert [(a.training_id, a.status, a.reden) for a in db.absenties_van_atleet(mid)] == [
                (1, "aanwezig", None), (2, "blessure", "knie")]
            assert db.personen.execute(
                "SELECT count(*) FROM sqlite_master WHERE name LIKE 'absentie%'").fetchone()[0] == 0


def test_leerlijnen():
    with opslag() as db:
        anna, _, _, _ = _basis(db)
        lijn = db.leerlijn_opslaan(Leerlijn("Sprint", stappen=[
            LeerlijnStap(1, "Armactie"), LeerlijnStap(2, "Blokstart")]))
        terug = db.leerlijn(lijn.id)
        assert [s.naam for s in terug.stappen] == ["Armactie", "Blokstart"]
        db.voortgang_opslaan(LeerlijnVoortgang(anna.master_id, terug.stappen[0].id, date(2026, 9, 1)))
        behaald = {v.stap_id for v in db.voortgang(anna.master_id) if v.behaald}
        assert terug.volgende_stap(behaald).naam == "Blokstart"


def test_atleet_verwijderen_wist_alles():
    with opslag() as db:
        anna, tim, sprint, _ = _basis(db)
        db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 12.9, wind=0.5).gekoppeld(anna.master_id))
        db.prestatie_opslaan(Prestatie("100m", date(2026, 6, 1), 13.5, wind=0.5).gekoppeld(tim.master_id))
        t = db.test_opslaan(Test("30m vliegend", "s", True))
        db.testresultaat_opslaan(Testresultaat(anna.master_id, t.id, date(2026, 10, 1), 3.9))
        g = db.groep_opslaan(Groep("C", leden=[anna.master_id, tim.master_id]))
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["dinsdag"]))
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(tim.master_id, ["dinsdag"]))
        tr = db.training_opslaan(Training(g.id, date(2026, 10, 13)))
        db.absenties_opslaan([Absentie(tr.id, anna.master_id, "blessure"), Absentie(tr.id, tim.master_id, "aanwezig")])
        db.notitie_opslaan(Notitie(anna.master_id, date(2026, 10, 13), "Notitie over Anna"))
        db.notitie_opslaan(Notitie(tim.master_id, date(2026, 10, 13), "Notitie over Tim"))

        db.atleet_verwijderen(anna.master_id)
        assert db.atleet(anna.master_id) is None
        assert db.prestaties(anna.master_id) == []
        assert db.testresultaten(anna.master_id) == []
        assert db.trainingsschema(anna.master_id).dagen == []
        assert db.atleten_op_dag("dinsdag") == [tim.master_id]
        assert db.absentie_db.execute("SELECT count(*) FROM absentie").fetchone()[0] == 1   # alleen Tim
        assert db.notities(anna.master_id) == []
        assert [n.inhoud for n in db.notities()] == ["Notitie over Tim"]
        assert db.groep(g.id).leden == [tim.master_id]
        assert len(db.prestaties(tim.master_id)) == 1  # Tim blijft
