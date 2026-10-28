"""Tests voor meerdere trainingen op één dag en de keuze van de atleet daartussen.

- personen-migratie 006: extra begintijden per groep per dag (groep_extra_trainingstijd)
  en een eigen begintijd per training (training.starttijd).
- trainingsschema-migratie 002: trainingskeuze, welke (groep, tijd) een atleet op
  een weekdag kiest. Geen keuze = alle trainingen van die dag.
- De keuze bepaalt wie vooraf op 'aanwezig' staat; de lijst toont wel alle leden.

Alleen nepgegevens en een vaste testsleutel.
"""

from datetime import date, timedelta

from test_app import client

from atleten import trainingsschema as schema_pagina
from db.queries import Opslag, OpslagFout
from groepen import absentie, trainingen
from groepen import groep as groepsbeheer
from models import Atleet, Trainingsschema
from hulp import TESTSLEUTEL, opslag, tekst, verwacht as _verwacht

MAANDAG = date(2026, 10, 12)
DONDERDAG = MAANDAG + timedelta(days=3)
ZATERDAG = MAANDAG + timedelta(days=5)


def _basis(db):
    """Anna in twee groepen: Sprint (do 18:30) en Junioren (do 19:30, za 09:00 en 10:30)."""
    anna = db.atleet_opslaan(Atleet("Anna", "Aalbers"))
    bas = db.atleet_opslaan(Atleet("Bas", "Bakker"))
    sprint = groepsbeheer.groep_aanmaken(db, "Sprint", "2026-2027", [anna.master_id], {"donderdag": "18:30"})
    junioren = groepsbeheer.groep_aanmaken(db, "Junioren", "2026-2027", [anna.master_id, bas.master_id],
                                           {"donderdag": "19:30", "zaterdag": "09:00"}, {"zaterdag": ["10:30"]})
    return anna, bas, db.groep(sprint.id), db.groep(junioren.id)


def _training(db, groep, datum, tijd):
    return next(t for t in db.trainingen(groep.id, van=datum, tot=datum) if t.effectieve_starttijd(groep) == tijd)


def test_extra_tijden_opslaan():
    with opslag() as db:
        _, _, _, junioren = _basis(db)
        assert junioren.trainingsdagen == {"donderdag": "19:30", "zaterdag": "09:00"}   # hoofdtijd ongewijzigd
        assert junioren.tijden("zaterdag") == ["09:00", "10:30"] and junioren.tijden("maandag") == []
        assert ("zaterdag", "10:30") in junioren.momenten

        # Extra tijd alleen op een vaste dag; ongeldige tijd -> fout, niets gewijzigd.
        _verwacht(OpslagFout, lambda: db.groep_extra_tijden_opslaan(junioren.id, {"maandag": ["17:00"]}))
        _verwacht(OpslagFout, lambda: db.groep_extra_tijden_opslaan(junioren.id, {"zaterdag": ["26:00"]}))
        assert db.groep(junioren.id).tijden("zaterdag") == ["09:00", "10:30"]

        # Dag eraf: de extra tijden van die dag gaan mee.
        groepsbeheer.trainingsdagen_opslaan(db, junioren.id, {"donderdag": "19:30"})
        assert db.groep(junioren.id).extra_tijden == {}
        assert db.personen.execute("SELECT count(*) FROM groep_extra_trainingstijd").fetchone()[0] == 0


def test_extra_tijden_uit_formulier():
    class Formulier(dict):
        def getlist(self, k):
            return self.get(k, [])
    f = Formulier({"tijd-zaterdag": ["09:00", "10.30", ""], "tijd-donderdag": ["19:30"]})
    assert groepsbeheer.lees_extra_tijden(f) == {"zaterdag": ["10:30"]}


