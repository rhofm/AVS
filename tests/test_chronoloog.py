"""Tests voor het tijdschema (chronoloog) van wedstrijden: prestaties-migratie 003,
models/programma.py, Opslag.programma_* en wedstrijden/chronoloog.py.

Alleen nepgegevens en een vaste testsleutel.
"""

import contextlib
import io
import tempfile
from datetime import date
from pathlib import Path

from db.init_db import huidige_versie, init_db, verbind
from db.queries import Opslag, OpslagFout
from models import Atleet, Inschrijving, Onderdeel, ProgrammaOnderdeel, Wedstrijd, lees_categorie
from wedstrijden import chronoloog
from hulp import TESTSLEUTEL, opslag, verwacht as _verwacht

ZA = date(2027, 3, 13)
ZO = date(2027, 3, 14)


def P(w, dag, tijd, onderdeel=None, tekst=None, **kw):
    return ProgrammaOnderdeel(w.id, dag, tijd, onderdeel.id if onderdeel else None, tekst, **kw)


def _basis(db):
    anna = db.atleet_opslaan(Atleet("Anna", "Aalbers", geslacht="V", geboortedatum="2012-05-01"))   # U16 in 2027
    bas = db.atleet_opslaan(Atleet("Bas", "Bakker", geslacht="M", geboortedatum="2014-02-01"))      # U14
    cor = db.atleet_opslaan(Atleet("Cor", "Claassen", geslacht="M"))                                # geen geboortedatum
    o = {n: db.onderdeel_opslaan(Onderdeel(n, e, lager, c)) for n, e, lager, c in (
        ("60m", "tijd", True, "sprint"), ("60m horden", "tijd", True, "horden"),
        ("Verspringen", "afstand", False, "springen"), ("Kogelstoten", "afstand", False, "werpen"))}
    w = db.wedstrijd_opslaan(Wedstrijd("Indoor Apeldoorn", ZA, "Omnisport", indoor=True))
    return anna, bas, cor, o, w


def test_model():
    w = Wedstrijd("X", ZA)
    w.id = 1
    p = ProgrammaOnderdeel(1, ZA, "9:30", None, "  60m   horden ", "Meisjes U16", "serie", groep=2, duur=25)
    assert (p.starttijd, p.onderdeel_tekst, p.eindtijd) == ("09:30", "60m horden", "09:55")
    assert p.omschrijving == "60m horden Meisjes U16, serie, groep 2"
    q = ProgrammaOnderdeel(1, ZA, "09:50", None, "Ver", duur=60)
    assert p.overlapt(q) and q.overlapt(p)
    assert not ProgrammaOnderdeel(1, ZA, "10:00", None, "Ver").overlapt(p)          # na 09:55
    assert ProgrammaOnderdeel(1, ZA, "09:30", None, "Kogel").overlapt(
        ProgrammaOnderdeel(1, ZA, "09:30", None, "Hoog"))                           # zonder duur: zelfde tijd
    for fout in (dict(starttijd=""), dict(starttijd="25:00"), dict(groep=0), dict(duur=0), dict(duur=721),
                 dict(onderdeel_tekst=None)):
        kw = dict(wedstrijd_id=1, datum=ZA, starttijd="10:00", onderdeel_tekst="Ver") | fout
        _verwacht(ValueError, lambda k=kw: ProgrammaOnderdeel(**k))
    assert lees_categorie("Meisjes U16") == ("U16", "V") and lees_categorie("JU14") == ("U14", "M")
    assert lees_categorie("Vrouwen") == ("Senior", "V") and lees_categorie("JPA") == (None, None)


