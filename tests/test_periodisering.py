"""Tests voor de periodisering van een groep: megacyclus (fasen) en mesocycli.

  * models/periodisering.py: welke fase en mesoweek op een datum, randen, herhalen;
  * Opslag: opslaan en lezen (vervangt alles), fouten;
  * groepen/periodeplan.py: formulier lezen, start op het begin van de week,
    jaaroverzicht, kopiëren naar andere groepen;
  * de pagina's /groep/<id>/periodisering en .../kopieren.

Alleen nepgegevens en een testsleutel.
"""

from datetime import date, timedelta

from test_groep_landingspagina import MAANDAG, VANDAAG, opslag, voorbeeldgroep

import instellingen
from db.queries import OpslagFout
from groepen import periodeplan
from groepen import trainingen as trainingsbeheer
from models import Fase, Groep, Mesocyclus, Periode, Periodisering
from hulp import app_client


def _fout(f, *, soort=OpslagFout):
    try:
        f()
    except soort as e:
        return str(e)
    raise AssertionError("verwachtte een fout")


# ============================================================
# Model
# ============================================================
SEIZOEN = [Fase(date(2026, 10, 5), "V1"), Fase(date(2026, 12, 7), "WP"), Fase(date(2027, 1, 4), "V1"),
           Fase(date(2027, 3, 1), "V2"), Fase(date(2027, 5, 3), "WP"), Fase(date(2027, 8, 2), "Rust"),
           Fase(date(2027, 9, 6), "Geen")]


def test_fase_op_datum():
    p = Periodisering(list(reversed(SEIZOEN)))                         # volgorde maakt niet uit
    assert p.fase_op(date(2026, 10, 4)) is None                       # vóór de eerste fase
    assert p.fase_op(date(2026, 10, 5)).fase == "V1"                  # op de startdatum
    assert p.fase_op(date(2026, 12, 6)).fase == "V1"                  # dag ervoor: nog de vorige
    assert p.fase_op(date(2026, 12, 7)).fase == "WP"
    assert p.fase_op(date(2027, 2, 1)).fase == "V1"                   # V1 voor de tweede keer
    assert p.fase_op(date(2027, 9, 5)).naam == "Overgang / rust"
    assert p.fase_op(date(2027, 9, 6)) is None                        # 'Geen' stopt de periodisering
    assert Periodisering([Fase(date(2026, 1, 1), "WP")]).fase_op(date(2030, 1, 1)).fase == "WP"   # loopt door
    _fout(lambda: Fase(date(2026, 1, 1), "V3"), soort=ValueError)


def test_fase_blokken():
    p = Periodisering(SEIZOEN)
    blokken = p.fase_blokken(date(2026, 11, 1), date(2027, 1, 31))
    assert [(f.fase, b, e) for f, b, e in blokken] == [
        ("V1", date(2026, 11, 1), date(2026, 12, 6)),                 # afgekapt op het begin
        ("WP", date(2026, 12, 7), date(2027, 1, 3)),
        ("V1", date(2027, 1, 4), date(2027, 1, 31))]                  # afgekapt op het eind
    assert [f.fase for f, _, _ in p.fase_blokken(date(2027, 8, 1), date(2027, 12, 31))] == ["WP", "Rust"]   # geen 'Geen'
    assert Periodisering().fase_blokken(date(2026, 1, 1), date(2026, 12, 31)) == []


def test_mesocyclus():
    m = Mesocyclus(date(2026, 10, 5), 4, ["Opbouw", " Opbouw ", "Piek"])     # vierde naam ontbreekt
    assert m.weeknamen == ["Opbouw", "Opbouw", "Piek", ""]
    assert m.week_op(date(2026, 10, 4)) is None
    w = m.week_op(date(2026, 10, 11))                                  # zondag: nog week 1
    assert (w.nummer, w.aantal, w.titel, w.begin) == (1, 4, "Opbouw", date(2026, 10, 5))
    assert m.week_op(date(2026, 10, 19)).titel == "Piek"
    assert m.week_op(date(2026, 10, 26)).titel == "Week 4"             # geen eigen naam
    w = m.week_op(date(2026, 11, 2))                                   # herhaalt: weer week 1
    assert (w.nummer, w.begin) == (1, date(2026, 11, 2))
    assert Mesocyclus(date(2026, 1, 5), 2, ["a", "b", "c"]).weeknamen == ["a", "b"]   # te veel namen vervallen
    for weken in (0, 13):
        _fout(lambda: Mesocyclus(date(2026, 1, 5), weken), soort=ValueError)


