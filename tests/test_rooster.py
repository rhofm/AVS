"""Tests voor het rooster: geplande trainingsinhoud per week.

  * models/rooster.py: roosterweek op een datum (herhalen, één keer, einddatum);
  * Opslag: roosters, regels (lege tijd = vaste tijd), koppelingen;
  * groepen/rooster.py: inhoud naar trainingen kopiëren, losmaken bij aanpassen,
    terugzetten, wijzigingen doorvoeren, ontkoppelen, opruimen;
  * importeren: geplakte tabel (tab), CSV (; en ,), datums, fouten en waarschuwingen;
  * de pagina's.

Alleen nepgegevens en een testsleutel.
"""

from datetime import date, timedelta

from test_groep_landingspagina import VANDAAG, opslag

from db.queries import OpslagFout
from groepen import rooster as roosterbeheer
from groepen import trainingen as trainingsbeheer
from models import Absentie, Atleet, Groep, GroepRooster, Rooster, RoosterRegel, Training
from hulp import app_client

START = date(2026, 10, 19)            # maandag na VANDAAG (vr 16 okt): begin van roosterweek 1
DI1, ZA1, DI2, DI3 = START + timedelta(1), START + timedelta(5), START + timedelta(8), START + timedelta(15)


def _fout(f, *, soort=OpslagFout):
    try:
        f()
    except soort as e:
        return str(e)
    raise AssertionError("verwachtte een fout")


def _groep(db) -> Groep:
    """Groep die dinsdag 18:30 en zaterdag 09:00 + 10:30 traint."""
    g = db.groep_opslaan(Groep("U16 sprint", "2026-2027"))
    db.groep_trainingsdagen_opslaan(g.id, {"dinsdag": "18:30", "zaterdag": "09:00"})
    db.groep_extra_tijden_opslaan(g.id, {"zaterdag": ["10:30"]})
    return db.groep(g.id)


def _rooster(db) -> Rooster:
    r = db.rooster_opslaan(Rooster("Najaar", 2))
    for regel in (RoosterRegel(1, "dinsdag", onderwerp="Starts", kern_a="Startblok 6x 20m"),
                  RoosterRegel(1, "zaterdag", onderwerp="Duurloop"),
                  RoosterRegel(1, "zaterdag", "10:30", onderwerp="Extra: techniek"),
                  RoosterRegel(2, "dinsdag", onderwerp="Horden")):
        regel.rooster_id = r.id
        db.rooster_regel_opslaan(regel)
    return db.rooster(r.id)


