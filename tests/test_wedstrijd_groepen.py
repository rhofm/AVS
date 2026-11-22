"""Tests voor zelf gekozen groepen bij een onderdeel van het tijdschema (inschrijving.tijdschema_groep).

Alleen nepgegevens en een vaste testsleutel.
"""

from datetime import timedelta

import pytest
from voorbeeld_atleet import VANDAAG, opslag, voorbeeld

from db.queries import OpslagFout
from models import Onderdeel, ProgrammaOnderdeel
from wedstrijden import chronoloog, detail, planning


def _wedstrijd_met_groepen(db):
    """Verspringen in groepen: Mannen groep 1 en 2, Vrouwen groep 1, zonder leeftijd in de categorie."""
    dag = VANDAAG + timedelta(days=10)
    w = planning.plan_wedstrijd(db, "Open baanwedstrijd", dag)
    ver = db.onderdeel("Verspringen")
    db.programma_vervangen(w.id, [
        ProgrammaOnderdeel(w.id, dag, "10:00", ver.id, "Verspringen", "Mannen", groep=1),
        ProgrammaOnderdeel(w.id, dag, "11:30", ver.id, "Verspringen", "Mannen", groep=2),
        ProgrammaOnderdeel(w.id, dag, "10:00", ver.id, "Verspringen", "Vrouwen", groep=1),
    ])
    return w, ver


def _atleten_per_groep(db, wedstrijd_id):
    return {o.regel.groep_sleutel: [a.naam for a in o.atleten] for o in chronoloog.overzicht(db, wedstrijd_id)}


def test_groep_sleutel_en_tekst():
    r = ProgrammaOnderdeel(1, VANDAAG, "10:00", None, "Kogelstoten", "Mannen", groep=2)
    assert r.groep_sleutel == "Mannen|2" and r.groep_tekst == "Mannen · groep 2"
    assert ProgrammaOnderdeel(1, VANDAAG, "10:00", None, "Kogel", None, groep=1).groep_tekst == "Groep 1"
    assert ProgrammaOnderdeel(1, VANDAAG, "10:00", None, "Kogel").groep_tekst == "Alle"


def test_groep_met_gewicht():
    r = ProgrammaOnderdeel(1, VANDAAG, "10:00", None, "Kogelstoten 7,26kg", "Mannen", groep=2)
    assert r.gewicht == "7,26kg"
    assert r.groep_sleutel == "Mannen|2|7,26kg" and r.groep_sleutel_zonder_gewicht == "Mannen|2"
    assert r.groep_tekst == "7,26kg · Mannen · groep 2"
    assert ProgrammaOnderdeel(1, VANDAAG, "10:00", None, "Kogel", None, opmerking="3 kg").groep_tekst == "3kg"
    assert ProgrammaOnderdeel(1, VANDAAG, "10:00", None, "Kogel").gewicht is None
    assert ProgrammaOnderdeel(1, VANDAAG, "10:00", None, "100m horden 83,8cm").gewicht is None


def test_gemengde_werpgroepen_per_gewicht_kiesbaar():
    with opslag() as db:
        mid = voorbeeld(db)
        dag = VANDAAG + timedelta(days=10)
        w = planning.plan_wedstrijd(db, "Werpwedstrijd", dag)
        kogel = db.onderdeel_opslaan(Onderdeel("Kogelstoten", "afstand", False, "werpen"))
        db.programma_vervangen(w.id, [
            ProgrammaOnderdeel(w.id, dag, "10:00", kogel.id, "Kogelstoten 3kg", "Vrouwen U16", groep=1),
            ProgrammaOnderdeel(w.id, dag, "10:00", kogel.id, "Kogelstoten 4kg", "Vrouwen U16", groep=1),
        ])
        d = detail.wedstrijd_detail(db, w.id)
        assert [t for _, t in d.groepsopties[kogel.id]] == ["3kg · Vrouwen U16 · groep 1", "4kg · Vrouwen U16 · groep 1"]
        detail.inschrijven_uit_formulier(db, w.id, [mid], [kogel.id], {kogel.id: "Vrouwen U16|1|4kg"})
        assert [r.regel.onderdeel_tekst for r in chronoloog.persoonlijk_schema(db, w.id, mid)] == ["Kogelstoten 4kg"]
        # Een keuze van vóór het gewicht ('Vrouwen U16|1') geeft beide groepen.
        db.inschrijving_groep_zetten(mid, w.id, kogel.id, "Vrouwen U16|1")
        assert len(chronoloog.persoonlijk_schema(db, w.id, mid)) == 2