def test_periodisering_samen():
    cycli = [Mesocyclus(date(2026, 10, 5), 4, ["Opbouw", "Opbouw", "Piek", "Herstel"]),
             Mesocyclus(date(2027, 1, 4), 3, ["Zwaar", "Zwaar", "Licht"])]
    p = Periodisering(SEIZOEN, cycli)
    assert p.mesoweek_op(date(2026, 12, 21)).nummer == 4               # 11 weken na de start: week 4
    assert p.mesoweek_op(date(2026, 12, 28)).nummer == 1               # 12 weken: weer week 1
    assert p.mesoweek_op(date(2027, 1, 4)).titel == "Zwaar"            # nieuwe mesocyclus neemt het over
    assert p.mesoweek_op(date(2027, 1, 18)).titel == "Licht"
    assert p.mesoweek_op(date(2027, 1, 25)).nummer == 1

    op = p.op(date(2026, 10, 19))
    assert op.kort == "V1 · wk 3 Piek"
    assert op.lang == "Algemene voorbereiding (V1) · week 3 van 4: Piek"
    assert Periode(week=Mesocyclus(date(2026, 1, 5), 2).week_op(date(2026, 1, 5))).kort == "wk 1"
    assert Periode(fase=Fase(date(2026, 1, 1), "WP")).lang == "Wedstrijdperiode (WP)"
    assert not Periode() and not p.op(date(2020, 1, 1)) and Periodisering().leeg


# ============================================================
# Opslag
# ============================================================
def test_opslag():
    with opslag() as (db, _):
        g = db.groep_opslaan(Groep("U14", "2026-2027"))
        assert db.periodisering(g.id).leeg
        db.groep_fasen_opslaan(g.id, [Fase(date(2027, 3, 1), "V2"), Fase(date(2026, 10, 5), "V1")])
        assert [(f.startdatum, f.fase) for f in db.groep_fasen(g.id)] == [(date(2026, 10, 5), "V1"), (date(2027, 3, 1), "V2")]
        db.groep_fasen_opslaan(g.id, [Fase(date(2026, 9, 7), "Rust")])                 # vervangt alles
        assert [f.fase for f in db.groep_fasen(g.id)] == ["Rust"]

        cycli = db.mesocycli_opslaan(g.id, [Mesocyclus(date(2026, 10, 5), 3, ["A", "", "C"])])
        assert cycli[0].id is not None and cycli[0].groep_id == g.id
        terug = db.mesocycli(g.id)
        assert [(m.startdatum, m.aantal_weken, m.weeknamen) for m in terug] == [(date(2026, 10, 5), 3, ["A", "", "C"])]
        db.mesocycli_opslaan(g.id, [Mesocyclus(date(2027, 1, 4), 2), Mesocyclus(date(2026, 11, 2), 4)])
        assert [m.startdatum for m in db.mesocycli(g.id)] == [date(2026, 11, 2), date(2027, 1, 4)]
        assert db.personen.execute("SELECT COUNT(*) FROM mesocyclus_week").fetchone()[0] == 6   # oude weken weg

        assert "dezelfde dag" in _fout(lambda: db.groep_fasen_opslaan(
            g.id, [Fase(date(2026, 1, 5), "V1"), Fase(date(2026, 1, 5), "V2")]))
        assert "dezelfde dag" in _fout(lambda: db.mesocycli_opslaan(
            g.id, [Mesocyclus(date(2026, 1, 5), 2), Mesocyclus(date(2026, 1, 5), 3)]))
        assert [f.fase for f in db.groep_fasen(g.id)] == ["Rust"]                       # niets veranderd
        _fout(lambda: db.groep_fasen_opslaan(9999, []))
        _fout(lambda: db.mesocycli_opslaan(9999, []))

        db.groep_fasen_opslaan(g.id, [])
        db.mesocycli_opslaan(g.id, [])
        assert db.periodisering(g.id).leeg