def _op(db, g, d: date, tijd: str | None = None) -> Training:
    return next(t for t in db.trainingen(g.id, van=d, tot=d) if t.effectieve_starttijd(g) == (tijd or g.starttijd(
        ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"][d.weekday()])))


# ============================================================
# Model
# ============================================================
def test_roosterweek():
    k = GroepRooster(1, 1, START)
    assert k.week_op(START - timedelta(1), 3) is None
    assert [k.week_op(START + timedelta(weeks=w, days=6), 3) for w in range(5)] == [1, 2, 3, 1, 2]
    eenmalig = GroepRooster(1, 1, START, herhalen=False)
    assert eenmalig.week_op(START + timedelta(weeks=2), 3) == 3 and eenmalig.week_op(START + timedelta(weeks=3), 3) is None
    tot = GroepRooster(1, 1, START, einddatum=START + timedelta(10))
    assert tot.week_op(START + timedelta(10), 3) == 2 and tot.week_op(START + timedelta(11), 3) is None
    _fout(lambda: GroepRooster(1, 1, START, einddatum=START - timedelta(1)), soort=ValueError)

    r = RoosterRegel(2, "Dinsdag", "9.00", onderwerp="  Starts ", notities="\r\n")
    assert (r.dag, r.starttijd, r.onderwerp, r.notities, r.aantal_delen) == ("dinsdag", "09:00", "Starts", None, 0)
    assert RoosterRegel(1, "maandag").leeg
    for f in (lambda: RoosterRegel(0, "maandag"), lambda: RoosterRegel(1, "feestdag"),
              lambda: Rooster("", 4), lambda: Rooster("x", 61)):
        _fout(f, soort=ValueError)


# ============================================================
# Opslag
# ============================================================
def test_opslag():
    with opslag() as (db, _):
        g = _groep(db)
        r = _rooster(db)
        assert [(x.week, x.dag, x.starttijd, x.onderwerp) for x in r.regels] == [
            (1, "dinsdag", None, "Starts"), (1, "zaterdag", None, "Duurloop"),
            (1, "zaterdag", "10:30", "Extra: techniek"), (2, "dinsdag", None, "Horden")]
        oud = r.regels[0].id
        # Zelfde moment (ook met lege tijd) vervangt; leeg haalt weg.
        nieuw = db.rooster_regel_opslaan(RoosterRegel(1, "dinsdag", onderwerp="Snelheid", rooster_id=r.id))
        assert nieuw.id == oud and db.rooster_regel(oud).onderwerp == "Snelheid"
        assert db.rooster_regel_opslaan(RoosterRegel(2, "dinsdag", rooster_id=r.id)) is None
        assert len(db.rooster(r.id).regels) == 3
        assert "maar 2 weken" in _fout(lambda: db.rooster_regel_opslaan(RoosterRegel(3, "dinsdag", onderwerp="x", rooster_id=r.id)))
        _fout(lambda: db.rooster_regel_opslaan(RoosterRegel(1, "dinsdag", onderwerp="x")))

        # Vervangen: hetzelfde moment houdt zijn id (trainingen blijven gekoppeld).
        db.rooster_regels_vervangen(r.id, [RoosterRegel(1, "dinsdag", onderwerp="A"), RoosterRegel(2, "zaterdag", onderwerp="B"),
                                           RoosterRegel(2, "zaterdag", onderwerp="B2"), RoosterRegel(1, "zondag")])
        regels = db.rooster(r.id).regels
        assert [(x.week, x.dag, x.onderwerp) for x in regels] == [(1, "dinsdag", "A"), (2, "zaterdag", "B2")]
        assert regels[0].id == oud

        assert "week 2" in _fout(lambda: db.rooster_opslaan(Rooster("Najaar", 1, id=r.id)))
        db.rooster_opslaan(Rooster("Najaar kort", 3, id=r.id))
        assert [x.naam for x in db.roosters()] == ["Najaar kort"]

        db.groep_rooster_opslaan(GroepRooster(g.id, r.id, START))
        db.groep_rooster_opslaan(GroepRooster(g.id, r.id, START, herhalen=False))      # zelfde start: vervangen
        assert [(k.startdatum, k.herhalen) for k in db.groep_roosters(g.id)] == [(START, False)]
        assert db.groepen_met_rooster(r.id) == [g.id]
        assert "nog door een groep" in _fout(lambda: db.rooster_verwijderen(r.id))
        _fout(lambda: db.groep_rooster_opslaan(GroepRooster(9999, r.id, START)))
        _fout(lambda: db.groep_rooster_opslaan(GroepRooster(g.id, 9999, START)))
        db.groep_rooster_verwijderen(g.id, START)
        db.rooster_verwijderen(r.id)
        assert db.roosters() == []


# ============================================================
# Toepassen op trainingen
# ============================================================
def test_nieuwe_trainingen_krijgen_inhoud():
    with opslag() as (db, _):
        g = _groep(db)
        r = _rooster(db)
        db.groep_rooster_opslaan(GroepRooster(g.id, r.id, START))
        trainingsbeheer.trainingen_aanvullen(db, g, peildatum=VANDAAG)
        assert _op(db, g, DI1).onderwerp == "Starts" and _op(db, g, DI1).kern_a == "Startblok 6x 20m"
        assert _op(db, g, ZA1).onderwerp == "Duurloop"                         # regel zonder tijd = 09:00
        assert _op(db, g, ZA1, "10:30").onderwerp == "Extra: techniek"
        assert _op(db, g, DI2).onderwerp == "Horden"
        assert _op(db, g, DI3).onderwerp == "Starts"                           # herhaalt
        assert _op(db, g, START + timedelta(12)).onderwerp is None             # za week 2: niets gepland
        assert _op(db, g, DI1).rooster_regel_id is not None


def test_aanpassen_doorvoeren_en_terugzetten():
    with opslag() as (db, _):
        g = _groep(db)
        r = _rooster(db)
        db.groep_rooster_opslaan(GroepRooster(g.id, r.id, START))
        trainingsbeheer.trainingen_aanvullen(db, g, peildatum=VANDAAG)
        di1, di3 = _op(db, g, DI1), _op(db, g, DI3)

        # Opslaan zonder wijziging: blijft gekoppeld. Wel wijzigen: los van het rooster.
        trainingsbeheer.training_bewerken(db, di3.id, {**roosterbeheer.inhoud(di3)})
        assert db.training(di3.id).rooster_regel_id is not None
        trainingsbeheer.training_bewerken(db, di1.id, {**roosterbeheer.inhoud(di1), "onderwerp": "Starts (regen)"})
        assert db.training(di1.id).rooster_regel_id is None

        # Regel wijzigen: alleen gekoppelde toekomstige trainingen veranderen.
        regel, n = roosterbeheer.regel_opslaan(db, r.id, 1, "dinsdag", "", {"onderwerp": "Snelheid"}, peildatum=VANDAAG)
        assert n == 1                                                          # alleen di week 3 (week 1 is los)
        assert db.training(di3.id).onderwerp == "Snelheid" and db.training(di3.id).kern_a is None
        assert db.training(di1.id).onderwerp == "Starts (regen)"

        status = roosterbeheer.rooster_status(db, g, db.training(di1.id))
        assert status.afwijkend and status.regel.onderwerp == "Snelheid"
        assert roosterbeheer.rooster_status(db, g, db.training(di3.id)).gekoppeld
        roosterbeheer.terugzetten(db, di1.id)
        assert db.training(di1.id).onderwerp == "Snelheid" and db.training(di1.id).rooster_regel_id == regel.id
        assert "plant niets" in _fout(lambda: roosterbeheer.terugzetten(db, _op(db, g, START + timedelta(12)).id))

        # Regel leegmaken: gekoppelde trainingen worden weer leeg.
        roosterbeheer.regel_opslaan(db, r.id, 1, "dinsdag", "", {}, peildatum=VANDAAG)
        assert db.training(di3.id).onderwerp is None and db.training(di3.id).rooster_regel_id is None


def test_handwerk_verleden_en_varianten_blijven():
    with opslag() as (db, _):
        g = _groep(db)
        r = _rooster(db)
        trainingsbeheer.trainingen_aanvullen(db, g, peildatum=VANDAAG)
        handwerk = _op(db, g, DI1)
        handwerk.onderwerp = "Clubtraining"
        db.training_opslaan(handwerk)
        verleden = db.training_opslaan(Training(g.id, START - timedelta(weeks=1, days=-1)))   # di vorige week
        anna = db.atleet_opslaan(Atleet("Anna", "Test")).master_id
        g.voeg_toe(anna)
        db.groep_opslaan(g)
        variant = db.training_opslaan(Training(g.id, DI2, "Revalidatie", hoofdtraining_id=_op(db, g, DI2).id,
                                               atleten=[anna]))
        k, n = roosterbeheer.koppelen(db, g.id, {"rooster": str(r.id), "start": START.isoformat(), "herhalen": "1"},
                                      peildatum=VANDAAG)
        assert db.training(handwerk.id).onderwerp == "Clubtraining"             # met de hand: niet overschreven
        assert db.training(verleden.id).onderwerp is None                       # verleden: niet aangeraakt
        assert _op(db, g, ZA1).onderwerp == "Duurloop" and n > 0
        assert _op(db, g, DI2).onderwerp == "Horden"                            # gewone training: uit het rooster
        assert db.training(variant.id).onderwerp == "Revalidatie"               # variant: niet aangeraakt


def test_herhalen_uit_en_ontkoppelen():
    with opslag() as (db, _):
        g = _groep(db)
        r = _rooster(db)
        trainingsbeheer.trainingen_aanvullen(db, g, peildatum=VANDAAG)
        roosterbeheer.koppelen(db, g.id, {"rooster": str(r.id), "start": START.isoformat(), "herhalen": "1"},
                               peildatum=VANDAAG)
        assert _op(db, g, DI3).onderwerp == "Starts"
        # Zelfde start, nu één keer: week 3 valt buiten het rooster en wordt weer leeg.
        roosterbeheer.koppelen(db, g.id, {"rooster": str(r.id), "start": (START + timedelta(2)).isoformat()},
                               peildatum=VANDAAG)                               # woensdag -> maandag
        assert db.groep_roosters(g.id)[0].startdatum == START and not db.groep_roosters(g.id)[0].herhalen
        assert _op(db, g, DI3).onderwerp is None and _op(db, g, DI2).onderwerp == "Horden"

        handwerk = _op(db, g, DI2)
        trainingsbeheer.training_bewerken(db, handwerk.id, {"onderwerp": "Horden + starts"})
        n = roosterbeheer.ontkoppelen(db, g.id, START.isoformat(), peildatum=VANDAAG)
        assert n >= 2 and _op(db, g, DI1).onderwerp is None
        assert db.training(handwerk.id).onderwerp == "Horden + starts"          # handwerk blijft
        assert db.groep_roosters(g.id) == []


def test_opruimen_telt_rooster_inhoud_als_leeg():
    with opslag() as (db, _):
        g = _groep(db)
        r = _rooster(db)
        db.groep_rooster_opslaan(GroepRooster(g.id, r.id, START))
        trainingsbeheer.trainingen_aanvullen(db, g, peildatum=VANDAAG)
        za = _op(db, g, ZA1)
        db.groep_trainingsdagen_opslaan(g.id, {"dinsdag": "18:30"})            # zaterdag vervalt
        weg = trainingsbeheer.trainingen_opruimen(db, db.groep(g.id), peildatum=VANDAAG)
        assert za.id in {t.id for t in weg}                                     # alleen rooster-inhoud: mag weg
        di = _op(db, g, DI1)
        db.absenties_opslaan([Absentie(di.id, db.atleet_opslaan(Atleet("Anna", "Test")).master_id, "aanwezig")])
        db.groep_trainingsdagen_opslaan(g.id, {"donderdag": "18:30"})
        assert di.id not in {t.id for t in trainingsbeheer.trainingen_opruimen(db, db.groep(g.id), peildatum=VANDAAG)}


def test_roosterpagina():
    with opslag() as (db, _):
        g = _groep(db)
        r = _rooster(db)
        leeg = roosterbeheer.roosterpagina(db, g.id, peildatum=VANDAAG)
        assert leeg.rooster is None and leeg.koppelingen == [] and leeg.standaard_start == START
        db.groep_rooster_opslaan(GroepRooster(g.id, r.id, START - timedelta(weeks=1)))
        anders = db.rooster_opslaan(Rooster("Winter", 1))
        db.groep_rooster_opslaan(GroepRooster(g.id, anders.id, START + timedelta(weeks=8), herhalen=False))
        p = roosterbeheer.roosterpagina(db, g.id, peildatum=VANDAAG)
        assert p.rooster.id == r.id and p.week_nu == 1
        assert [(m.dag, m.tijd) for m in p.momenten] == [("dinsdag", "18:30"), ("zaterdag", "09:00"), ("zaterdag", "10:30")]
        assert [c.regel.onderwerp if c.regel else None for c in p.weken[0]] == ["Starts", "Duurloop", "Extra: techniek"]
        assert [c.tijd_veld for c in p.weken[1]] == ["", "", "10:30"] and p.weken[0][0].nu
        assert [(k.nu, k.tot) for k in p.koppelingen] == [(True, START + timedelta(weeks=8, days=-1)),
                                                          (False, START + timedelta(weeks=9, days=-1))]
        # Regel op een dag zonder training: extra kolom.
        db.rooster_regel_opslaan(RoosterRegel(2, "woensdag", onderwerp="Krachttraining", rooster_id=r.id))
        p = roosterbeheer.roosterpagina(db, g.id, peildatum=VANDAAG)
        assert ("woensdag", None, False) in [(m.dag, m.tijd, m.vast) for m in p.momenten]
        assert roosterbeheer.roosterpagina(db, 9999) is None


# ============================================================
# Importeren
# ============================================================
TAB = "week\tdag\tonderwerp\tKern A\twarming-up\n1\tdi\tStarts\tStartblok\tInlopen\n1\tZaterdag\tDuurloop\t\t\n\n2\tdi\tHorden\t\t\n"


def test_lees_tabel_geplakt():
    with opslag() as (db, _):
        g = _groep(db)
        res = roosterbeheer.lees_tabel(TAB, groep=g)
        assert res.bruikbaar and not res.met_datum and res.aantal_weken == 2
        assert [(r.week, r.dag, r.onderwerp, r.kern_a, r.warming_up) for r in res.goed] == [
            (1, "dinsdag", "Starts", "Startblok", "Inlopen"), (1, "zaterdag", "Duurloop", None, None),
            (2, "dinsdag", "Horden", None, None)]


def test_lees_tabel_csv_en_datums():
    csv_puntkomma = 'Week;Dag;Tijd;Onderwerp;Notities\r\n1;dinsdag;;Starts;"Spikes mee;\nen pionnen"\r\n1;zaterdag;10:30;Techniek;\r\n'
    res = roosterbeheer.lees_tabel(csv_puntkomma)
    assert res.bruikbaar and res.goed[0].notities == "Spikes mee;\nen pionnen" and res.goed[1].starttijd == "10:30"
    res = roosterbeheer.lees_tabel("week,dag,onderwerp\n1,ma,A\n3,wo,B\n")
    assert res.bruikbaar and res.aantal_weken == 3

    datums = "datum;onderwerp\n21-10-2026;Starts\n2026-11-03;Horden\n"
    res = roosterbeheer.lees_tabel(datums)
    assert res.met_datum and res.start == START                                 # week van de vroegste datum
    assert [(r.week, r.dag) for r in res.goed] == [(1, "woensdag"), (3, "dinsdag")]
    res = roosterbeheer.lees_tabel(datums, start=START - timedelta(weeks=1, days=-3))   # donderdag ervoor
    assert res.start == START - timedelta(weeks=1) and res.goed[0].week == 2
    res = roosterbeheer.lees_tabel(datums, start=START + timedelta(weeks=1))
    assert not res.bruikbaar and "voor de start" in res.fouten[0].fout


def test_lees_tabel_fouten_en_waarschuwingen():
    with opslag() as (db, _):
        g = _groep(db)
        for tekst, deel in (("", "kopregel"), ("onderwerp;notities\nA;B\n", "kolom 'datum'"),
                            ("week;dag;tijd\n1;di;18:30\n", "Geen kolom met inhoud")):
            assert deel in roosterbeheer.lees_tabel(tekst).fout, tekst
        res = roosterbeheer.lees_tabel(
            "week;dag;tijd;onderwerp\nx;di;;A\n1;feestdag;;B\n0;di;;C\n1;di;25:00;D\n1;wo;;E\n1;di;19:00;F\n"
            "2;di;;G\n2;di;;H\n3;di;;\n", groep=g)
        assert [f.rij for f in res.fouten] == [2, 3, 4, 5] and not res.bruikbaar
        assert "geen weeknummer" in res.fouten[0].fout and "geen dag" in res.fouten[1].fout
        let_op = {i.rij: i.let_op for i in res.let_op}
        assert "geen trainingsdag" in let_op[6] and "niet om 19:00" in let_op[7] and "Dubbel met regel 9" in let_op[8]
        assert 10 not in {i.rij for i in res.regels}                            # lege regel overgeslagen
        assert "maximaal 120" in roosterbeheer.lees_tabel("week;dag;onderwerp\n1;di;" + "x" * 121).fouten[0].fout
        assert roosterbeheer.decodeer("week;dag;onderwerp\n1;di;Caf\xe9\n".encode("cp1252")).endswith("Café\n")
        assert roosterbeheer.decodeer("﻿week".encode("utf-8")) == "week"


def test_importeren():
    with opslag() as (db, _):
        g = _groep(db)
        trainingsbeheer.trainingen_aanvullen(db, g, peildatum=VANDAAG)
        form = {"naam": "Geïmporteerd", "start": (START + timedelta(3)).isoformat(), "herhalen": "1"}
        r, k, n = roosterbeheer.importeren(db, g.id, form, TAB, peildatum=VANDAAG)
        assert (r.naam, r.aantal_weken, len(r.regels), k.startdatum, k.herhalen) == ("Geïmporteerd", 2, 3, START, True)
        assert n > 0 and _op(db, g, DI1).onderwerp == "Starts" and _op(db, g, DI2).onderwerp == "Horden"
        assert "Kies vanaf" in _fout(lambda: roosterbeheer.importeren(db, g.id, {"naam": "x"}, TAB))
        assert "klopt niet" in _fout(lambda: roosterbeheer.importeren(db, g.id, form, "week;dag;onderwerp\n1;x;A\n"))
        assert "naam" in _fout(lambda: roosterbeheer.importeren(db, g.id, {**form, "naam": " "}, TAB))
        _fout(lambda: roosterbeheer.importeren(db, 9999, form, TAB))


# ============================================================
# Pagina's
# ============================================================
def test_routes():
    with opslag() as (db, tmp):
        g = _groep(db)
        c = app_client(tmp)
        assert f'href="/groep/{g.id}/rooster"' in c.get(f"/groep/{g.id}").get_data(as_text=True)
        assert f'href="/groep/{g.id}/rooster"' in c.get(f"/groep/{g.id}/trainingen").get_data(as_text=True)
        html = c.get(f"/groep/{g.id}/rooster").get_data(as_text=True)
        assert "volgt nog geen rooster" in html and 'value="nieuw" selected' in html

        r = c.post(f"/groep/{g.id}/rooster/koppelen", data={"rooster": "nieuw", "naam": "Najaar", "weken": "2",
                                                              "start": date.today().isoformat(), "herhalen": "1"})
        assert r.status_code == 302
        rid = db.roosters()[0].id
        html = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "Rooster gekoppeld vanaf" in html and "Najaar" in html and 'class="roostercel roostercel--leeg"' in html
        assert c.post(f"/groep/{g.id}/rooster/koppelen", data={"rooster": "nieuw", "naam": "", "weken": "2",
                                                                 "start": "2026-10-19"}).status_code == 400

        pad = f"/rooster/{rid}/regel?week=1&dag=dinsdag&tijd=&groep={g.id}"
        assert "Week 1, dinsdag" in c.get(pad).get_data(as_text=True)
        r = c.post(pad, data={"onderwerp": "Starts", "kern_a": "Startblok"})
        assert r.status_code == 302 and "Opgeslagen: week 1, dinsdag." in c.get(r.headers["Location"]).get_data(as_text=True)
        assert db.rooster(rid).regels[0].onderwerp == "Starts"
        assert c.post(pad, data={"onderwerp": "x" * 121}).status_code == 400
        assert c.get(f"/rooster/{rid}/regel?week=9&dag=dinsdag&groep={g.id}").status_code == 404
        assert c.get(f"/rooster/{rid}/regel?week=1&dag=dinsdag").status_code == 404      # zonder groep
        assert c.get(f"/rooster/9999/regel?week=1&dag=dinsdag&groep={g.id}").status_code == 404

        r = c.post(f"/rooster/{rid}/wijzigen", data={"groep": str(g.id), "naam": "Najaar 2026", "weken": "3"})
        assert r.status_code == 302 and db.rooster(rid).aantal_weken == 3

        # Importeren: eerst controleren, dan opslaan.
        pad = f"/groep/{g.id}/rooster/importeren"
        assert "Voorbeeld-CSV" in c.get(pad).get_data(as_text=True)
        r = c.post(pad, data={"naam": "Uit Excel", "start": "2026-10-19", "herhalen": "1", "tabel": TAB, "stap": "controleren"})
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "3 regels gelezen, 2 weken" in html and 'value="opslaan"' in html
        assert len(db.roosters()) == 1                                          # nog niets opgeslagen
        r = c.post(pad, data={"naam": "Uit Excel", "start": "2026-10-19", "herhalen": "1", "tabel": TAB, "stap": "opslaan"})
        assert r.status_code == 302 and len(db.roosters()) == 2
        r = c.post(pad, data={"naam": "x", "tabel": "week;dag;onderwerp\n1;x;A\n", "stap": "controleren"})
        assert "klopt niet" in r.get_data(as_text=True) and 'value="opslaan"' not in r.get_data(as_text=True)
        assert c.get("/groep/9999/rooster").status_code == 404

        csv = c.get("/rooster/voorbeeld.csv")
        assert csv.mimetype == "text/csv" and csv.get_data(as_text=True).startswith("﻿week;dag;tijd")

        # Training uit het rooster, aanpassen, terugzetten.
        di = next(t for t in db.trainingen(g.id, van=date(2026, 10, 20)) if t.datum.weekday() == 1)
        assert "uit rooster" in c.get(f"/training/{di.id}").get_data(as_text=True)
        trainingsbeheer.training_bewerken(db, di.id, {"onderwerp": "Anders"})
        html = c.get(f"/training/{di.id}").get_data(as_text=True)
        assert "afwijkend van rooster" in html and "Terugzetten naar rooster" in html
        r = c.post(f"/training/{di.id}/rooster")
        assert r.status_code == 302 and db.training(di.id).rooster_regel_id is not None
        assert "weer zoals in het rooster" in c.get(r.headers["Location"]).get_data(as_text=True)
        assert c.post("/training/9999/rooster").status_code == 404

        r = c.post(f"/groep/{g.id}/rooster/ontkoppelen", data={"start": "2026-10-19"})
        assert r.status_code == 302 and "Koppeling weggehaald" in c.get(r.headers["Location"]).get_data(as_text=True)