def test_opslaan_lezen_vervangen():
    with opslag() as db:
        _, _, _, o, w = _basis(db)
        r1 = db.programma_opslaan(P(w, ZA, "10:30", o["60m horden"], categorie="Meisjes U16",
                                    ronde="serie", groep=2, duur=20, opmerking="oproep 15 min eerder"))
        r2 = db.programma_opslaan(P(w, ZA, "10:30", o["60m horden"], categorie="Meisjes U16", ronde="serie", groep=1))
        r3 = db.programma_opslaan(P(w, ZA, "09:00", None, "Opening"))
        r4 = db.programma_opslaan(P(w, ZO, "11:00", o["Verspringen"], categorie="JU14", duur=90))
        assert r1.onderdeel_tekst == "60m horden"                                   # naam overgenomen
        terug = db.programma(w.id)
        assert [(x.datum, x.starttijd, x.groep) for x in terug] == [
            (ZA, "09:00", None), (ZA, "10:30", 1), (ZA, "10:30", 2), (ZO, "11:00", None)]
        r = db.programma_regel(r1.id)
        assert (r.groep, r.duur, r.eindtijd, r.ronde, r.opmerking) == (2, 20, "10:50", "serie", "oproep 15 min eerder")
        assert chronoloog.dagen(terug) == [ZA, ZO]

        r4.starttijd = "11:15"
        db.programma_opslaan(r4)
        assert db.programma_regel(r4.id).starttijd == "11:15"
        db.programma_verwijderen(r3.id)
        assert len(db.programma(w.id)) == 3

        # Fouten: onbekende wedstrijd/onderdeel/regel. De database weigert ook rare waarden.
        _verwacht(OpslagFout, lambda: db.programma_opslaan(ProgrammaOnderdeel(999, ZA, "10:00", None, "X")))
        _verwacht(OpslagFout, lambda: db.programma_opslaan(ProgrammaOnderdeel(w.id, ZA, "10:00", 999)))
        _verwacht(OpslagFout, lambda: db.programma_opslaan(ProgrammaOnderdeel(w.id, ZA, "10:00", None, "X", id=999)))
        for sql in ("UPDATE wedstrijd_programma SET starttijd = '9:00'", "UPDATE wedstrijd_programma SET groep = 0",
                    "UPDATE wedstrijd_programma SET duur = 0",
                    "UPDATE wedstrijd_programma SET onderdeel_id = NULL, onderdeel_tekst = ' '"):
            _verwacht(Exception, lambda s=sql: db.prestaties_db.execute(s))

        # Vervangen: alles of niets.
        _verwacht(OpslagFout, lambda: db.programma_vervangen(w.id, [P(w, ZA, "12:00", None, "Nieuw"),
                                                                    ProgrammaOnderdeel(w.id, ZA, "13:00", 999)]))
        assert len(db.programma(w.id)) == 3
        assert db.programma_vervangen(w.id, [P(w, ZA, "12:00", None, "Nieuw"), P(w, ZA, "13:00", o["60m"])]) == 2
        assert [x.naam for x in db.programma(w.id)] == ["Nieuw", "60m"]

        # Wedstrijd weg (zonder uitslagen) -> tijdschema weg.
        db.wedstrijd_verwijderen(w.id)
        assert db.prestaties_db.execute("SELECT count(*) FROM wedstrijd_programma").fetchone()[0] == 0


def test_persoonlijk_schema_en_overzicht():
    with opslag() as db:
        anna, bas, cor, o, w = _basis(db)
        for a, onderdelen in ((anna, ["60m horden", "Verspringen"]), (bas, ["60m", "Verspringen"]), (cor, ["60m"])):
            for n in onderdelen:
                db.inschrijving_opslaan(Inschrijving(a.master_id, w.id, o[n].id))
        regels = [
            P(w, ZA, "10:30", o["60m horden"], categorie="Meisjes U16", ronde="serie", groep=1, duur=15),
            P(w, ZA, "10:45", o["60m horden"], categorie="Meisjes U16", ronde="serie", groep=2, duur=15),
            P(w, ZA, "10:30", o["60m horden"], categorie="Jongens U16", ronde="serie", duur=15),
            P(w, ZA, "12:00", o["Verspringen"], categorie="MU16", duur=60),
            P(w, ZA, "12:00", o["Verspringen"], categorie="JU14", duur=60),
            P(w, ZA, "11:00", o["60m"], categorie="JU14", ronde="serie", duur=20),
            P(w, ZA, "11:30", o["60m"], categorie="JPA"),                                # onleesbaar
            P(w, ZA, "09:00", None, "Opening"),                                         # geen onderdeel
        ]
        db.programma_vervangen(w.id, regels)

        anna_s = chronoloog.persoonlijk_schema(db, w.id, anna.master_id)
        assert [(s.regel.starttijd, s.regel.naam, s.regel.groep) for s in anna_s] == [
            ("10:30", "60m horden", 1), ("10:45", "60m horden", 2), ("12:00", "Verspringen", None)]
        assert all(s.zeker for s in anna_s) and anna_s[0].andere_groep_mogelijk and not anna_s[2].andere_groep_mogelijk

        bas_s = chronoloog.persoonlijk_schema(db, w.id, bas.master_id)
        assert [(s.regel.starttijd, s.regel.categorie, s.zeker) for s in bas_s] == [
            ("11:00", "JU14", True), ("11:30", "JPA", False), ("12:00", "JU14", True)]
        # Cor: geen geboortedatum -> leeftijd onbekend: wel op de lijst, niet zeker.
        assert [(s.regel.starttijd, s.zeker) for s in chronoloog.persoonlijk_schema(db, w.id, cor.master_id)] == [
            ("11:00", False), ("11:30", False)]

        ov = {(x.regel.starttijd, x.regel.categorie): x for x in chronoloog.overzicht(db, w.id)}
        assert [a.voornaam for a in ov[("12:00", "MU16")].atleten] == ["Anna"]
        assert [a.voornaam for a in ov[("11:30", "JPA")].misschien] == ["Bas", "Cor"]
        assert ov[("09:00", None)].atleten == [] and ov[("10:30", "Jongens U16")].atleten == []

        # Ingeschreven zonder onderdeel: leeg schema.
        dirk = db.atleet_opslaan(Atleet("Dirk", "Dekker"))
        db.inschrijving_opslaan(Inschrijving(dirk.master_id, w.id, None))
        assert chronoloog.persoonlijk_schema(db, w.id, dirk.master_id) == []
        _verwacht(OpslagFout, lambda: chronoloog.persoonlijk_schema(db, 999, anna.master_id))