# ============================================================
# Formulier en opslaan
# ============================================================
def _formulier(**extra) -> dict:
    f = {"fase-0": "V1", "fasestart-0": "2026-10-05", "fase-1": "WP", "fasestart-1": "2026-12-07",
         "fase-2": "", "fasestart-2": "",                                    # lege rij telt niet
         "meso-0-start": "2026-10-07", "meso-0-weken": "4",                  # woensdag -> maandag
         "meso-0-naam-1": "Opbouw", "meso-0-naam-2": "  Opbouw  ", "meso-0-naam-3": "Piek", "meso-0-naam-4": "",
         "meso-0-naam-5": "telt niet",                                      # na het aantal weken
         "meso-1-start": "", "meso-1-weken": "4"}
    f.update(extra)
    return f


def test_opslaan_vanuit_formulier():
    with opslag() as (db, _):
        g = db.groep_opslaan(Groep("U16", "2026-2027"))
        w = periodeplan.opslaan(db, g.id, _formulier())
        assert w.tekst == ("Periodisering opgeslagen: 2 fasen en 1 mesocyclus. "
                           "De start van een mesocyclus is op het begin van de week gezet.")
        m = db.mesocycli(g.id)[0]
        assert (m.startdatum, m.weeknamen) == (date(2026, 10, 5), ["Opbouw", "Opbouw", "Piek", ""])

        # Een rij weghalen = de datum leegmaken.
        periodeplan.opslaan(db, g.id, _formulier(**{"fasestart-1": "", "meso-0-start": ""}))
        assert [f.fase for f in db.groep_fasen(g.id)] == ["V1"] and db.mesocycli(g.id) == []

        for fout, tekst in (({"fase-1": ""}, "rij 2: kies een fase"),
                            ({"fasestart-0": "5 okt"}, "geen geldige datum"),
                            ({"meso-0-weken": "13"}, "1 tot 12 weken"),
                            ({"fasestart-1": "2026-10-05"}, "dezelfde dag"),
                            ({"meso-1-start": "2026-10-09"}, "na het verschuiven")):   # zelfde week als meso-0
            assert tekst in _fout(lambda: periodeplan.opslaan(db, g.id, _formulier(**fout))), fout
        assert [f.fase for f in db.groep_fasen(g.id)] == ["V1"]                       # niets opgeslagen
        _fout(lambda: periodeplan.opslaan(db, 9999, _formulier()))


def test_week_op_zondag():
    """Begint de week op zondag (Instellingen), dan begint een mesocyclus ook op zondag."""
    try:
        instellingen.activeer(instellingen.Instellingen(eerste_dag="zondag"))
        with opslag() as (db, _):
            g = db.groep_opslaan(Groep("U12"))
            periodeplan.opslaan(db, g.id, _formulier())
            assert db.mesocycli(g.id)[0].startdatum == date(2026, 10, 4)               # zondag
    finally:
        instellingen.activeer(instellingen.NEDERLANDS)


def test_formulier_na_fout_en_opgeslagen():
    with opslag() as (db, _):
        g = db.groep_opslaan(Groep("U16"))
        f = periodeplan.formulier(db, g.id)
        assert len(f.fasen) == periodeplan.LEGE_FASE_RIJEN and len(f.cycli) == periodeplan.LEGE_CYCLI
        assert f.fase_keuzes[0] == ("V1", "V1 – Algemene voorbereiding")

        periodeplan.opslaan(db, g.id, _formulier())
        f = periodeplan.formulier(db, g.id)
        assert [(r.fase, r.start) for r in f.fasen[:2]] == [("V1", "2026-10-05"), ("WP", "2026-12-07")]
        assert f.cycli[0].start == "2026-10-05" and f.cycli[0].namen[:4] == ["Opbouw", "Opbouw", "Piek", ""]
        assert len(f.cycli[0].namen) == 12

        f = periodeplan.formulier(db, g.id, ingevuld=_formulier(**{"fase-3": "Rust", "fasestart-3": "x"}))
        assert [r.fase for r in f.fasen if r.fase] == ["V1", "WP", "Rust"]          # wat er was ingevuld blijft
        assert periodeplan.formulier(db, 9999) is None