def test_aparte_trainingen_per_tijd():
    with opslag() as db:
        _, _, _, junioren = _basis(db)
        trainingen.trainingen_aanvullen(db, junioren, peildatum=MAANDAG, weken_vooruit=1)
        zaterdag = db.trainingen(junioren.id, van=ZATERDAG, tot=ZATERDAG)
        assert [t.effectieve_starttijd(junioren) for t in zaterdag] == ["09:00", "10:30"]
        # Nog een keer aanvullen maakt niets dubbel.
        assert trainingen.trainingen_aanvullen(db, junioren, peildatum=MAANDAG, weken_vooruit=1) == []

        # Extra tijd weg: de lege trainingen van 10:30 worden opgeruimd, die van 09:00 blijven.
        db.groep_extra_tijden_opslaan(junioren.id, {})
        junioren = db.groep(junioren.id)
        weg = trainingen.trainingen_opruimen(db, junioren, peildatum=MAANDAG)
        assert weg and {t.starttijd for t in weg} == {"10:30"}
        assert [t.effectieve_starttijd(junioren) for t in db.trainingen(junioren.id, van=ZATERDAG, tot=ZATERDAG)] == ["09:00"]


def test_traint_mee_zonder_en_met_keuze():
    with opslag() as db:
        anna, _, sprint, junioren = _basis(db)
        for g in (sprint, junioren):
            trainingen.trainingen_aanvullen(db, g, peildatum=MAANDAG, weken_vooruit=1)
        do_sprint = _training(db, sprint, DONDERDAG, "18:30")
        do_junioren = _training(db, junioren, DONDERDAG, "19:30")
        za_vroeg, za_laat = _training(db, junioren, ZATERDAG, "09:00"), _training(db, junioren, ZATERDAG, "10:30")

        schema = db.trainingsschema(anna.master_id)
        assert schema.keuze == {}                                     # geen keuze = alles
        assert all(schema.traint_mee(t, g) for t, g in [(do_sprint, sprint), (do_junioren, junioren),
                                                       (za_vroeg, junioren), (za_laat, junioren)])

        db.trainingskeuze_opslaan(anna.master_id, {"donderdag": [(sprint.id, "18:30")],
                                                   "zaterdag": [(junioren.id, "10:30")]})
        schema = db.trainingsschema(anna.master_id)
        assert schema.traint_mee(do_sprint, sprint) and not schema.traint_mee(do_junioren, junioren)
        assert schema.traint_mee(za_laat, junioren) and not schema.traint_mee(za_vroeg, junioren)

        # Uit de groep Sprint: die keuze telt niet meer, dus donderdag = weer alles.
        groepsbeheer.leden_opslaan(db, sprint.id, [])
        assert db.trainingsschema(anna.master_id).keuze == {"zaterdag": {(junioren.id, "10:30")}}

        # Geen trainingsdag in het schema: nooit mee, ook niet met een keuze.
        db.trainingsschema_opslaan(Trainingsschema.met_dagen(anna.master_id, ["donderdag"]))
        assert not db.trainingsschema(anna.master_id).traint_mee(za_laat, junioren)


def test_absentielijst_vult_alleen_gekozen_training_voor():
    with opslag() as db:
        anna, bas, sprint, junioren = _basis(db)
        for g in (sprint, junioren):
            trainingen.trainingen_aanvullen(db, g, peildatum=MAANDAG, weken_vooruit=1)
        schema_pagina.schema_opslaan(db, anna.master_id, ["zaterdag"],
                                     {"donderdag": {(sprint.id, "18:30")}, "zaterdag": {(junioren.id, "09:00")}})
        do_junioren = _training(db, junioren, DONDERDAG, "19:30")
        za_laat = _training(db, junioren, ZATERDAG, "10:30")

        vooraf = {a.atleet_id for a in absentie.absentielijst(db, do_junioren.id)}
        assert vooraf == {bas.master_id}                               # Anna koos donderdag Sprint
        assert {a.atleet_id for a in absentie.absentielijst(db, za_laat.id)} == {bas.master_id}

        # Het invulformulier toont wel iedereen: Anna zonder voorgestelde status.
        f = trainingen.invulformulier(db, do_junioren.id, peildatum=MAANDAG)
        regels = {r.atleet.voornaam: r for r in f.regels}
        assert set(regels) == {"Anna", "Bas"}
        assert regels["Anna"].status is None and not regels["Anna"].ingeroosterd
        assert regels["Bas"].status == "aanwezig" and regels["Bas"].ingeroosterd


