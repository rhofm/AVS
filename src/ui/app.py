"""Webserver (Flask) met de routes voor de UI.

Starten (vanuit de repo-root):

    python src                 # opent de browser op http://127.0.0.1:<poort>/
    python src/ui/app.py       # hetzelfde

De server luistert alleen op 127.0.0.1: andere computers in het netwerk kunnen
er niet bij. Elke request krijgt een eigen `Opslag` (SQLCipher-verbindingen
mogen niet tussen threads worden gedeeld) en die wordt na de request gesloten.

Voor tests: `maak_app(map=..., hoofd=...)` met een tijdelijke map en testsleutel.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path

if __package__ in (None, ""):          # los gestart: src/ op het pad zetten
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, abort, flash, g, get_flashed_messages, redirect, render_template, request, url_for

from atleten import beheer, landingspagina
from atleten.aanwezigheid import aanwezigheid
from db.init_db import SleutelFout, init_db
from db.queries import Opslag, OpslagFout
from leerlijnen import voortgang
from ui.opmaak import registreer_filters
from wedstrijden import kalender

HOST = "127.0.0.1"
VOORKEUR_POORT = 5050

#: Menu-items en losse links die nog geen eigen pagina hebben: (pad, titel).
BINNENKORT = {
    "groepen": "Groepen",
    "wedstrijden": "Wedstrijden",
    "ploegen": "Ploegen",
    "leerlijnen": "Leerlijnen",
    "importeren": "Importeren",
    "instellingen": "Instellingen",
}
ATLEET_BINNENKORT = {
    "trainingsschema": "Trainingsschema aanpassen",
    "notities": "Notities",
    "notities/nieuw": "Nieuwe notitie",
    "inschrijven": "Inschrijven voor een wedstrijd",
}


def _ui_map() -> Path:
    """Map met templates/ en static/, ook in de PyInstaller-.exe (sys._MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ui"          # build.py: --add-data src/ui/templates;ui/templates (en static)
    return Path(__file__).resolve().parent


def maak_app(map: Path | None = None, hoofd: str | bytes | None = None, startfout: str | None = None) -> Flask:
    """Maak de Flask-app.

    map / hoofd: databasemap en sleutel; None = de normale (data/ en de sleutelkluis).
    startfout:   melding als de databases niet geopend konden worden; dan toont
                 elke pagina die melding in plaats van te crashen.
    """
    ui = _ui_map()
    app = Flask(__name__, template_folder=str(ui / "templates"), static_folder=str(ui / "static"))
    app.secret_key = os.urandom(32)         # alleen voor meldingen na opslaan; hoeft niet te blijven bestaan
    app.config["AVS_MAP"] = map
    app.config["AVS_HOOFD"] = hoofd
    registreer_filters(app.jinja_env)

    # ---------------- databases per request ----------------
    def db() -> Opslag:
        if "db" not in g:
            g.db = Opslag(map=app.config["AVS_MAP"], hoofd=app.config["AVS_HOOFD"])
        return g.db

    @app.teardown_appcontext
    def sluit_db(_fout=None) -> None:
        opslag = g.pop("db", None)
        if opslag is not None:
            opslag.sluit()

    @app.before_request
    def controleer_start():
        if startfout and request.endpoint != "static":
            return render_template("fout.html", titel="AVS kan niet starten", tekst=startfout), 500

    def haal_atleet(master_id: str):
        a = db().atleet(master_id)
        if a is None:
            abort(404)
        return a

    # ---------------- pagina's ----------------
    @app.get("/")
    def start():
        return redirect(url_for("atleten"))

    @app.get("/atleten")
    def atleten():
        zoek = request.args.get("q", "").strip()
        ook_inactief = request.args.get("alle") == "1"
        vandaag = date.today()
        rijen = []
        for a in beheer.zoeken(db(), zoek, alleen_actief=not ook_inactief):
            rijen.append({
                "atleet": a,
                "categorie": landingspagina.categorie_code(landingspagina.leeftijdscategorie(a, vandaag), a.geslacht),
                "groepen": [gr.naam for gr in db().groepen_van_atleet(a.master_id)],
            })
        return render_template("atleten.html", rijen=rijen, zoek=zoek, ook_inactief=ook_inactief,
                               actief_menu="atleten")

    @app.get("/atleet/<master_id>")
    def atleet(master_id: str):
        pagina = landingspagina.landingspagina(db(), master_id)
        if pagina is None:
            abort(404)
        return render_template("atleet.html", pagina=pagina, fases=landingspagina.FASES, actief_menu="atleten")

    @app.get("/atleet/<master_id>/wedstrijden")
    def atleet_wedstrijden(master_id: str):
        a = haal_atleet(master_id)
        return render_template(
            "wedstrijdplanning.html", planning=kalender.wedstrijdplanning(db(), master_id),
            kop_naam=a.naam, terug_url=url_for("atleet", master_id=master_id),
            nieuw_url=url_for("atleet_binnenkort", master_id=master_id, onderdeel="inschrijven"),
            weergave=request.args.get("weergave", "lijst"), actief_menu="atleten")

    @app.get("/atleet/<master_id>/aanwezigheid")
    def atleet_aanwezigheid(master_id: str):
        a = haal_atleet(master_id)
        return render_template(
            "aanwezigheid.html", aw=aanwezigheid(db(), master_id), kop_naam=a.naam,
            terug_url=url_for("atleet", master_id=master_id),
            weergave=request.args.get("weergave", "lijst"), actief_menu="atleten")

    def _leerdoelen(master_id: str, *, modus: str, fout: str | None = None, status: int = 200):
        a = haal_atleet(master_id)
        categorie = landingspagina.leeftijdscategorie(a, date.today())
        lp = voortgang.leerdoelenpagina(db(), master_id, categorie, doorlopend=request.args.get("doorlopend") == "1")
        meldingen = get_flashed_messages()
        return render_template(
            "leerdoelen.html", lp=lp, basis_url=url_for("atleet", master_id=master_id), modus=modus,
            melding=meldingen[0] if meldingen else None, fout=fout, actief_menu="atleten"), status

    @app.get("/atleet/<master_id>/leerdoelen")
    def atleet_leerdoelen(master_id: str):
        return _leerdoelen(master_id, modus=request.args.get("modus", "bekijken"))

    @app.post("/atleet/<master_id>/leerdoelen")
    def atleet_leerdoelen_opslaan(master_id: str):
        haal_atleet(master_id)
        try:
            datum = date.fromisoformat(request.form.get("datum", ""))
        except ValueError:
            return _leerdoelen(master_id, modus="bewerken", fout="Vul een geldige datum in.", status=400)
        if datum > date.today():
            return _leerdoelen(master_id, modus="bewerken", fout="De datum mag niet in de toekomst liggen.",
                               status=400)
        try:
            aantal = voortgang.scores_opslaan(db(), master_id, request.form, datum)
        except (OpslagFout, ValueError) as e:
            return _leerdoelen(master_id, modus="bewerken", fout=f"Niet opgeslagen: {e}", status=400)
        flash("Geen scores gewijzigd." if aantal == 0 else
              f"{aantal} score{'s' if aantal != 1 else ''} opgeslagen.")
        # Post/Redirect/Get: verversen stuurt het formulier niet nog eens.
        return redirect(url_for("atleet_leerdoelen", master_id=master_id,
                                **({"doorlopend": "1"} if request.args.get("doorlopend") == "1" else {})))

    # ---------------- nog te bouwen ----------------
    @app.get("/<any(" + ", ".join(BINNENKORT) + "):onderdeel>")
    def binnenkort(onderdeel: str):
        return render_template("binnenkort.html", titel=BINNENKORT[onderdeel], terug_url=url_for("atleten"),
                               actief_menu=onderdeel)

    @app.get("/atleet/<master_id>/<path:onderdeel>")
    def atleet_binnenkort(master_id: str, onderdeel: str):
        if onderdeel not in ATLEET_BINNENKORT:
            abort(404)
        a = haal_atleet(master_id)
        return render_template("binnenkort.html", titel=ATLEET_BINNENKORT[onderdeel],
                               terug_url=url_for("atleet", master_id=master_id), terug_naam=a.naam,
                               actief_menu="atleten")

    @app.errorhandler(404)
    def niet_gevonden(_e):
        return render_template("fout.html", titel="Niet gevonden",
                               tekst="Deze pagina of atleet bestaat niet (meer)."), 404

    return app


# ============================================================
# Starten
# ============================================================
def _vrije_poort(voorkeur: int = VOORKEUR_POORT) -> int:
    """De voorkeurspoort als die vrij is, anders een willekeurige vrije poort."""
    for poort in (voorkeur, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, poort))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Geen vrije poort gevonden.")


def start(map: Path | None = None, browser: bool = True) -> None:
    """Databases klaarzetten, de server starten en de browser openen."""
    startfout = None
    try:
        init_db(map)
    except SleutelFout as e:
        startfout = (f"{e}\n\nZet de herstelsleutel terug met: python src/db/init_db.py --herstel <sleutel>")
    app = maak_app(map=map, startfout=startfout)
    poort = _vrije_poort()
    adres = f"http://{HOST}:{poort}/"
    print(f"AVS draait op {adres}  (sluit dit venster om te stoppen)")
    if browser:
        threading.Timer(1.0, webbrowser.open, args=(adres,)).start()
    # Eén gebruiker op één computer: één thread is genoeg en houdt SQLCipher eenvoudig.
    app.run(host=HOST, port=poort, debug=False, threaded=False, use_reloader=False)


if __name__ == "__main__":
    start()