def test_gekozen_groep_gaat_voor_op_categorie():
    with opslag() as db:
        mid = voorbeeld(db)
        w, ver = _wedstrijd_met_groepen(db)
        planning.inschrijven(db, w.id, mid, ["Verspringen"])
        # Zonder keuze beslist de categorie: een jeugdatleet valt niet onder 'Mannen' of 'Vrouwen' (senioren).
        assert all(not namen for namen in _atleten_per_groep(db, w.id).values())
        db.inschrijving_groep_zetten(mid, w.id, ver.id, "Vrouwen|1")
        per_groep = _atleten_per_groep(db, w.id)
        assert per_groep["Vrouwen|1"] == ["Anna Voorbeeld"] and not per_groep["Mannen|1"] and not per_groep["Mannen|2"]
        assert [r.regel.groep_sleutel for r in chronoloog.persoonlijk_schema(db, w.id, mid)] == ["Vrouwen|1"]
        # Weer automatisch.
        db.inschrijving_groep_zetten(mid, w.id, ver.id, None)
        assert all(not namen for namen in _atleten_per_groep(db, w.id).values())


def test_groep_blijft_bij_opnieuw_inschrijven_en_overleeft_import():
    with opslag() as db:
        mid = voorbeeld(db)
        w, ver = _wedstrijd_met_groepen(db)
        planning.inschrijven(db, w.id, mid, ["Verspringen"])
        db.inschrijving_groep_zetten(mid, w.id, ver.id, "Mannen|2")
        planning.inschrijven(db, w.id, mid, ["Verspringen"])                  # nog eens: niet wissen
        assert [i.groep for i in db.inschrijvingen(mid) if i.wedstrijd_id == w.id] == ["Mannen|2"]
        regels = db.programma(w.id)                                            # 'opnieuw importeren': nieuwe regel-id's
        db.programma_vervangen(w.id, [ProgrammaOnderdeel(w.id, r.datum, r.starttijd, r.onderdeel_id, r.onderdeel_tekst,
                                                         r.categorie, groep=r.groep) for r in regels])
        assert _atleten_per_groep(db, w.id)["Mannen|2"] == ["Anna Voorbeeld"]


def test_inschrijven_uit_formulier_en_groep_kiezen():
    with opslag() as db:
        mid = voorbeeld(db)
        w, ver = _wedstrijd_met_groepen(db)
        assert detail.inschrijven_uit_formulier(db, w.id, [mid], [ver.id], {ver.id: "Mannen|1"}) == 1
        assert [i.groep for i in db.inschrijvingen(mid) if i.wedstrijd_id == w.id] == ["Mannen|1"]
        d = detail.wedstrijd_detail(db, w.id, VANDAAG)
        assert [s for s, _ in d.groepsopties[ver.id]] == ["Mannen|1", "Vrouwen|1", "Mannen|2"]   # op tijd: 10:00, 10:00, 11:30
        assert d.deelnemers[0].groep_van == {ver.id: "Mannen|1"}
        assert "niet" not in " ".join(d.deelnemers[0].niet_in_tijdschema)      # staat nu wel in het tijdschema
        assert "Vrouwen" in detail.groep_kiezen(db, w.id, mid, ver.id, "Vrouwen|1")
        assert "automatisch" in detail.groep_kiezen(db, w.id, mid, ver.id, "")
        with pytest.raises(OpslagFout):
            detail.groep_kiezen(db, w.id, mid, ver.id, "Mannen|9")             # staat niet in het tijdschema
        with pytest.raises(OpslagFout):
            detail.inschrijven_uit_formulier(db, w.id, [mid], [ver.id], {ver.id: "Dames|1"})


def test_inschrijfformulier_kiest_groep_van_de_regel_voor():
    with opslag() as db:
        voorbeeld(db)
        w, ver = _wedstrijd_met_groepen(db)
        regel = [r for r in db.programma(w.id) if r.groep_sleutel == "Mannen|2"][0]
        f = detail.inschrijfformulier(db, w.id, regel.id)
        assert f.groep_keuze == {ver.id: "Mannen|2"}
        assert [(o.naam, len(opties)) for o, opties in f.groep_onderdelen] == [("Verspringen", 3)]