# ============================================================
# Jaaroverzicht
# ============================================================
def test_jaaroverzicht():
    p = Periodisering(SEIZOEN, [Mesocyclus(date(2026, 10, 5), 4, ["Opbouw", "Opbouw", "Piek", "Herstel"])])
    j = periodeplan.jaaroverzicht(p, vandaag=date(2026, 10, 19))
    assert (j.van, j.tot) == (date(2026, 7, 1), date(2027, 6, 30))                  # 3 maanden terug, 12 maanden
    assert [b.code for b in j.fasen] == ["V1", "WP", "V1", "V2", "WP"]
    assert j.fasen[0].links == round(100 * 96 / 365, 3)                              # 5 okt = dag 96
    assert abs(sum(b.breedte for b in j.fasen) - (100 - j.fasen[0].links)) < 0.01  # aaneengesloten tot het eind
    assert j.weken[0].begin == date(2026, 10, 5) and j.weken[0].titel == "1" and "Opbouw" in j.weken[0].uitleg
    assert [b.titel for b in j.weken[:5]] == ["1", "2", "3", "4", "1"]
    assert j.maanden[0] == ("jul", 0.0) and len(j.maanden) == 12
    assert j.vandaag_pct is not None and j.nu.kort == "V1 · wk 3 Piek"
    assert (j.vorige, j.volgende) == (date(2025, 7, 1), date(2027, 7, 1))
    assert [c for c, _ in j.legenda] == ["V1", "V2", "WP", "Rust"]

    later = periodeplan.jaaroverzicht(p, vandaag=date(2026, 10, 19), van=date(2027, 7, 15))
    assert later.van == date(2027, 7, 1) and later.vandaag_pct is None
    assert [b.code for b in later.fasen] == ["WP", "Rust"] and later.weken            # meso loopt door
    assert periodeplan.jaaroverzicht(Periodisering(), vandaag=VANDAAG).leeg


# ============================================================
# Kopiëren
# ============================================================
def test_kopieren():
    with opslag() as (db, _):
        bron = db.groep_opslaan(Groep("U16 sprint", "2026-2027"))
        a = db.groep_opslaan(Groep("U16 horden", "2026-2027"))
        b = db.groep_opslaan(Groep("Oud", "2025-2026"))
        periodeplan.opslaan(db, bron.id, _formulier())
        db.groep_fasen_opslaan(b.id, [Fase(date(2025, 10, 6), "V1")])

        k = periodeplan.kopieerpagina(db, bron.id)
        assert [d.groep.naam for d in k.doelen] == ["U16 horden", "Oud"]             # zelfde seizoen eerst
        assert (k.doelen[1].fasen, k.doelen[1].cycli) == (1, 0)
        assert k.doelen[1].overschrijft(True, True) == "1 fase" and k.doelen[1].overschrijft(False, True) == ""

        w = periodeplan.kopieren(db, bron.id, [a.id, b.id], fasen=True, cycli=False)
        assert w.tekst == "De megacyclus gekopieerd naar U16 horden, Oud."
        assert db.groep_fasen(a.id) == db.groep_fasen(bron.id) == db.groep_fasen(b.id)
        assert db.mesocycli(a.id) == []
        periodeplan.kopieren(db, bron.id, [a.id], fasen=False, cycli=True)
        assert [m.weeknamen for m in db.mesocycli(a.id)] == [m.weeknamen for m in db.mesocycli(bron.id)]

        # Daarna los van elkaar: de bron wijzigen verandert de kopie niet.
        db.groep_fasen_opslaan(bron.id, [Fase(date(2026, 9, 7), "Rust")])
        assert [f.fase for f in db.groep_fasen(a.id)] == ["V1", "WP"]

        assert "Kies wat" in _fout(lambda: periodeplan.kopieren(db, bron.id, [a.id], fasen=False, cycli=False))
        assert "minstens één" in _fout(lambda: periodeplan.kopieren(db, bron.id, [], fasen=True, cycli=True))
        _fout(lambda: periodeplan.kopieren(db, bron.id, [bron.id], fasen=True, cycli=True))
        _fout(lambda: periodeplan.kopieren(db, bron.id, [9999], fasen=True, cycli=True))
        assert periodeplan.kopieerpagina(db, 9999) is None