def test_botsingen():
    with opslag() as db:
        anna, bas, _, o, w = _basis(db)
        for a, onderdelen in ((anna, ["60m horden", "Verspringen", "Kogelstoten"]), (bas, ["60m", "Verspringen"])):
            for n in onderdelen:
                db.inschrijving_opslaan(Inschrijving(a.master_id, w.id, o[n].id))
        db.programma_vervangen(w.id, [
            P(w, ZA, "10:30", o["60m horden"], categorie="MU16", groep=1, duur=15),
            P(w, ZA, "10:45", o["60m horden"], categorie="MU16", groep=2, duur=15),   # alternatief, geen botsing
            P(w, ZA, "10:50", o["Verspringen"], categorie="MU16", duur=60),           # overlapt groep 2
            P(w, ZA, "12:00", o["Kogelstoten"], categorie="MU16", duur=45),           # 10 min na verspringen
            P(w, ZA, "11:00", o["60m"], categorie="JU14", duur=20),
            P(w, ZA, "11:30", o["Verspringen"], categorie="JU14"),                    # 10 min na 60m
        ])
        b = chronoloog.botsingen(db, w.id)
        assert [(x.atleet.voornaam, x.eerste.starttijd, x.tweede.starttijd, x.pauze) for x in b] == [
            ("Anna", "10:45", "10:50", None)]
        assert "lopen tegelijk" in b[0].tekst
        krap = chronoloog.botsingen(db, w.id, min_pauze=15)
        assert [(x.atleet.voornaam, x.eerste.starttijd, x.tweede.starttijd, x.pauze) for x in krap] == [
            ("Anna", "10:30", "10:50", 5),          # in groep 1 heeft Anna maar 5 min tot verspringen
            ("Anna", "10:45", "10:50", None), ("Anna", "10:50", "12:00", 10), ("Bas", "11:00", "11:30", 10)]
        assert "maar 5 min ertussen" in krap[0].tekst


def test_migratie_op_bestaande_database():
    """prestaties.db van vóór migratie 003 krijgt de tabel erbij; bestaande wedstrijden blijven."""
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        # closing(): `with verbind(...)` sluit de verbinding niet; op Windows kan de
        # tijdelijke map dan niet weg (WinError 32).
        with contextlib.closing(verbind("prestaties", Path(tmp), TESTSLEUTEL)) as c:
            c.execute("DROP TABLE wedstrijd_programma")
            c.execute("DROP TABLE doel_regel")                  # 004 (doelen) kwam later
            c.execute("DROP TABLE doel")
            c.execute("DELETE FROM schema_version WHERE versie >= 3")
            c.execute("INSERT INTO wedstrijd (naam, datum) VALUES ('Oud', '2026-09-01')")
            c.commit()
            assert huidige_versie(c) == 2
        with contextlib.redirect_stdout(io.StringIO()):
            init_db(Path(tmp), hoofd=TESTSLEUTEL)
        with Opslag(map=Path(tmp), hoofd=TESTSLEUTEL) as db:
            assert huidige_versie(db.prestaties_db) == 4      # 003 tijdschema + 004 doelen
            w = db.wedstrijden()[0]
            db.programma_opslaan(ProgrammaOnderdeel(w.id, w.datum, "10:00", None, "Verspringen", groep=1, duur=45))
            assert db.programma(w.id)[0].eindtijd == "10:45"
