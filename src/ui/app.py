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
from urllib.parse import urlparse

if __package__ in (None, ""):          # los gestart: src/ op het pad zetten
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import (Flask, Response, abort, flash, g, get_flashed_messages, redirect, render_template, request,
                   url_for)

from atleten import beheer, landingspagina
from atleten import aanpassen as atleetbeheer
from atleten import nieuw as nieuwe_atleten
from atleten import notities as notitiebeheer
from atleten.overzicht import atletenoverzicht
from atleten import trainingsschema as schemabeheer
from atleten import prs_importeren as prs_import
from atleten.aanwezigheid import aanwezigheid
import instellingen
from db.init_db import (HERSTEL_UITLEG, InstallatieFout, OvernameFout, SleutelFout, herstel, init_db,
                        oude_data_overnemen, standaard_map)
from db.queries import Opslag, OpslagFout
from importers.base import ImportFout
from groepen import groep as groepsbeheer
from groepen import groep_importeren
from groepen.groepenoverzicht import GEEN_SEIZOEN, groepenoverzicht
from groepen import landingspagina as groep_landingspagina
from groepen import periodeplan as periodisering
from groepen import rooster as roosterbeheer
from groepen import doelen as doelbeheer
from groepen import overzichten as groep_overzichten
from groepen import trainingen as trainingsbeheer
from leerlijnen import overzicht as leerlijnoverzicht
from leerlijnen import voortgang
from ui import export as trainingsexport
from ui import importeren as importeerpagina
from ui import startpagina
from ui.opmaak import registreer_filters
from ploeg import export as ploegexport
from ploeg import paginas as ploegpaginas
from ploeg.optimaliseer import OptimalisatieFout
from ploeg.regels import RegelFout
from wedstrijden import detail as wedstrijddetail
from wedstrijden import kalender, tijdschema_import, uitslag_import
from wedstrijden.overzicht import wedstrijdenoverzicht

HOST = "127.0.0.1"
VOORKEUR_POORT = 5050

#: Menu-items en losse links die nog geen eigen pagina hebben: (pad, titel).
BINNENKORT: dict[str, str] = {
}
ATLEET_BINNENKORT: dict[str, str] = {
}

#: Pagina's die ook werken als de databases niet open kunnen (bijv. sleutel kwijt):
#: daar zet de gebruiker de herstelsleutel terug. Ze gebruiken geen database.
ZONDER_DATABASE = frozenset({"static", "instellingen_pagina", "instellingen_opslaan", "sleutel_herstellen"})


