"""Tests voor het aanpassen van regels in het tijdschema (starttijd, duur, dag) op de
pagina 'Gegevens wijzigen': wedstrijden.detail.tijdschema_wijzigingen / tijdschema_aanpassen
en de route /wedstrijd/<id>/bewerken. Na opslaan staat het tijdschema weer op dag en tijd.

Alleen nepgegevens en een vaste testsleutel; niets van internet. Werkt met pytest en los:
`python tests/test_tijdschema_aanpassen.py`.
"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_wedstrijdpagina import DAG, _client, _verwacht, opslag  # noqa: E402
from test_wedstrijd_nieuw import nep_site  # noqa: E402

from db.queries import OpslagFout  # noqa: E402
from models import ProgrammaOnderdeel  # noqa: E402
from wedstrijden import detail  # noqa: E402

# Het tijdschema uit test_wedstrijdpagina.opslag():
#   10:00 100m Meisjes U16 (30 min) · 10:15 Verspringen MU16 (45) · 10:30 100m Jongens U16 (30)
#   11:00 Kogelstoten Jongens U12 · 11:30 Hoogspringen U14


def _volgorde(db, wid):
    return [(r.starttijd, r.naam) for r in db.programma(wid)]


def test_wijzigingen_en_volgorde():
    with opslag() as (db, _, ids):
        honderd_m, ver, _, kogel, _ = ids["regels"]
        form = {f"tijd-{kogel}": "9:45", f"duur-{kogel}": "20",       # kogel naar voren, met duur
                f"tijd-{honderd_m}": "10:00", f"duur-{honderd_m}": "35",  # alleen de duur verandert
                f"tijd-{ver}": "10:15", f"duur-{ver}": "45"}             # verandert niet
        w = detail.tijdschema_wijzigingen(db, ids["w"], form)
        assert [x.oud.id for x in w] == [honderd_m, kogel]
        assert w[1].nieuw.starttijd == "09:45" and w[1].nieuw.duur == 20
        assert "11:00u → 09:45u" in w[1].tekst and "duur ? → 20 min" in w[1].tekst
        assert w[0].tekst.endswith("duur 30 → 35 min")
        assert _volgorde(db, ids["w"])[0] == ("10:00", "100m")            # nog niets opgeslagen
        assert detail.tijdschema_aanpassen(db, w) == 2
        # Nu op de nieuwe volgorde, de rest is ongewijzigd.
        assert _volgorde(db, ids["w"]) == [("09:45", "Kogelstoten"), ("10:00", "100m"), ("10:15", "Verspringen"),
                                           ("10:30", "100m"), ("11:30", "Hoogspringen")]
        assert db.programma_regel(honderd_m).duur == 35 and db.programma_regel(honderd_m).categorie == "Meisjes U16"
        # Duur leegmaken = onbekend.
        detail.tijdschema_aanpassen(db, detail.tijdschema_wijzigingen(db, ids["w"], {f"duur-{kogel}": ""}))
        assert db.programma_regel(kogel).duur is None
        # De pagina van de wedstrijd volgt de nieuwe volgorde.
        d = detail.wedstrijd_detail(db, ids["w"])
        assert [r.regel.id for r in d.dagen[0].rijen][0] == kogel


def test_fouten_slaan_niets_op():
    with opslag() as (db, _, ids):
        a, b, *_ = ids["regels"]
        voor = _volgorde(db, ids["w"])
        for form in ({f"tijd-{a}": "25:00"}, {f"tijd-{a}": ""}, {f"duur-{a}": "half uur"}, {f"duur-{a}": "0"},
                     {f"duur-{a}": "999"}, {f"dag-{a}": "morgen"},
                     {f"tijd-{b}": "09:00", f"tijd-{a}": "nee"}):            # één fout: ook b niet opgeslagen
            _verwacht(OpslagFout, lambda form=form: detail.tijdschema_wijzigingen(db, ids["w"], form))
        assert _volgorde(db, ids["w"]) == voor
        assert detail.tijdschema_wijzigingen(db, ids["w"], {}) == []        # niets ingevuld = niets veranderd


def test_meerdaags():
    with opslag() as (db, _, ids):
        dag2 = DAG + timedelta(days=1)
        extra = db.programma_opslaan(ProgrammaOnderdeel(ids["w"], dag2, "09:00", ids["kogel"], categorie="Jongens U12"))
        f = detail.tijdschemaformulier(db, ids["w"])
        assert f.meerdaags and f.dagen == [DAG, dag2]
        kogel = ids["regels"][3]
        w = detail.tijdschema_wijzigingen(db, ids["w"], {f"dag-{kogel}": dag2.isoformat(), f"tijd-{kogel}": "08:30"})
        detail.tijdschema_aanpassen(db, w)
        assert [r.id for r in db.programma(ids["w"])][-2:] == [kogel, extra.id]   # dag 2: 08:30, dan 09:00
        assert db.programma_regel(kogel).datum == dag2


def test_pagina():
    with opslag() as (db, tmp, ids):
        c = _client(tmp)
        kogel = ids["regels"][3]
        html = c.get(f"/wedstrijd/{ids['w']}/bewerken").get_data(as_text=True)
        assert f'name="tijd-{kogel}" value="11:00"' in html and f'name="duur-{ids["regels"][0]}" value="30"' in html
        assert 'name="dag-' not in html                                    # één dag: geen keuzelijst
        gegevens = {"naam": "Clubkampioenschappen", "datum": DAG.isoformat(), "locatie": "Sportpark",
                    "link": "https://www.atletiek.nu/wedstrijd/main/45678/"}
        r = c.post(f"/wedstrijd/{ids['w']}/bewerken", data={**gegevens, f"tijd-{kogel}": "09:30"})
        assert r.status_code == 302
        html = c.get(r.headers["Location"] + "?alle=1").get_data(as_text=True)
        assert "1 regel in het tijdschema aangepast: Kogelstoten Jongens U12: 11:00u → 09:30u." in html
        assert html.index(f'id="regel-{kogel}"') < html.index(f'id="regel-{ids["regels"][0]}"')   # nu bovenaan

        # Fout in een tijd: niets opgeslagen (ook de naam niet), alles blijft ingevuld.
        r = c.post(f"/wedstrijd/{ids['w']}/bewerken", data={**gegevens, "naam": "Nieuwe naam",
                                                            f"tijd-{kogel}": "", f"duur-{kogel}": "15"})
        html = r.get_data(as_text=True)
        assert r.status_code == 400 and "Niet opgeslagen" in html and "vul een starttijd in" in html
        assert 'value="Nieuwe naam"' in html and f'name="duur-{kogel}" value="15"' in html
        assert db.wedstrijd(ids["w"]).naam == "Clubkampioenschappen" and db.programma_regel(kogel).duur is None


def test_opnieuw_ophalen_wint():
    """Wie ook 'tijdschema opnieuw ophalen' aanvinkt, krijgt het tijdschema van de site (en een melding)."""
    with opslag() as (db, tmp, ids):
        c = _client(tmp)
        kogel = ids["regels"][3]
        with nep_site():
            r = c.post(f"/wedstrijd/{ids['w']}/bewerken", data={
                "naam": "CK", "datum": DAG.isoformat(), "link": "https://www.atletiek.nu/wedstrijd/main/45678/",
                f"tijd-{kogel}": "09:30", "bijwerken": "1"})
        html = c.get(r.headers["Location"]).get_data(as_text=True)
        assert "niet bewaard" in html and "Tijdschema geïmporteerd: 15 regels" in html
        assert len(db.programma(ids["w"])) == 15                           # oude tijdschema is vervangen
        assert all(r.naam != "Kogelstoten" for r in db.programma(ids["w"]))


if __name__ == "__main__":
    for naam, fn in list(globals().items()):
        if naam.startswith("test_") and callable(fn):
            fn()
            print("ok ", naam)