# ============================================================
# Trainingen tonen fase en mesoweek
# ============================================================
def test_trainingen_tonen_periode():
    with opslag() as (db, _):
        ids = voorbeeldgroep(db)                       # V1 sinds 2 weken, mesocyclus van 4 weken
        lijst = trainingsbeheer.trainingenlijst(db, db.groep(ids["groep"]), peildatum=VANDAAG)
        startblok = next(r for r in lijst.komend if r.training.onderwerp == "Startblok")
        assert startblok.periode == "V1 · wk 4 Herstel"
        oud = next(r for r in lijst.geweest if r.training.onderwerp == "Te oud")   # vóór de eerste fase
        assert oud.periode is None
        tp = trainingsbeheer.trainingpagina(db, startblok.training.id, peildatum=VANDAAG)
        assert tp.periode.lang == "Algemene voorbereiding (V1) · week 4 van 4: Herstel"


# ============================================================
# Pagina's
# ============================================================
def test_routes():
    with opslag() as (db, tmp):
        ids = voorbeeldgroep(db)
        gid = ids["groep"]
        anderen = db.groep_opslaan(Groep("U14 sprint", "2026-2027"))
        c = app_client(tmp)

        html = c.get(f"/groep/{gid}").get_data(as_text=True)
        assert f'href="/groep/{gid}/periodisering"' in html and "jaar__balk" in html

        html = c.get(f"/groep/{gid}/periodisering").get_data(as_text=True)
        assert "Megacyclus" in html and "Mesocycli" in html and 'name="fase-0"' in html
        assert 'value="V1" selected' in html and html.count('name="meso-0-naam-') == 12
        assert f"/groep/{gid}/periodisering/kopieren" in html and "Vandaag:" in html
        assert c.get(f"/groep/{gid}/periodisering?van=2025-07").status_code == 200
        assert c.get(f"/groep/{gid}/periodisering?van=onzin").status_code == 200

        r = c.post(f"/groep/{gid}/periodisering", data=_formulier())
        assert r.status_code == 302 and r.headers["Location"].endswith(f"/groep/{gid}#kop-periodisering")
        assert "Periodisering opgeslagen: 2 fasen en 1 mesocyclus." in c.get(r.headers["Location"]).get_data(as_text=True)
        assert [f.fase for f in db.groep_fasen(gid)] == ["V1", "WP"]

        r = c.post(f"/groep/{gid}/periodisering", data=_formulier(**{"fase-1": ""}))
        tekst = r.get_data(as_text=True)
        assert r.status_code == 400 and "Niet opgeslagen" in tekst and 'value="2026-12-07"' in tekst
        assert c.get("/groep/9999/periodisering").status_code == 404
        assert c.post("/groep/9999/periodisering", data={}).status_code == 404

        # Kopiëren: naar een lege groep meteen, naar een groep met fasen eerst bevestigen.
        pad = f"/groep/{gid}/periodisering/kopieren"
        html = c.get(pad).get_data(as_text=True)
        assert "U14 sprint" in html and 'name="fasen" value="1" checked' in html
        r = c.post(pad, data={"groep": str(anderen.id), "fasen": "1", "cycli": "1"})
        assert r.status_code == 302 and db.groep_fasen(anderen.id) == db.groep_fasen(gid)

        db.groep_fasen_opslaan(gid, [Fase(date(2026, 9, 7), "Rust")])
        r = c.post(pad, data={"groep": str(anderen.id), "fasen": "1"})
        tekst = r.get_data(as_text=True)
        assert r.status_code == 200 and "dit overschrijft" in tekst and "U14 sprint: 2 fasen" in tekst
        assert [f.fase for f in db.groep_fasen(anderen.id)] == ["V1", "WP"]                 # nog niet
        r = c.post(pad, data={"groep": str(anderen.id), "fasen": "1", "bevestigd": "1"})
        assert r.status_code == 302 and [f.fase for f in db.groep_fasen(anderen.id)] == ["Rust"]

        r = c.post(pad, data={"fasen": "1"})
        assert r.status_code == 400 and "minstens één groep" in r.get_data(as_text=True)
        assert c.get("/groep/9999/periodisering/kopieren").status_code == 404

        # De trainingspagina toont fase en mesoweek.
        tr = db.trainingen(gid, van=MAANDAG + timedelta(days=8))[0]
        assert "Overgang / rust (Rust)" in c.get(f"/training/{tr.id}").get_data(as_text=True)