def _ui_map() -> Path:
    """Map met templates/ en static/, ook in de PyInstaller-.exe (sys._MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ui"          # build.py: --add-data src/ui/templates;ui/templates (en static)
    return Path(__file__).resolve().parent


def maak_app(map: Path | None = None, hoofd: str | bytes | None = None, startfout: str | None = None,
             sleutelfout: bool = True) -> Flask:
    """Maak de Flask-app.

    map / hoofd: databasemap en sleutel; None = de normale (data/ en de sleutelkluis).
    startfout:   melding als de databases niet geopend konden worden; dan toont
                 elke pagina die melding in plaats van te crashen, behalve
                 Instellingen (ZONDER_DATABASE), waar de sleutel kan worden hersteld.
    sleutelfout: True als startfout over de sleutel gaat (dan een knop 'Sleutel herstellen');
                 False bij bijv. een onvolledige installatie (InstallatieFout).
    """
    ui = _ui_map()
    app = Flask(__name__, template_folder=str(ui / "templates"), static_folder=str(ui / "static"))
    app.secret_key = os.urandom(32)         # alleen voor meldingen na opslaan; hoeft niet te blijven bestaan
    app.config["AVS_MAP"] = map
    app.config["AVS_HOOFD"] = hoofd
    app.config["AVS_STARTFOUT"] = startfout     # wordt None na 'Sleutel herstellen'
    app.config["AVS_STARTFOUT_SLEUTEL"] = sleutelfout
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
        fout = app.config["AVS_STARTFOUT"]
        if fout and request.endpoint not in ZONDER_DATABASE:
            return render_template("fout.html", titel="AVS kan niet starten", tekst=fout,
                                   sleutel_herstellen=app.config["AVS_STARTFOUT_SLEUTEL"]), 500

    @app.before_request
    def instellingen_laden():
        """Elke request de opgeslagen instellingen (eerste weekdag, thema, tijdnotatie) actief maken.
        Het bestand is klein; zo telt een wijziging (ook 'zoals de computer') meteen mee."""
        if request.endpoint != "static":
            instellingen.activeer(instellingen.laad(app.config["AVS_MAP"]))

    @app.teardown_request
    def instellingen_terugzetten(_fout=None):
        instellingen.activeer(instellingen.NEDERLANDS)     # niets laten doorlekken naar code buiten een request

    @app.context_processor
    def instellingen_in_templates():
        inst = instellingen.actief()
        dagen = inst.dagen()
        return {"thema": inst.thema_attribuut,
                "weekkoppen": [d[:2].capitalize() for d in dagen]}     # ['Ma', 'Di', …] of ['Zo', 'Ma', …]

    @app.before_request
    def trainingen_klaarzetten():
        """Eén keer per dag (bij de eerste pagina): trainingen aanmaken voor de vaste trainingsdagen
        van alle groepen, tot een paar weken vooruit. Zie groepen.trainingen.trainingen_aanvullen()."""
        if (request.endpoint in ZONDER_DATABASE or app.config["AVS_STARTFOUT"]
                or app.config.get("AVS_AANGEVULD_OP") == date.today()):
            return None
        trainingsbeheer.alle_trainingen_aanvullen(db())
        app.config["AVS_AANGEVULD_OP"] = date.today()
        return None

    def haal_atleet(master_id: str):
        a = db().atleet(master_id)
        if a is None:
            abort(404)
        return a

    # ---------------- pagina's ----------------
    @app.get("/")
    def start():
        vandaag = date.today()
        return render_template("start.html", tegels=startpagina.tegels(db(), vandaag), vandaag=vandaag)

    @app.get("/atleten")
    def atleten():
        groep = request.args.get("groep", "")
        o = atletenoverzicht(db(), zoek=request.args.get("q", ""), categorie=request.args.get("cat", ""),
                             groep_id=int(groep) if groep.isdigit() else None,
                             ook_inactief=request.args.get("alle") == "1")
        meldingen = get_flashed_messages()
        return render_template("atleten.html", o=o, melding=meldingen[0] if meldingen else None,
                               actief_menu="atleten")

    # ---------------- nieuwe atleet ----------------
    def _nieuw(ingevuld=None, *, fouten: dict | None = None, dubbelen=None, status: int = 200):
        return render_template("atleet_nieuw.html", f=nieuwe_atleten.formulier(db(), ingevuld),
                               fouten=fouten or {}, dubbelen=dubbelen, actief_menu="atleten"), status

    @app.get("/atleten/nieuw")
    def atleet_nieuw():
        return _nieuw()

    @app.post("/atleten/nieuw")
    def atleet_nieuw_opslaan():
        try:
            invoer = nieuwe_atleten.lees_formulier(db(), request.form)
        except nieuwe_atleten.InvoerFout as e:
            return _nieuw(request.form, fouten=e.fouten, status=400)
        try:
            a = nieuwe_atleten.aanmaken(db(), invoer, toch_aanmaken=request.form.get("toch") == "1")
        except beheer.DubbeleAtleet as e:
            return _nieuw(request.form, dubbelen=e.bestaande, status=409)
        except (OpslagFout, ValueError) as e:
            return _nieuw(request.form, fouten={"algemeen": str(e)}, status=400)
        flash(f"{a.naam} is toegevoegd.")
        return redirect(url_for("atleet", master_id=a.master_id))

    # ---------------- atleet aanpassen / verwijderen ----------------
    def _aanpassen(master_id: str, ingevuld=None, *, fouten: dict | None = None,
                   verwijder_fout: str | None = None, status: int = 200):
        r = atleetbeheer.aanpasformulier(db(), master_id, ingevuld)
        if r is None:
            abort(404)
        a, f, actief = r
        return render_template("atleet_aanpassen.html", a=a, f=f, actief=actief, fouten=fouten or {},
                               verwijder_fout=verwijder_fout, actief_menu="atleten"), status

    @app.get("/atleet/<master_id>/aanpassen")
    def atleet_aanpassen(master_id: str):
        return _aanpassen(master_id)

    @app.post("/atleet/<master_id>/aanpassen")
    def atleet_aanpassen_opslaan(master_id: str):
        haal_atleet(master_id)
        try:
            w = atleetbeheer.lees_en_opslaan(db(), master_id, request.form)
        except nieuwe_atleten.InvoerFout as e:
            return _aanpassen(master_id, request.form, fouten=e.fouten, status=400)
        except (OpslagFout, ValueError) as e:
            return _aanpassen(master_id, request.form, fouten={"algemeen": str(e)}, status=400)
        flash(w.tekst)
        return redirect(url_for("atleet", master_id=master_id))

    @app.post("/atleet/<master_id>/verwijderen")
    def atleet_verwijderen(master_id: str):
        haal_atleet(master_id)
        try:
            a = atleetbeheer.verwijderen(db(), master_id, request.form.get("bevestiging", ""))
        except (OpslagFout, ValueError) as e:
            return _aanpassen(master_id, verwijder_fout=str(e), status=400)
        flash(f"{a.naam} en alle gegevens zijn verwijderd.")
        return redirect(url_for("atleten"))

    @app.get("/atleet/<master_id>")
    def atleet(master_id: str):
        pagina = landingspagina.landingspagina(db(), master_id)
        if pagina is None:
            abort(404)
        meldingen = get_flashed_messages(with_categories=True)
        algemeen = [m for soort, m in meldingen if not soort.startswith("prs")]
        prs = next(((m, soort == "prs-fout") for soort, m in meldingen if soort.startswith("prs")), None)
        return render_template("atleet.html", pagina=pagina, fases=landingspagina.FASES,
                               melding=algemeen[0] if algemeen else None, prs_melding=prs, actief_menu="atleten")

    @app.post("/atleet/<master_id>/prs/importeren")
    def atleet_prs_importeren(master_id: str):
        """Knop 'PR's ophalen' op de atletenpagina: prestaties van atletiek.nu bijwerken."""
        haal_atleet(master_id)
        try:
            flash(prs_import.prs_importeren(db(), master_id, _haal_profiel()).tekst, "prs")
        except (OpslagFout, ImportFout) as e:
            flash(f"PR's niet opgehaald: {str(e).splitlines()[0]}", "prs-fout")
        return redirect(url_for("atleet", master_id=master_id) + "#kop-pr")

    @app.get("/atleet/<master_id>/voorkeuren")
    def atleet_voorkeuren(master_id: str):
        haal_atleet(master_id)
        return render_template("atleet_voorkeuren.html", av=ploegpaginas.atleet_voorkeuren(db(), master_id),
                               actief_menu="atleten")

    @app.post("/atleet/<master_id>/voorkeuren")
    def atleet_voorkeuren_opslaan(master_id: str):
        haal_atleet(master_id)
        try:
            n = ploegpaginas.atleet_voorkeuren_opslaan(db(), master_id, request.form)
        except OpslagFout as e:
            return render_template("atleet_voorkeuren.html", av=ploegpaginas.atleet_voorkeuren(db(), master_id),
                                   fout=f"Niet opgeslagen: {e}", actief_menu="atleten"), 400
        flash(f"Voorkeuren voor ploegen opgeslagen ({n} ingesteld).")
        return redirect(url_for("atleet", master_id=master_id) + "#kop-wed")

    @app.get("/atleet/<master_id>/wedstrijden")
    def atleet_wedstrijden(master_id: str):
        a = haal_atleet(master_id)
        return render_template(
            "wedstrijdplanning.html", planning=kalender.wedstrijdplanning(db(), master_id),
            kop_naam=a.naam, terug_url=url_for("atleet", master_id=master_id),
            nieuw_url=url_for("atleet_inschrijven", master_id=master_id),
            weergave=request.args.get("weergave", "lijst"), melding=(get_flashed_messages() or [None])[0],
            actief_menu="atleten")

    @app.get("/atleet/<master_id>/inschrijven")
    def atleet_inschrijven(master_id: str):
        """'+ Inschrijven' op de wedstrijdplanning: kies een komende wedstrijd of maak een nieuwe."""
        k = wedstrijddetail.wedstrijdkeuze(db(), master_id)
        if k is None:
            abort(404)
        return render_template("atleet_inschrijven.html", k=k, actief_menu="atleten")

    @app.get("/atleet/<master_id>/aanwezigheid")
    def atleet_aanwezigheid(master_id: str):
        a = haal_atleet(master_id)
        return render_template(
            "aanwezigheid.html", aw=aanwezigheid(db(), master_id), kop_naam=a.naam,
            terug_url=url_for("atleet", master_id=master_id),
            weergave=request.args.get("weergave", "lijst"), actief_menu="atleten")

    # ---------------- groepen ----------------
    def haal_groep(groep_id: int):
        gr = db().groep(groep_id)
        if gr is None:
            abort(404)
        return gr

    @app.get("/groepen")
    def groepen():
        o = groepenoverzicht(db(), zoek=request.args.get("q", ""), seizoen=request.args.get("seizoen", ""),
                             dag=request.args.get("dag", ""))
        return render_template("groepen.html", o=o, geen_seizoen=GEEN_SEIZOEN, actief_menu="groepen")

    @app.get("/groepen/nieuw")
    def groep_nieuw():
        return render_template("groep_leden.html", f=groepsbeheer.nieuw_formulier(db()), fout=None,
                               actief_menu="groepen")

    @app.post("/groepen/nieuw")
    def groep_nieuw_opslaan():
        naam, seizoen, gekozen = request.form.get("naam", ""), request.form.get("seizoen", ""), request.form.getlist("lid")
        try:
            dagen = groepsbeheer.lees_trainingsdagen(request.form)
            g = groepsbeheer.groep_aanmaken(db(), naam, seizoen, gekozen, dagen,
                                            groepsbeheer.lees_extra_tijden(request.form))
        except (OpslagFout, ValueError) as e:
            f = groepsbeheer.nieuw_formulier(db(), naam=naam, seizoen=seizoen,
                                             gekozen=[m for m in gekozen if len(m) == 32 and db().atleet(m)],
                                             trainingsdagen=groepsbeheer.lees_trainingsdagen(request.form, streng=False),
                                             extra_tijden=groepsbeheer.lees_extra_tijden(request.form, streng=False))
            return render_template("groep_leden.html", f=f, fout=str(e), actief_menu="groepen"), 400
        aantal = len(g.leden)
        flash(f"Groep {g.naam} aangemaakt met {aantal} {'atleten' if aantal != 1 else 'atleet'}.")
        return redirect(url_for("groep", groep_id=g.id))

    @app.get("/groep/<int:groep_id>")
    def groep(groep_id: int):
        pagina = groep_landingspagina.landingspagina(db(), groep_id)
        if pagina is None:
            abort(404)
        meldingen = get_flashed_messages()
        return render_template("groep.html", pagina=pagina, melding=meldingen[0] if meldingen else None,
                               actief_menu="groepen")

    def _gegevens(groep_id: int, fout: str | None = None, status: int = 200):
        gr = haal_groep(groep_id)
        waarden = ({"naam": request.form.get("naam", ""), "seizoen": request.form.get("seizoen", "")} if fout
                   else {"naam": gr.naam, "seizoen": gr.seizoen or ""})
        return render_template("groep_gegevens.html", groep=gr, waarden=waarden, fout=fout,
                               seizoenen=groepsbeheer.seizoenkeuzes(db()), actief_menu="groepen"), status

    @app.get("/groep/<int:groep_id>/gegevens")
    def groep_gegevens(groep_id: int):
        return _gegevens(groep_id)

    @app.post("/groep/<int:groep_id>/gegevens")
    def groep_gegevens_opslaan(groep_id: int):
        haal_groep(groep_id)
        try:
            g, veranderd = groepsbeheer.gegevens_opslaan(db(), groep_id, request.form.get("naam"),
                                                         request.form.get("seizoen"))
        except OpslagFout as e:
            return _gegevens(groep_id, fout=f"Niet opgeslagen: {e}", status=400)
        flash("Gewijzigd: " + " en ".join(veranderd) + "." if veranderd else "Niets gewijzigd.")
        return redirect(url_for("groep", groep_id=g.id))

    def _leden(groep_id: int, fout: str | None = None, status: int = 200, na_fout: bool = False):
        f = groepsbeheer.ledenformulier(
            db(), groep_id,
            gekozen=request.form.getlist("lid") if na_fout else None,
            trainingsdagen=groepsbeheer.lees_trainingsdagen(request.form, streng=False) if na_fout else None,
            extra_tijden=groepsbeheer.lees_extra_tijden(request.form, streng=False) if na_fout else None)
        if f is None:
            abort(404)
        return render_template("groep_leden.html", f=f, fout=fout, actief_menu="groepen"), status

    @app.get("/groep/<int:groep_id>/leden")
    def groep_leden(groep_id: int):
        return _leden(groep_id)

    @app.post("/groep/<int:groep_id>/leden")
    def groep_leden_opslaan(groep_id: int):
        haal_groep(groep_id)
        try:
            w = groepsbeheer.leden_opslaan(db(), groep_id, request.form.getlist("lid"),
                                           groepsbeheer.lees_trainingsdagen(request.form),
                                           groepsbeheer.lees_extra_tijden(request.form))
        except (OpslagFout, ValueError) as e:
            return _leden(groep_id, fout=f"Niet opgeslagen: {e}", status=400, na_fout=True)
        flash(w.tekst + _extra_melding(w))
        return redirect(url_for("groep", groep_id=groep_id) + "#kop-dagen")

    def _extra_melding(w) -> str:
        """Wat er na het wijzigen van een groep nog meer automatisch is gebeurd (schema's, trainingen)."""
        tekst = ""
        if w.schema_aangevuld:
            n = len(w.schema_aangevuld)
            tekst += f" Trainingsschema aangevuld voor {n} {'atleten' if n != 1 else 'atleet'}."
        if w.trainingen_erbij:
            n = w.trainingen_erbij
            tekst += f" {n} {'trainingen' if n != 1 else 'training'} ingepland."
        if w.trainingen_weg:
            n = w.trainingen_weg
            tekst += f" {n} lege {'trainingen' if n != 1 else 'training'} op vervallen dagen of tijden weggehaald."
        return tekst

    def _trainingsdagen(groep_id: int, fout: str | None = None, status: int = 200):
        f = groepsbeheer.ledenformulier(
            db(), groep_id,
            trainingsdagen=groepsbeheer.lees_trainingsdagen(request.form, streng=False) if fout else None,
            extra_tijden=groepsbeheer.lees_extra_tijden(request.form, streng=False) if fout else None)
        if f is None:
            abort(404)
        return render_template("groep_trainingsdagen.html", f=f, fout=fout, actief_menu="groepen"), status

    @app.get("/groep/<int:groep_id>/trainingsdagen")
    def groep_trainingsdagen(groep_id: int):
        return _trainingsdagen(groep_id)

    @app.post("/groep/<int:groep_id>/trainingsdagen")
    def groep_trainingsdagen_opslaan(groep_id: int):
        haal_groep(groep_id)
        try:
            w = groepsbeheer.trainingsdagen_opslaan(db(), groep_id, groepsbeheer.lees_trainingsdagen(request.form),
                                                    groepsbeheer.lees_extra_tijden(request.form))
        except (OpslagFout, ValueError) as e:
            return _trainingsdagen(groep_id, fout=f"Niet opgeslagen: {e}", status=400)
        flash(w.tekst + _extra_melding(w))
        return redirect(url_for("groep", groep_id=groep_id) + "#kop-dagen")

    # ---------------- periodisering (megacyclus en mesocycli) ----------------
    def _periodisering(groep_id: int, fout: str | None = None, status: int = 200):
        f = periodisering.formulier(db(), groep_id, ingevuld=request.form if fout else None)
        if f is None:
            abort(404)
        try:
            van = date.fromisoformat(request.args.get("van", "") + "-01") if request.args.get("van") else None
        except ValueError:
            van = None
        jaar = periodisering.jaaroverzicht(db().periodisering(groep_id), van=van,
                                           doelen=doelbeheer.markeringen(db(), groep_id))
        return render_template("groep_periodisering.html", f=f, jaar=jaar, fout=fout,
                               actief_menu="groepen"), status

    @app.get("/groep/<int:groep_id>/periodisering")
    def groep_periodisering(groep_id: int):
        return _periodisering(groep_id)

    @app.post("/groep/<int:groep_id>/periodisering")
    def groep_periodisering_opslaan(groep_id: int):
        haal_groep(groep_id)
        try:
            w = periodisering.opslaan(db(), groep_id, request.form)
        except (OpslagFout, ValueError) as e:
            return _periodisering(groep_id, fout=f"Niet opgeslagen: {e}", status=400)
        flash(w.tekst)
        return redirect(url_for("groep", groep_id=groep_id) + "#kop-periodisering")

    @app.route("/groep/<int:groep_id>/periodisering/kopieren", methods=["GET", "POST"])
    def groep_periodisering_kopieren(groep_id: int):
        k = periodisering.kopieerpagina(db(), groep_id)
        if k is None:
            abort(404)
        gekozen = [int(x) for x in request.form.getlist("groep") if x.isdigit()]
        fasen, cycli = request.form.get("fasen") == "1", request.form.get("cycli") == "1"
        fout, bevestigen = None, []
        if request.method == "POST":
            # Eerst bevestigen als er bij een gekozen groep iets wordt overschreven.
            bevestigen = [d for d in k.doelen if d.groep.id in gekozen and d.overschrijft(fasen, cycli)]
            if not bevestigen or request.form.get("bevestigd") == "1":
                try:
                    w = periodisering.kopieren(db(), groep_id, gekozen, fasen=fasen, cycli=cycli)
                except OpslagFout as e:
                    fout, bevestigen = f"Niet gekopieerd: {e}", []
                else:
                    flash(w.tekst)
                    return redirect(url_for("groep", groep_id=groep_id) + "#kop-periodisering")
        elif not k.plan.leeg:
            fasen, cycli = bool(k.plan.fasen), bool(k.plan.cycli)
        return render_template("groep_periodisering_kopieren.html", k=k, gekozen=gekozen, fasen=fasen, cycli=cycli,
                               bevestigen=bevestigen, fout=fout, actief_menu="groepen"), (400 if fout else 200)

    # ---------------- rooster (geplande trainingsinhoud) ----------------
    def _bijgewerkt(n: int) -> str:
        return f" {n} toekomstige {'trainingen' if n != 1 else 'training'} bijgewerkt." if n else ""

    def _naar_rooster(groep_id: int, rooster_id: int | None = None):
        return redirect(url_for("groep_rooster", groep_id=groep_id, **({"rooster": rooster_id} if rooster_id else {})))

    def _roosterpagina(groep_id: int, fout: str | None = None, status: int = 200):
        keuze = request.args.get("rooster", "")
        p = roosterbeheer.roosterpagina(db(), groep_id, rooster_id=int(keuze) if keuze.isdigit() else None)
        if p is None:
            abort(404)
        meldingen = get_flashed_messages()
        return render_template("groep_rooster.html", p=p, fout=fout, waarden=request.form if fout else {},
                               melding=meldingen[0] if meldingen else None, actief_menu="groepen"), status

    @app.get("/groep/<int:groep_id>/rooster")
    def groep_rooster(groep_id: int):
        return _roosterpagina(groep_id)

    @app.post("/groep/<int:groep_id>/rooster/koppelen")
    def groep_rooster_koppelen(groep_id: int):
        haal_groep(groep_id)
        try:
            k, n = roosterbeheer.koppelen(db(), groep_id, request.form)
        except (OpslagFout, ValueError) as e:
            return _roosterpagina(groep_id, fout=f"Niet gekoppeld: {e}", status=400)
        flash(f"Rooster gekoppeld vanaf {k.startdatum.strftime('%d-%m-%Y')}." + _bijgewerkt(n))
        return _naar_rooster(groep_id, k.rooster_id)

    @app.post("/groep/<int:groep_id>/rooster/ontkoppelen")
    def groep_rooster_ontkoppelen(groep_id: int):
        haal_groep(groep_id)
        try:
            n = roosterbeheer.ontkoppelen(db(), groep_id, request.form.get("start", ""))
        except OpslagFout as e:
            return _roosterpagina(groep_id, fout=f"Niet gelukt: {e}", status=400)
        flash("Koppeling weggehaald." + _bijgewerkt(n))
        return _naar_rooster(groep_id)

    @app.post("/rooster/<int:rooster_id>/wijzigen")
    def rooster_wijzigen(rooster_id: int):
        r = db().rooster(rooster_id)
        groep_id = request.form.get("groep", "")
        if r is None or not groep_id.isdigit():
            abort(404)
        try:
            r, n = roosterbeheer.rooster_wijzigen(db(), rooster_id, request.form.get("naam", ""),
                                                  request.form.get("weken", ""))
        except OpslagFout as e:
            flash(f"Niet opgeslagen: {e}")
            return _naar_rooster(int(groep_id), rooster_id)
        flash(f"Rooster '{r.naam}' opgeslagen ({r.aantal_weken} weken)." + _bijgewerkt(n))
        return _naar_rooster(int(groep_id), rooster_id)

    @app.route("/rooster/<int:rooster_id>/regel", methods=["GET", "POST"])
    def rooster_regel(rooster_id: int):
        a = request.values
        groep_id = int(a["groep"]) if a.get("groep", "").isdigit() else None
        try:
            f = roosterbeheer.regelformulier(db(), rooster_id, a.get("week"), a.get("dag"), a.get("tijd"),
                                             groep_id=groep_id)
        except OpslagFout:
            abort(404)
        if f is None or f.groep is None:
            abort(404)
        fout = None
        if request.method == "POST":
            try:
                regel, n = roosterbeheer.regel_opslaan(db(), rooster_id, f.week, f.dag, f.tijd, request.form)
            except (OpslagFout, ValueError) as e:
                fout = f"Niet opgeslagen: {e}"
                f = roosterbeheer.regelformulier(db(), rooster_id, f.week, f.dag, f.tijd, groep_id=groep_id,
                                                 ingevuld=request.form)
            else:
                flash(("Opgeslagen: " if regel else "Leeggemaakt: ") + f"week {f.week}, {f.dag}." + _bijgewerkt(n))
                return _naar_rooster(groep_id, rooster_id)
        return render_template("rooster_regel.html", f=f, fout=fout, actief_menu="groepen"), (400 if fout else 200)

    @app.route("/groep/<int:groep_id>/rooster/importeren", methods=["GET", "POST"])
    def groep_rooster_importeren(groep_id: int):
        gr = haal_groep(groep_id)
        tekst, res, fout = request.form.get("tabel", ""), None, None
        bestand = request.files.get("bestand")
        if bestand is not None and bestand.filename:
            tekst = roosterbeheer.decodeer(bestand.read(roosterbeheer.MAX_TABEL + 1))
        if request.method == "POST":
            start = request.form.get("start", "").strip()
            try:
                startdatum = date.fromisoformat(start) if start else None
            except ValueError:
                startdatum, fout = None, "Vanaf: kies een geldige datum."
            if request.form.get("stap") == "opslaan" and fout is None:
                try:
                    r, k, n = roosterbeheer.importeren(db(), groep_id, request.form, tekst)
                except (OpslagFout, ValueError) as e:
                    fout = f"Niet geïmporteerd: {e}"
                else:
                    flash(f"Rooster '{r.naam}' geïmporteerd ({len(r.regels)} regels, {r.aantal_weken} weken) "
                          f"en gekoppeld vanaf {k.startdatum.strftime('%d-%m-%Y')}." + _bijgewerkt(n))
                    return _naar_rooster(groep_id, r.id)
            res = roosterbeheer.lees_tabel(tekst, groep=gr, start=startdatum)
        return render_template("rooster_importeren.html", groep=gr, tekst=tekst, res=res, fout=fout,
                               waarden=request.form, actief_menu="groepen"), (400 if fout else 200)

    @app.get("/rooster/voorbeeld.csv")
    def rooster_voorbeeld():
        return Response("\ufeff" + roosterbeheer.VOORBEELD_CSV, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="rooster-voorbeeld.csv"'})

    @app.post("/training/<int:training_id>/rooster")
    def training_rooster_terugzetten(training_id: int):
        try:
            t = roosterbeheer.terugzetten(db(), training_id)
        except OpslagFout as e:
            if db().training(training_id) is None:
                abort(404)
            flash(f"Niet gelukt: {e}")
            return redirect(url_for("training", training_id=training_id))
        flash("De training staat weer zoals in het rooster.")
        return redirect(url_for("training", training_id=t.id))

    # ---------------- doelen ----------------
    @app.get("/groep/<int:groep_id>/doelen")
    def groep_doelen(groep_id: int):
        o = doelbeheer.doelenoverzicht(db(), groep_id)
        if o is None:
            abort(404)
        meldingen = get_flashed_messages()
        return render_template("groep_doelen.html", o=o, melding=meldingen[0] if meldingen else None,
                               actief_menu="groepen")

    def _doelformulier(*, groep_id=None, master_id=None, doel_id=None):
        """Formulier tonen (GET), aanvullen uit inschrijvingen, of opslaan (POST)."""
        post = request.method == "POST"
        f = doelbeheer.doelformulier(db(), groep_id=groep_id, master_id=master_id, doel_id=doel_id,
                                     ingevuld=request.form if post else None)
        if f is None:
            abort(404)
        fout = None
        if post and request.form.get("stap") == "aanvullen":
            f = doelbeheer.aanvullen(db(), f)
        elif post:
            try:
                d = doelbeheer.opslaan(db(), request.form, groep_id=groep_id, master_id=master_id, doel_id=doel_id)
            except (OpslagFout, ValueError) as e:
                fout = f"Niet opgeslagen: {e}"
            else:
                flash(f"Doel '{d.titel}' opgeslagen.")
                return redirect(url_for("doel", doel_id=d.id))
        actief = "atleten" if f.persoonlijk else "groepen"
        return render_template("doel_bewerken.html", f=f, fout=fout, actief_menu=actief), (400 if fout else 200)

    @app.route("/groep/<int:groep_id>/doel/nieuw", methods=["GET", "POST"])
    def groep_doel_nieuw(groep_id: int):
        haal_groep(groep_id)
        return _doelformulier(groep_id=groep_id)

    @app.route("/atleet/<master_id>/doel/nieuw", methods=["GET", "POST"])
    def atleet_doel_nieuw(master_id: str):
        haal_atleet(master_id)
        return _doelformulier(master_id=master_id)

    @app.route("/doel/<int:doel_id>/bewerken", methods=["GET", "POST"])
    def doel_bewerken(doel_id: int):
        return _doelformulier(doel_id=doel_id)

    @app.get("/doel/<int:doel_id>")
    def doel(doel_id: int):
        d = db().doel(doel_id)
        if d is None:
            abort(404)
        meldingen = get_flashed_messages()
        return render_template("doel.html", s=doelbeheer.doelstand(db(), d), melding=meldingen[0] if meldingen else None,
                               actief_menu="atleten" if d.persoonlijk else "groepen")

    @app.post("/doel/<int:doel_id>/verwijderen")
    def doel_verwijderen(doel_id: int):
        try:
            d = doelbeheer.verwijderen(db(), doel_id)
        except OpslagFout:
            abort(404)
        flash(f"Doel '{d.titel}' verwijderd.")
        if d.groep_id is not None:
            return redirect(url_for("groep_doelen", groep_id=d.groep_id))
        mid = d.regels[0].atleet_id if d.regels else None
        return redirect(url_for("atleet", master_id=mid) + "#kop-wed" if mid else url_for("atleten"))

    # ---------------- wedstrijden ----------------
    @app.get("/wedstrijden")
    def wedstrijden():
        return render_template("wedstrijden.html", o=wedstrijdenoverzicht(db()),
                               toon_afgelopen=request.args.get("afgelopen") == "1", actief_menu="wedstrijden")

    NIET_BEREIKBAAR = ("de website is niet bereikbaar of gaf iets onverwachts terug. Controleer de link en de "
                       "internetverbinding en probeer het opnieuw.")

    def _van_atleet():
        """De atleet vanaf wiens wedstrijdplanning je komt ('+ Inschrijven'): ?atleet= of het verborgen
        veld van_atleet. Dan staat die atleet al aangevinkt en ga je na opslaan terug naar zijn planning."""
        mid = request.args.get("atleet") or request.form.get("van_atleet") or ""
        return db().atleet(mid) if len(mid) == 32 else None

    def _nieuw_pagina(*, link: str = "", g=None, open_: bool = False, fout: str | None = None, status: int = 200):
        return render_template("wedstrijd_nieuw.html", link=link, g=g or wedstrijddetail.Gegevens(), open=open_,
                               fout=fout, van_atleet=_van_atleet(), actief_menu="wedstrijden"), status

    def _naar_inschrijven(w):
        a = _van_atleet()
        return redirect(url_for("wedstrijd_inschrijven", wedstrijd_id=w.id,
                                **({"atleet": a.master_id} if a else {})))

    def _gegevens_uit_formulier():
        f = request.form
        return wedstrijddetail.Gegevens(f.get("naam", ""), f.get("datum", ""), f.get("locatie", ""),
                                        f.get("link", ""), f.get("indoor") == "1")

    @app.get("/wedstrijden/nieuw")
    def wedstrijd_nieuw():
        return _nieuw_pagina()

    @app.post("/wedstrijden/nieuw")
    def wedstrijd_nieuw_opslaan():
        """Nieuwe wedstrijd: van een link (gegevens + tijdschema ophalen) of met de hand. Daarna inschrijven."""
        if request.form.get("soort") == "hand":
            g = _gegevens_uit_formulier()
            try:
                w = wedstrijddetail.gegevens_opslaan(db(), None, g)
            except OpslagFout as e:
                return _nieuw_pagina(g=g, open_=True, fout=str(e), status=400)
            flash(f"Wedstrijd {w.naam} aangemaakt. Schrijf nu de atleten in.")
            return _naar_inschrijven(w)

        link = request.form.get("link", "").strip()
        try:
            n = tijdschema_import.wedstrijd_uit_link(db(), link, indoor=request.form.get("indoor") == "1")
        except OpslagFout as e:
            return _nieuw_pagina(link=link, fout=f"Niet gelukt: {e}", status=400)
        except Exception as e:                         # netwerk, onverwachte pagina, ...
            app.logger.warning("Nieuwe wedstrijd ophalen mislukt: %s", type(e).__name__)
            return _nieuw_pagina(link=link, fout=f"Niet gelukt: {NIET_BEREIKBAAR}", status=502)
        w = n.wedstrijd
        if n.bestond:
            flash(f"Deze wedstrijd stond er al ({w.naam}); het tijdschema is bijgewerkt. {n.verslag.tekst}")
        else:
            flash(f"Wedstrijd {w.naam} ({w.datum.isoformat()}) aangemaakt. {n.verslag.tekst} "
                  "Schrijf nu de atleten in.")
        return _naar_inschrijven(w)

    def _wedstrijdpagina(wedstrijd_id: int, fout: str | None = None, status: int = 200):
        d = wedstrijddetail.wedstrijd_detail(db(), wedstrijd_id)
        if d is None:
            abort(404)
        meldingen = get_flashed_messages()
        return render_template("wedstrijd.html", d=d, alle=request.args.get("alle") == "1",
                               doelen=doelbeheer.wedstrijddoelen(db(), wedstrijd_id),
                               melding=meldingen[0] if meldingen else None, fout=fout,
                               actief_menu="wedstrijden"), status

    @app.get("/wedstrijd/<int:wedstrijd_id>")
    def wedstrijd(wedstrijd_id: int):
        return _wedstrijdpagina(wedstrijd_id)

    @app.post("/wedstrijd/<int:wedstrijd_id>/tijdschema")
    def wedstrijd_tijdschema(wedstrijd_id: int):
        """Tijdschema ophalen van atletiek.nu of Seltec (de link van de wedstrijd, of een opgegeven link)."""
        if db().wedstrijd(wedstrijd_id) is None:
            abort(404)
        link = request.form.get("link", "").strip() or None
        try:
            verslag = tijdschema_import.tijdschema_importeren(db(), wedstrijd_id, link)
        except OpslagFout as e:
            return _wedstrijdpagina(wedstrijd_id, fout=f"Tijdschema niet geïmporteerd: {e}", status=400)
        except Exception as e:                         # netwerk, onverwachte pagina, ...
            app.logger.warning("Tijdschema ophalen mislukt: %s", type(e).__name__)
            return _wedstrijdpagina(wedstrijd_id, fout=f"Tijdschema niet geïmporteerd: {NIET_BEREIKBAAR}",
                                    status=502)
        tekst = verslag.tekst
        w = db().wedstrijd(wedstrijd_id)
        if link and not w.bron_url and request.form.get("bewaar") == "1":
            g = wedstrijddetail.Gegevens.van(w)
            g.link = link
            try:                                       # de link meteen bij de wedstrijd bewaren
                wedstrijddetail.gegevens_opslaan(db(), wedstrijd_id, g)
            except OpslagFout as e:
                tekst += f" De link is niet bewaard: {e}"
        flash(tekst)
        return redirect(url_for("wedstrijd", wedstrijd_id=wedstrijd_id) + "#kop-tijdschema")

    @app.post("/wedstrijd/<int:wedstrijd_id>/uitslagen")
    def wedstrijd_uitslagen(wedstrijd_id: int):
        """Uitslag van atletiek.nu of Seltec ophalen en de prestaties van onze atleten opslaan.
        Wie alleen op naam overeenkomt, controleert de trainer eerst (pagina 'Uitslagen controleren')."""
        if db().wedstrijd(wedstrijd_id) is None:
            abort(404)
        try:
            verslag = uitslag_import.uitslagen_importeren(db(), wedstrijd_id)
        except OpslagFout as e:
            return _wedstrijdpagina(wedstrijd_id, fout=f"Uitslagen niet geïmporteerd: {e}", status=400)
        except Exception as e:                         # netwerk, onverwachte pagina, ...
            app.logger.warning("Uitslagen ophalen mislukt: %s", type(e).__name__)
            return _wedstrijdpagina(wedstrijd_id, fout=f"Uitslagen niet geïmporteerd: {NIET_BEREIKBAAR}",
                                    status=502)
        if verslag.te_controleren:
            return render_template("wedstrijd_uitslagen.html", w=db().wedstrijd(wedstrijd_id), verslag=verslag,
                                   naar_formulier=uitslag_import.naar_formulier, fout=None,
                                   actief_menu="wedstrijden")
        flash(verslag.tekst)
        return redirect(url_for("wedstrijd", wedstrijd_id=wedstrijd_id) + "#kop-uitslagen")

    @app.post("/wedstrijd/<int:wedstrijd_id>/uitslagen/bevestigen")
    def wedstrijd_uitslagen_bevestigen(wedstrijd_id: int):
        if db().wedstrijd(wedstrijd_id) is None:
            abort(404)
        try:
            lijst = uitslag_import.uit_formulier(db(), wedstrijd_id, request.form)
            keuzes = {t.sleutel: request.form.get(f"keuze-{t.sleutel}", "") for t in lijst}
            nieuw, bekend, namen = uitslag_import.uitslagen_bevestigen(db(), wedstrijd_id, keuzes, lijst)
        except OpslagFout as e:
            return _wedstrijdpagina(wedstrijd_id, fout=f"Niet opgeslagen: {e}", status=400)
        if namen:
            tekst = (f"{nieuw} prestatie{'s' if nieuw != 1 else ''} opgeslagen voor {', '.join(namen)}."
                     + (f" {bekend} stonden er al." if bekend else ""))
        else:
            tekst = "Niemand gekoppeld; er is niets extra opgeslagen."
        flash(tekst)
        return redirect(url_for("wedstrijd", wedstrijd_id=wedstrijd_id) + "#kop-uitslagen")

    def _bewerkpagina_wedstrijd(wedstrijd_id: int, g=None, fout: str | None = None, status: int = 200,
                                formulier=None):
        w = db().wedstrijd(wedstrijd_id)
        if w is None:
            abort(404)
        ts = wedstrijddetail.tijdschemaformulier(db(), wedstrijd_id, formulier)
        return render_template("wedstrijd_bewerken.html", w=w, g=g or wedstrijddetail.Gegevens.van(w), ts=ts,
                               fout=fout, actief_menu="wedstrijden"), status

    @app.get("/wedstrijd/<int:wedstrijd_id>/bewerken")
    def wedstrijd_bewerken(wedstrijd_id: int):
        return _bewerkpagina_wedstrijd(wedstrijd_id)

    @app.post("/wedstrijd/<int:wedstrijd_id>/bewerken")
    def wedstrijd_bewerken_opslaan(wedstrijd_id: int):
        if db().wedstrijd(wedstrijd_id) is None:
            abort(404)
        g = _gegevens_uit_formulier()
        try:                                           # eerst alles controleren, dan pas opslaan
            wijzigingen = wedstrijddetail.tijdschema_wijzigingen(db(), wedstrijd_id, request.form)
            w = wedstrijddetail.gegevens_opslaan(db(), wedstrijd_id, g)
        except OpslagFout as e:
            return _bewerkpagina_wedstrijd(wedstrijd_id, g, fout=f"Niet opgeslagen: {e}", status=400,
                                           formulier=request.form)
        tekst = "Gegevens opgeslagen."
        if wijzigingen and request.form.get("bijwerken") != "1":
            wedstrijddetail.tijdschema_aanpassen(db(), wijzigingen)
            n = len(wijzigingen)
            tekst += (f" {n} {'regel' if n == 1 else 'regels'} in het tijdschema aangepast: "
                      + "; ".join(x.tekst for x in wijzigingen) + ".")
        elif wijzigingen:
            tekst += " De aanpassingen in het tijdschema zijn niet bewaard: het tijdschema is opnieuw opgehaald."
        if request.form.get("bijwerken") == "1":
            if not w.bron_url:
                tekst += " Het tijdschema is niet bijgewerkt: er is geen link."
            else:
                try:
                    tekst += " " + tijdschema_import.tijdschema_importeren(db(), wedstrijd_id).tekst
                except OpslagFout as e:
                    tekst += f" Tijdschema niet bijgewerkt: {e}"
                except Exception as e:
                    app.logger.warning("Tijdschema ophalen mislukt: %s", type(e).__name__)
                    tekst += f" Tijdschema niet bijgewerkt: {NIET_BEREIKBAAR}"
        flash(tekst)
        return redirect(url_for("wedstrijd", wedstrijd_id=wedstrijd_id))

    def _inschrijfpagina(wedstrijd_id: int, regel_id: int | None, fout: str | None = None, status: int = 200,
                         onderdelen=(), gekozen=()):
        van_atleet = _van_atleet()
        if van_atleet is not None and not gekozen:
            gekozen = [van_atleet.master_id]                 # vanaf de planning van de atleet: al aangevinkt
        f = wedstrijddetail.inschrijfformulier(db(), wedstrijd_id, regel_id, onderdelen=onderdelen, gekozen=gekozen)
        if f is None:
            abort(404)
        meldingen = get_flashed_messages()
        return render_template("wedstrijd_inschrijven.html", f=f, fout=fout, van_atleet=van_atleet,
                               actief_menu="atleten" if van_atleet else "wedstrijden",
                               melding=meldingen[0] if meldingen else None), status

    def _regel_id(waarde: str | None) -> int | None:
        return int(waarde) if waarde and waarde.isdigit() else None

    @app.get("/wedstrijd/<int:wedstrijd_id>/inschrijven")
    def wedstrijd_inschrijven(wedstrijd_id: int):
        return _inschrijfpagina(wedstrijd_id, _regel_id(request.args.get("regel")))

    @app.post("/wedstrijd/<int:wedstrijd_id>/inschrijven")
    def wedstrijd_inschrijven_opslaan(wedstrijd_id: int):
        regel_id = _regel_id(request.form.get("regel"))
        atleten, onderdelen = request.form.getlist("atleet"), request.form.getlist("onderdeel")
        try:
            aantal = wedstrijddetail.inschrijven_uit_formulier(db(), wedstrijd_id, atleten, onderdelen)
        except OpslagFout as e:
            if db().wedstrijd(wedstrijd_id) is None:
                abort(404)
            return _inschrijfpagina(wedstrijd_id, regel_id, fout=str(e), status=400,
                                    onderdelen=[int(o) for o in onderdelen if o.isdigit()],
                                    gekozen=[m for m in atleten if db().atleet(m)])
        namen = [o.naam for o in db().onderdelen() if str(o.id) in onderdelen]
        wat = f"voor {', '.join(namen)}" if namen else "(onderdelen volgen nog)"
        flash(f"{aantal} {'atleet' if aantal == 1 else 'atleten'} ingeschreven {wat}.")
        van_atleet = _van_atleet()
        if van_atleet is not None:                           # terug naar de planning van de atleet
            return redirect(url_for("atleet_wedstrijden", master_id=van_atleet.master_id) + f"#w-{wedstrijd_id}")
        anker = f"#regel-{regel_id}" if regel_id else "#kop-deelnemers"
        return redirect(url_for("wedstrijd", wedstrijd_id=wedstrijd_id) + anker)

    @app.post("/wedstrijd/<int:wedstrijd_id>/afmelden")
    def wedstrijd_afmelden(wedstrijd_id: int):
        onderdeel = request.form.get("onderdeel", "")
        try:
            tekst = wedstrijddetail.afmelden(db(), wedstrijd_id, request.form.get("atleet", ""),
                                             int(onderdeel) if onderdeel.isdigit() else None)
        except OpslagFout as e:
            if db().wedstrijd(wedstrijd_id) is None:
                abort(404)
            return _wedstrijdpagina(wedstrijd_id, fout=str(e), status=400)
        flash(tekst)
        return redirect(url_for("wedstrijd", wedstrijd_id=wedstrijd_id) + "#kop-deelnemers")

    @app.get("/groep/<int:groep_id>/wedstrijden")
    def groep_wedstrijden(groep_id: int):
        gr = haal_groep(groep_id)
        return render_template(
            "wedstrijdplanning.html", planning=kalender.wedstrijdplanning(db(), gr.leden),
            kop_naam=gr.naam, terug_url=url_for("groep", groep_id=groep_id),
            weergave=request.args.get("weergave", "lijst"), actief_menu="groepen")

    @app.get("/groep/<int:groep_id>/prs")
    def groep_prs(groep_id: int):
        return render_template(
            "groep_tabel.html", tabel=groep_overzichten.prs(db(), haal_groep(groep_id)), titel="PR's", soort="prs",
            uitleg="Vet met rode streep: beste PR binnen de eigen categorie (bijv. U16M alleen met U16M).",
            leeg="Nog geen PR's. Importeer uitslagen of PR-lijsten van atletiek.nu of Seltec.", actief_menu="groepen")

    @app.get("/groep/<int:groep_id>/testen")
    def groep_testen(groep_id: int):
        return render_template(
            "groep_tabel.html", tabel=groep_overzichten.testresultaten(db(), haal_groep(groep_id)),
            titel="Testresultaten", soort="testen",
            uitleg="Het laatste resultaat per test, met de testdatum. Vet met rode streep: beste binnen de eigen categorie.",
            leeg="Nog geen testresultaten.", actief_menu="groepen")

    @app.get("/groep/<int:groep_id>/leerdoelen")
    def groep_leerdoelen(groep_id: int):
        return render_template("groep_leerdoelen.html", tabel=groep_overzichten.leerdoelen(db(), haal_groep(groep_id)),
                               actief_menu="groepen")

    @app.get("/groep/<int:groep_id>/aanwezigheid")
    def groep_aanwezigheid(groep_id: int):
        try:
            weken = min(max(int(request.args.get("weken", 12)), 1), 104)
        except ValueError:
            weken = 12
        return render_template("groep_aanwezigheid.html",
                               reg=groep_overzichten.aanwezigheid(db(), haal_groep(groep_id), weken=weken),
                               actief_menu="groepen")

    @app.get("/groep/<int:groep_id>/trainingen")
    def groep_trainingen(groep_id: int):
        return render_template("groep_trainingen.html",
                               lijst=trainingsbeheer.trainingenlijst(db(), haal_groep(groep_id)), actief_menu="groepen")

    # ---------------- trainingen ----------------
    @app.get("/training/<int:training_id>")
    def training(training_id: int):
        tp = trainingsbeheer.trainingpagina(db(), training_id)
        if tp is None:
            abort(404)
        meldingen = get_flashed_messages()
        return render_template("training.html", tp=tp, melding=meldingen[0] if meldingen else None,
                               actief_menu="groepen")

    @app.get("/training/<int:training_id>/export.<soort>")
    def training_export(training_id: int, soort: str):
        """Training als .md of .pdf om te delen. Namen bij afwijkende trainingen alleen met ?namen=1."""
        if soort not in ("md", "pdf"):
            abort(404)
        tp = trainingsbeheer.trainingpagina(db(), training_id)
        if tp is None:
            abort(404)
        e = trainingsexport.trainingsexport(tp, namen=request.args.get("namen") == "1")
        if soort == "md":
            inhoud, mime = trainingsexport.naar_markdown(e).encode("utf-8"), "text/markdown; charset=utf-8"
        else:
            try:
                inhoud, mime = trainingsexport.naar_pdf(e), "application/pdf"
            except ImportError:
                flash("PDF maken lukt niet: het pakket fpdf2 ontbreekt (pip install fpdf2). Markdown werkt wel.")
                return redirect(url_for("training", training_id=tp.training.id))
        return Response(inhoud, mimetype=mime, headers={
            "Content-Disposition": f'attachment; filename="{e.bestandsnaam}.{soort}"'})

    # ---------------- training bewerken en afwijkende trainingen ----------------
    def _bewerkpagina(f, fout: str | None = None, status: int = 200):
        if f is None:
            abort(404)
        return render_template("training_bewerken.html", f=f, fout=fout, actief_menu="groepen"), status

    def _naar_training(t, melding: str):
        flash(melding)
        hoofd_id = t.hoofdtraining_id or t.id
        anker = f"#kop-variant-{t.id}" if t.hoofdtraining_id else ""
        return redirect(url_for("training", training_id=hoofd_id) + anker)

    @app.get("/training/<int:training_id>/bewerken")
    def training_bewerken(training_id: int):
        return _bewerkpagina(trainingsbeheer.bewerkformulier(db(), training_id))

    @app.post("/training/<int:training_id>/bewerken")
    def training_bewerken_opslaan(training_id: int):
        if db().training(training_id) is None:
            abort(404)
        gekozen = request.form.getlist(trainingsbeheer.ATLEET_VELD)
        try:
            t = trainingsbeheer.training_bewerken(db(), training_id, request.form, gekozen)
        except (OpslagFout, ValueError) as e:
            return _bewerkpagina(trainingsbeheer.bewerkformulier(db(), training_id, formulier=request.form,
                                                                 gekozen=gekozen), f"Niet opgeslagen: {e}", 400)
        return _naar_training(t, "Afwijkende training opgeslagen." if t.is_afwijkend else "Training opgeslagen.")

    @app.get("/training/<int:training_id>/variant/nieuw")
    def variant_nieuw(training_id: int):
        return _bewerkpagina(trainingsbeheer.variantformulier(db(), training_id))

    @app.post("/training/<int:training_id>/variant/nieuw")
    def variant_nieuw_opslaan(training_id: int):
        if trainingsbeheer.variantformulier(db(), training_id) is None:
            abort(404)
        gekozen = request.form.getlist(trainingsbeheer.ATLEET_VELD)
        try:
            v = trainingsbeheer.variant_toevoegen(db(), training_id, request.form, gekozen)
        except (OpslagFout, ValueError) as e:
            return _bewerkpagina(trainingsbeheer.variantformulier(db(), training_id, formulier=request.form,
                                                                  gekozen=gekozen), f"Niet opgeslagen: {e}", 400)
        n = len(v.atleten)
        return _naar_training(v, f"Afwijkende training toegevoegd voor {n} {'atleten' if n != 1 else 'atleet'}.")

    @app.post("/training/<int:training_id>/verwijderen")
    def variant_verwijderen(training_id: int):
        try:
            hoofd = trainingsbeheer.variant_verwijderen(db(), training_id)
        except OpslagFout:
            abort(404)
        flash("Afwijkende training verwijderd; die atleten volgen weer de gewone training.")
        return redirect(url_for("training", training_id=hoofd.id))

    def _invullen(training_id: int, fout: str | None = None, status: int = 200):
        f = trainingsbeheer.invulformulier(db(), training_id)
        if f is None:
            abort(404)
        return render_template("training_aanwezigheid.html", f=f, fout=fout, max_reden=trainingsbeheer.MAX_REDEN,
                               actief_menu="groepen"), status

    @app.get("/training/<int:training_id>/aanwezigheid")
    def training_aanwezigheid(training_id: int):
        return _invullen(training_id)

    @app.post("/training/<int:training_id>/aanwezigheid")
    def training_aanwezigheid_opslaan(training_id: int):
        if db().training(training_id) is None:
            abort(404)
        try:
            aantal = trainingsbeheer.aanwezigheid_opslaan(db(), training_id, request.form)
        except (OpslagFout, ValueError) as e:
            return _invullen(training_id, fout=f"Niet opgeslagen: {e}", status=400)
        flash("Niets opgeslagen." if aantal == 0 else f"Aanwezigheid van {aantal} {'atleten' if aantal != 1 else 'atleet'} opgeslagen.")
        return redirect(url_for("training", training_id=training_id))

    # ---------------- trainingsschema van een atleet ----------------
    def _schema(master_id: str, fout: str | None = None, status: int = 200):
        f = schemabeheer.schemaformulier(db(), master_id)
        if f is None:
            abort(404)
        return render_template("trainingsschema.html", f=f, basis_url=url_for("atleet", master_id=master_id),
                               fout=fout, actief_menu="atleten"), status

    @app.get("/atleet/<master_id>/trainingsschema")
    def atleet_trainingsschema(master_id: str):
        return _schema(master_id)

    @app.post("/atleet/<master_id>/trainingsschema")
    def atleet_trainingsschema_opslaan(master_id: str):
        haal_atleet(master_id)
        try:
            w = schemabeheer.schema_opslaan(db(), master_id, request.form.getlist("dag"),
                                            schemabeheer.lees_trainingen(request.form))
        except (OpslagFout, ValueError) as e:
            return _schema(master_id, fout=f"Niet opgeslagen: {e}", status=400)
        flash(w.tekst)
        return redirect(url_for("atleet", master_id=master_id) + "#kop-schema")

    # ---------------- notities van een atleet ----------------
    def _notities(master_id: str, *, nieuw: bool = False, concept: dict | None = None,
                  fout: str | None = None, status: int = 200):
        np_ = notitiebeheer.notitiespagina(db(), master_id, zoek=request.args.get("zoek", ""))
        if np_ is None:
            abort(404)
        meldingen = get_flashed_messages()
        return render_template("notities.html", np=np_, basis_url=url_for("atleet", master_id=master_id),
                               nieuw=nieuw, concept=concept, fout=fout,
                               melding=meldingen[0] if meldingen else None, actief_menu="atleten"), status

    @app.get("/atleet/<master_id>/notities")
    def atleet_notities(master_id: str):
        return _notities(master_id)

    @app.get("/atleet/<master_id>/notities/nieuw")
    def atleet_notitie_nieuw(master_id: str):
        return _notities(master_id, nieuw=True)

    @app.post("/atleet/<master_id>/notities")
    def atleet_notitie_toevoegen(master_id: str):
        haal_atleet(master_id)
        concept = {"datum": request.form.get("datum", ""), "inhoud": request.form.get("inhoud", "")}
        try:
            datum = notitiebeheer.lees_datum(concept["datum"])
            n = notitiebeheer.toevoegen(db(), master_id, datum, concept["inhoud"])
        except (OpslagFout, ValueError) as e:
            return _notities(master_id, concept=concept, fout=f"Niet opgeslagen: {e}", status=400)
        flash(f"Notitie van {n.datum.strftime('%d-%m-%Y')} opgeslagen.")
        return redirect(url_for("atleet_notities", master_id=master_id) + f"#notitie-{n.id}")

    def _notitie_bewerken(master_id: str, notitie_id: int, *, concept: dict | None = None,
                          fout: str | None = None, status: int = 200):
        a = haal_atleet(master_id)
        n = notitiebeheer.haal_notitie(db(), master_id, notitie_id)
        if n is None:
            abort(404)
        return render_template("notitie_bewerken.html", a=a, n=n, basis_url=url_for("atleet", master_id=master_id),
                               vandaag=date.today(), concept=concept, fout=fout, actief_menu="atleten"), status

    @app.get("/atleet/<master_id>/notities/<int:notitie_id>")
    def atleet_notitie(master_id: str, notitie_id: int):
        return _notitie_bewerken(master_id, notitie_id)

    @app.post("/atleet/<master_id>/notities/<int:notitie_id>")
    def atleet_notitie_opslaan(master_id: str, notitie_id: int):
        haal_atleet(master_id)
        if notitiebeheer.haal_notitie(db(), master_id, notitie_id) is None:
            abort(404)
        terug = url_for("atleet_notities", master_id=master_id)
        if request.form.get("actie") == "verwijderen":
            if request.form.get("zeker") != "1":
                return _notitie_bewerken(master_id, notitie_id, fout="Vink eerst aan dat je de notitie wilt verwijderen.",
                                         status=400)
            n = notitiebeheer.verwijderen(db(), master_id, notitie_id)
            flash(f"Notitie van {n.datum.strftime('%d-%m-%Y')} verwijderd.")
            return redirect(terug)
        concept = {"datum": request.form.get("datum", ""), "inhoud": request.form.get("inhoud", "")}
        try:
            datum = notitiebeheer.lees_datum(concept["datum"])
            n = notitiebeheer.bijwerken(db(), master_id, notitie_id, datum, concept["inhoud"])
        except (OpslagFout, ValueError) as e:
            return _notitie_bewerken(master_id, notitie_id, concept=concept, fout=f"Niet opgeslagen: {e}", status=400)
        flash("Notitie opgeslagen.")
        return redirect(terug + f"#notitie-{n.id}")

    # ---------------- leerdoelen van een atleet ----------------
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

    # ---------------- importeren ----------------
    @app.get("/importeren")
    def importeren():
        return render_template("importeren.html", keuzes=importeerpagina.KEUZES, actief_menu="importeren")

    @app.get("/importeren/<any(" + ", ".join(importeerpagina.DOORSTUREN) + "):soort>")
    def importeren_soort(soort: str):
        """Oude adressen (/importeren/atleet, /importeren/wedstrijd): door naar het formulier."""
        return redirect(url_for(importeerpagina.DOORSTUREN[soort]))

    def _haal_profiel():
        """Profielpagina's van atletiek.nu ophalen (met pauze); tests zetten AVS_HAAL_PROFIEL."""
        haal = app.config.get("AVS_HAAL_PROFIEL")
        if haal is None:
            from groepen.atleten_uit_csv import STANDAARD_PAUZE, maak_haal_html
            haal = maak_haal_html(None, STANDAARD_PAUZE)
        return haal

    def _groepimport(rijen=None, keuze=None, dubbel="overslaan", *, fouten=None, fout=None, resultaat=None,
                     status: int = 200):
        groepen = sorted(db().groepen(), key=lambda g: ((g.seizoen or ""), g.naam.lower()), reverse=True)
        if keuze is None:
            gevraagd = request.args.get("groep", "")
            keuze = groep_importeren.Groepkeuze(
                "bestaand" if groepen else "nieuw",
                int(gevraagd) if gevraagd.isdigit() else None,
                seizoen=groepsbeheer.huidig_seizoen(date.today()))
        return render_template(
            "groep_importeren.html", rijen=groep_importeren.aangevuld(rijen or []), kolommen=groep_importeren.KOLOMMEN,
            fouten=fouten or {}, fout=fout, resultaat=resultaat, keuze=keuze, dubbel=dubbel,
            dubbel_keuzes=groep_importeren.DUBBEL_KEUZES, groepen=groepen,
            seizoenen=groepsbeheer.seizoenkeuzes(db()), actief_menu="importeren"), status

    @app.get("/importeren/groep")
    def importeren_groep():
        return _groepimport()

    @app.post("/importeren/groep")
    def importeren_groep_opslaan():
        f = request.form
        rijen = groep_importeren.rijen_uit_formulier(f)
        keuze = groep_importeren.lees_groepkeuze(f)
        dubbel = f.get("dubbel") if f.get("dubbel") in ("overslaan", "zelfde", "nieuw") else "overslaan"
        if f.get("actie") == "rijen":                  # 'Regels toevoegen' zonder JavaScript
            rijen = rijen + [groep_importeren.lege_rij() for _ in range(groep_importeren.RIJEN_ERBIJ)]
            return _groepimport(rijen, keuze, dubbel)
        try:
            res = groep_importeren.importeren(db(), rijen, keuze, haal_html=_haal_profiel(), dubbel=dubbel)
        except groep_importeren.TabelFout as e:
            return _groepimport(rijen, keuze, dubbel, fouten=e.fouten, fout=str(e), status=400)
        except OpslagFout as e:
            return _groepimport(rijen, keuze, dubbel, fout=str(e), status=400)
        # Mislukte regels staan weer in de tabel. Is er een groep, dan gaat een volgende poging naar díe groep.
        if res.groep is not None:
            keuze = groep_importeren.Groepkeuze("bestaand", res.groep.id, seizoen=keuze.seizoen)
        return _groepimport([r.rij for r in res.mislukt], keuze, dubbel,
                            fouten={i: r.reden for i, r in enumerate(res.mislukt)}, resultaat=res)

    # ---------------- leerlijnen (catalogus) ----------------
    @app.get("/leerlijnen")
    def leerlijnen():
        o = leerlijnoverzicht.leerlijnoverzicht(db(), onderdeel=request.args.get("onderdeel"),
                                                categorie=request.args.get("categorie"),
                                                doorlopend=request.args.get("doorlopend") == "1")
        return render_template("leerlijnen.html", o=o, bronnen=leerlijnoverzicht.BRONNEN,
                               fasen=leerlijnoverzicht.FASEN, actief_menu="leerlijnen")

    # ---------------- instellingen ----------------
    def _naamvoorbeelden() -> dict[str, list[str]]:
        """Drie verzonnen namen, gesorteerd zoals elke keuze dat doet."""
        from models import Atleet
        namen = [Atleet("Jan", "Vries", tussenvoegsel="de"), Atleet("Sanne", "Akkerman"), Atleet("Eva", "Boer")]
        return {w: [a.naam for a in sorted(namen, key=instellingen.Instellingen(naamvolgorde=w).naam_sleutel)]
                for w in instellingen.NAAM_KEUZES}

    def _instellingenpagina(inst: instellingen.Instellingen, fout: str | None = None, status: int = 200,
                            sleutel_fout: str | None = None):
        startfout = app.config["AVS_STARTFOUT"]
        return render_template("instellingen.html", inst=inst, fout=fout, meldingen=get_flashed_messages(),
                               startfout=startfout, sleutel_fout=sleutel_fout,
                               datamap=Path(app.config["AVS_MAP"] or standaard_map()),
                               sleutel_open=bool((startfout and app.config["AVS_STARTFOUT_SLEUTEL"]) or sleutel_fout),
                               eerste_dag_keuzes=instellingen.EERSTE_DAG_KEUZES,
                               thema_keuzes=instellingen.THEMA_KEUZES, tijd_keuzes=instellingen.TIJD_KEUZES,
                               naam_keuzes=instellingen.NAAM_KEUZES, naamvoorbeelden=_naamvoorbeelden(),
                               computer=instellingen.Instellingen(),        # alles 'systeem': wat de computer doet
                               tijdnotaties={w: instellingen.Instellingen(tijdnotatie=w)
                                             for w in instellingen.TIJD_KEUZES},
                               voorbeeld_tijden=("09:30", "18:00", "14:00"),
                               actief_menu="instellingen"), status

    @app.get("/instellingen")
    def instellingen_pagina():
        return _instellingenpagina(instellingen.actief())

    @app.post("/instellingen")
    def instellingen_opslaan():
        try:
            nieuw = instellingen.uit_formulier(request.form)
        except ValueError:
            return _instellingenpagina(instellingen.actief(), fout="Niet opgeslagen: kies een van de opties.",
                                       status=400)
        try:
            instellingen.opslaan(nieuw, app.config["AVS_MAP"])
        except OSError as e:
            return _instellingenpagina(nieuw, fout=f"Niet opgeslagen: het bestand kon niet worden geschreven ({e}).",
                                       status=500)
        instellingen.activeer(nieuw)
        flash("Instellingen opgeslagen.")
        return redirect(url_for("instellingen_pagina"))

    def _van_deze_app() -> bool:
        """Komt het formulier van AVS zelf? Een andere website in dezelfde browser kan ook naar
        127.0.0.1 posten; browsers sturen dan een Origin (of Referer) van die site mee."""
        herkomst = request.headers.get("Origin") or request.headers.get("Referer")
        if not herkomst:
            return True                     # geen herkomst meegestuurd (oude browser, tests)
        return urlparse(herkomst).netloc == request.host

    @app.post("/instellingen/sleutel")
    def sleutel_herstellen():
        """Herstelsleutel terugzetten (nieuwe computer, Windows opnieuw geïnstalleerd).

        De sleutel wordt nooit teruggezet in de pagina, gelogd of bewaard buiten de sleutelkluis.
        """
        if not _van_deze_app():
            abort(403)
        try:
            herstel(request.form.get("herstelsleutel", ""), app.config["AVS_MAP"])
            init_db(app.config["AVS_MAP"], app.config["AVS_HOOFD"])     # databases bijwerken met de sleutel
        except (SleutelFout, InstallatieFout) as e:
            pagina, status = _instellingenpagina(instellingen.actief(), sleutel_fout=f"Niet hersteld: {e}",
                                                 status=400)
            return pagina, status, {"Cache-Control": "no-store"}
        app.config["AVS_STARTFOUT"] = None
        app.config["AVS_AANGEVULD_OP"] = None       # trainingen klaarzetten bij de volgende pagina
        flash("Herstelsleutel teruggezet. AVS kan je gegevens weer openen.")
        r = redirect(url_for("instellingen_pagina"))
        r.headers["Cache-Control"] = "no-store"
        return r

    # ---------------- ploegen ----------------
    @app.get("/ploegen")
    def ploegen():
        meldingen = get_flashed_messages()
        return render_template("ploegen.html", regels=ploegpaginas.overzicht(db(), date.today()),
                               melding=meldingen[0] if meldingen else None, actief_menu="ploegen")

    def _ploegformulier(ingevuld=None, *, ploeg=None, fouten=None, status: int = 200):
        f = ploegpaginas.formulier(db(), date.today(), ingevuld, ploeg)
        return render_template("ploeg_gegevens.html", f=f, p=ploeg, fouten=fouten or {},
                               actief_menu="ploegen"), status

    @app.get("/ploegen/nieuw")
    def ploeg_nieuw():
        return _ploegformulier()

    @app.post("/ploegen/nieuw")
    def ploeg_nieuw_opslaan():
        try:
            p = ploegpaginas.ploeg_opslaan(db(), ploegpaginas.lees_formulier(db(), request.form))
        except ploegpaginas.InvoerFout as e:
            return _ploegformulier(request.form, fouten=e.fouten, status=400)
        except OpslagFout as e:
            return _ploegformulier(request.form, fouten={"algemeen": str(e)}, status=400)
        flash(f"Ploeg {p.naam} is aangemaakt. Kies de atleten en hun onderdelen.")
        return redirect(url_for("ploeg", ploeg_id=p.id))

    def haal_ploeg(ploeg_id: int):
        p = db().ploeg(ploeg_id)
        if p is None:
            abort(404)
        return p

    @app.get("/ploeg/<int:ploeg_id>/gegevens")
    def ploeg_gegevens(ploeg_id: int):
        return _ploegformulier(ploeg=haal_ploeg(ploeg_id))

    @app.post("/ploeg/<int:ploeg_id>/gegevens")
    def ploeg_gegevens_opslaan(ploeg_id: int):
        oud = haal_ploeg(ploeg_id)
        try:
            p = ploegpaginas.ploeg_opslaan(db(), ploegpaginas.lees_formulier(db(), request.form, oud))
        except ploegpaginas.InvoerFout as e:
            return _ploegformulier(request.form, ploeg=oud, fouten=e.fouten, status=400)
        except OpslagFout as e:
            return _ploegformulier(request.form, ploeg=oud, fouten={"algemeen": str(e)}, status=400)
        flash("De gegevens van de ploeg zijn opgeslagen.")
        return redirect(url_for("ploeg", ploeg_id=p.id))

    def _ploegpagina(ploeg_id: int, pagina=None, *, melding=None, status: int = 200):
        try:
            pg = pagina or ploegpaginas.ploegpagina(db(), ploeg_id)
        except RegelFout as e:
            p = haal_ploeg(ploeg_id)
            return render_template("fout.html", titel=p.naam,
                                   tekst=f"Het regelbestand van deze ploeg is niet te lezen: {e}"), 500
        if pg is None:
            abort(404)
        if melding is None:
            meldingen = get_flashed_messages()
            melding = meldingen[0] if meldingen else None
        return render_template("ploeg.html", pg=pg, melding=melding, actief_menu="ploegen"), status

    @app.get("/ploeg/<int:ploeg_id>")
    def ploeg(ploeg_id: int):
        return _ploegpagina(ploeg_id)

    @app.post("/ploeg/<int:ploeg_id>")
    def ploeg_opslaan(ploeg_id: int):
        haal_ploeg(ploeg_id)
        try:
            pg, wijzigingen = ploegpaginas.opstelling_opslaan(db(), ploeg_id, request.form)
        except RegelFout:
            return _ploegpagina(ploeg_id)
        except OpslagFout as e:
            pg = ploegpaginas.ploegpagina(db(), ploeg_id)
            return render_template("ploeg.html", pg=pg, fout=str(e), actief_menu="ploegen"), 400
        tekst = "Opgeslagen." + (" Nog niet alles klopt: zie de meldingen." if pg.fouten else
                                 " De opstelling voldoet aan de regels.")
        if wijzigingen.iets and pg.wedstrijd:
            tekst += (f" Wedstrijd {pg.wedstrijd.naam} bijgewerkt: {wijzigingen.ingeschreven} ingeschreven, "
                      f"{wijzigingen.afgemeld} afgemeld.")
        return _ploegpagina(ploeg_id, pg, melding=tekst)

    @app.post("/ploeg/<int:ploeg_id>/optimaliseren")
    def ploeg_optimaliseren(ploeg_id: int):
        haal_ploeg(ploeg_id)
        try:
            o = ploegpaginas.optimaliseren(db(), ploeg_id, request.form.get("strategie", ""),
                                           vastzetten=request.form.get("vastzetten") == "1",
                                           alleen_aangevinkt=request.form.get("aangevinkt") == "1")
        except KeyError:
            return render_template("ploeg.html", pg=ploegpaginas.ploegpagina(db(), ploeg_id),
                                   fout="Kies een manier om de opstelling te maken.", actief_menu="ploegen"), 400
        except OptimalisatieFout as e:
            return render_template("ploeg.html", pg=ploegpaginas.ploegpagina(db(), ploeg_id),
                                   fout=str(e), actief_menu="ploegen"), 400
        except RegelFout:
            return _ploegpagina(ploeg_id)
        tekst = f"Opstelling gemaakt met '{o.strategie}': {o.na} punten (was {o.voor})."
        if o.pagina.fouten:
            tekst += " Nog niet alles klopt: zie de meldingen."
        if o.wijzigingen.iets and o.pagina.wedstrijd:
            tekst += (f" Wedstrijd {o.pagina.wedstrijd.naam} bijgewerkt: {o.wijzigingen.ingeschreven} ingeschreven, "
                      f"{o.wijzigingen.afgemeld} afgemeld.")
        return _ploegpagina(ploeg_id, o.pagina, melding=tekst)

    @app.get("/ploeg/<int:ploeg_id>/voorkeuren")
    def ploeg_voorkeuren(ploeg_id: int):
        haal_ploeg(ploeg_id)
        try:
            vp = ploegpaginas.voorkeurpagina(db(), ploeg_id)
        except RegelFout:
            return _ploegpagina(ploeg_id)
        return render_template("ploeg_voorkeuren.html", vp=vp, actief_menu="ploegen")

    @app.post("/ploeg/<int:ploeg_id>/voorkeuren")
    def ploeg_voorkeuren_opslaan(ploeg_id: int):
        haal_ploeg(ploeg_id)
        try:
            n = ploegpaginas.voorkeuren_opslaan(db(), ploeg_id, request.form)
        except OpslagFout as e:
            return render_template("ploeg_voorkeuren.html", vp=ploegpaginas.voorkeurpagina(db(), ploeg_id),
                                   fout=f"Niet opgeslagen: {e}", actief_menu="ploegen"), 400
        except RegelFout:
            return _ploegpagina(ploeg_id)
        flash(f"Voorkeuren voor deze ploeg opgeslagen ({n} ingesteld).")
        return redirect(url_for("ploeg", ploeg_id=ploeg_id))

    def _dag(datum: str):
        try:
            return date.fromisoformat(datum)
        except ValueError:
            abort(404)

    @app.get("/ploegen/dag/<datum>")
    def ploegen_dag(datum: str):
        dag = ploegpaginas.dagpagina(db(), _dag(datum))
        return render_template("ploegen_dag.html", dag=dag, actief_menu="ploegen")

    @app.post("/ploegen/dag/<datum>")
    def ploegen_dag_maken(datum: str):
        dag = ploegpaginas.dagpagina(db(), _dag(datum))
        try:
            keuzes = ploegpaginas.lees_dagformulier(request.form, dag)
            uitkomst = ploegpaginas.dag_optimaliseren(db(), keuzes, vastzetten=request.form.get("vastzetten") == "1")
        except ploegpaginas.InvoerFout as e:
            return render_template("ploegen_dag.html", dag=dag, fouten=e.fouten,
                                   fout="Niet alles is goed ingevuld.", actief_menu="ploegen"), 400
        except (OptimalisatieFout, RegelFout) as e:
            return render_template("ploegen_dag.html", dag=ploegpaginas.dagpagina(db(), dag.datum), fout=str(e),
                                   actief_menu="ploegen"), 400
        return render_template("ploegen_dag.html", dag=ploegpaginas.dagpagina(db(), dag.datum), uitkomst=uitkomst,
                               actief_menu="ploegen")

    @app.get("/ploeg/<int:ploeg_id>/atletieknu.csv")
    def ploeg_export(ploeg_id: int):
        haal_ploeg(ploeg_id)
        try:
            e = ploegexport.atletieknu_csv(db(), ploeg_id)
        except RegelFout:
            return _ploegpagina(ploeg_id)
        if e is None:
            abort(404)
        # Persoonsgegevens: alleen als download, niet opslaan en niet cachen.
        return Response(e.inhoud, mimetype="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="{e.bestandsnaam}"', "Cache-Control": "no-store"})

    @app.post("/ploeg/<int:ploeg_id>/verwijderen")
    def ploeg_verwijderen(ploeg_id: int):
        p = haal_ploeg(ploeg_id)
        ploegpaginas.ploeg_verwijderen(db(), ploeg_id)
        flash(f"Ploeg {p.naam} is verwijderd.")
        return redirect(url_for("ploegen"))

    # ---------------- nog te bouwen ----------------
    if BINNENKORT:
        @app.get("/<any(" + ", ".join(BINNENKORT) + "):onderdeel>")
        def binnenkort(onderdeel: str):
            return render_template("binnenkort.html", titel=BINNENKORT[onderdeel], terug_url=url_for("start"),
                                   terug_naam="Start", actief_menu=onderdeel)

    @app.get("/atleet/<master_id>/<path:onderdeel>")
    def atleet_binnenkort(master_id: str, onderdeel: str):
        if onderdeel not in ATLEET_BINNENKORT:
            abort(404)
        a = haal_atleet(master_id)
        return render_template("binnenkort.html", titel=ATLEET_BINNENKORT[onderdeel],
                               terug_url=url_for("atleet", master_id=master_id), terug_naam=a.naam,
                               actief_menu="atleten")

    @app.errorhandler(InstallatieFout)
    def installatiefout(e):
        """Bijv. de sleutelkluis van Windows die halverwege niet meer bereikbaar is."""
        return render_template("fout.html", titel="AVS kan je gegevens niet openen", tekst=str(e)), 500

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
    sleutelfout = True
    try:
        if map is None:
            oude_data_overnemen()           # eenmalig: data/ naast de .exe -> %LOCALAPPDATA%\AVS\data
        init_db(map)
    except OvernameFout as e:               # dan géén init_db: die zou lege databases aanmaken
        startfout, sleutelfout = str(e), False
    except SleutelFout as e:
        startfout = str(e) if HERSTEL_UITLEG in str(e) else f"{e}\n\n{HERSTEL_UITLEG}"
    except InstallatieFout as e:
        startfout, sleutelfout = str(e), False
    app = maak_app(map=map, startfout=startfout, sleutelfout=sleutelfout)
    poort = _vrije_poort()
    adres = f"http://{HOST}:{poort}/"
    print(f"AVS draait op {adres}  (sluit dit venster om te stoppen)")
    if browser:
        threading.Timer(1.0, webbrowser.open, args=(adres,)).start()
    # Eén gebruiker op één computer: één thread is genoeg en houdt SQLCipher eenvoudig.
    app.run(host=HOST, port=poort, debug=False, threaded=False, use_reloader=False)


if __name__ == "__main__":
    start()