def test_schema_opslaan_met_keuze():
    with opslag() as db:
        anna, _, sprint, junioren = _basis(db)
        mid = anna.master_id
        assert db.trainingsschema(mid).dagen == ["donderdag", "zaterdag"]       # aangevuld bij lid worden

        # Eén van de twee op donderdag: keuze bewaard, tekst noemt de training.
        w = schema_pagina.schema_opslaan(db, mid, [], {"donderdag": {(junioren.id, "19:30")},
                                                       "zaterdag": {(junioren.id, "09:00"), (junioren.id, "10:30")}})
        assert w.keuze_gewijzigd and "Junioren 19:30" in w.tekst
        assert db.trainingsschema(mid).keuze == {"donderdag": {(junioren.id, "19:30")}}   # za: alles = geen keuze
        assert db.trainingsschema(mid).dagen == ["donderdag", "zaterdag"]

        # Het formulier vinkt alleen de gekozen training aan.
        f = schema_pagina.schemaformulier(db, mid, peildatum=MAANDAG)
        do = next(d for d in f.dagen if d.dag == "donderdag")
        assert [(o.tijd, o.gekozen) for o in do.opties] == [("18:30", False), ("19:30", True)]
        assert f.heeft_opties and do.veld == "training-donderdag"

        # Alles aanvinken: keuze weg. Alles uitvinken op zaterdag: zaterdag uit het schema.
        schema_pagina.schema_opslaan(db, mid, [], {"donderdag": {(sprint.id, "18:30"), (junioren.id, "19:30")}})
        assert db.trainingsschema(mid).keuze == {} and db.trainingsschema(mid).dagen == ["donderdag"]

        # Training kiezen die de groepen niet hebben -> fout; zonder `trainingen` blijft de keuze staan.
        _verwacht(OpslagFout, lambda: schema_pagina.schema_opslaan(db, mid, [], {"donderdag": {(sprint.id, "20:00")}}))
        schema_pagina.schema_opslaan(db, mid, [], {"zaterdag": {(junioren.id, "10:30")}})
        schema_pagina.schema_opslaan(db, mid, ["zaterdag", "maandag"])
        assert db.trainingsschema(mid).keuze == {"zaterdag": {(junioren.id, "10:30")}}


def test_lees_trainingen():
    class Formulier(dict):
        def getlist(self, k):
            return self.get(k, [])
    assert schema_pagina.lees_trainingen(Formulier({"training-zaterdag": ["3|10:30", "3|09:00"]})) == {
        "zaterdag": {(3, "10:30"), (3, "09:00")}}
    _verwacht(OpslagFout, lambda: schema_pagina.lees_trainingen(Formulier({"training-zaterdag": ["x|10:30"]})))


def test_pagina_en_route():
    with client() as (c, mid, tmp):
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            g = groepsbeheer.groep_aanmaken(db, "Zaterdaggroep", "2026-2027", [mid], {"zaterdag": "09:00"},
                                            {"zaterdag": ["10:30"]})
        r = c.get(f"/atleet/{mid}/trainingsschema")
        assert r.status_code == 200
        assert f'name="training-zaterdag" value="{g.id}|09:00" checked' in tekst(r)
        assert f'value="{g.id}|10:30" checked' in tekst(r)

        r = c.post(f"/atleet/{mid}/trainingsschema", data={"training-zaterdag": [f"{g.id}|10:30"]})
        assert r.status_code == 302
        with Opslag(map=tmp, hoofd=TESTSLEUTEL) as db:
            assert db.trainingsschema(mid).keuze == {"zaterdag": {(g.id, "10:30")}}
        r = c.get(f"/atleet/{mid}/trainingsschema")
        assert f'value="{g.id}|09:00">' in tekst(r) and f'value="{g.id}|10:30" checked' in tekst(r)

        r = c.post(f"/atleet/{mid}/trainingsschema", data={"training-zaterdag": ["kapot"]})
        assert r.status_code == 400 and "Niet opgeslagen" in tekst(r)
