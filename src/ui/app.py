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

from flask import (Flask, Response, abort, flash, g, get_flashed_messages, redirect, render_template, request,
                   url_for)

from atleten import beheer, landingspagina
from atleten import aanpassen as atleetbeheer
from atleten import nieuw as nieuwe_atleten
from atleten import notities as notitiebeheer
from atleten.overzicht import atletenoverzicht
from atleten import trainingsschema as schemabeheer
from atleten.aanwezigheid import aanwezigheid
from db.init_db import SleutelFout, init_db
from db.queries import Opslag, OpslagFout
from groepen import groep as groepsbeheer
from groepen.groepenoverzicht import GEEN_SEIZOEN, groepenoverzicht
from groepen import landingspagina as groep_landingspagina
from groepen import overzichten as groep_overzichten
from groepen import trainingen as trainingsbeheer
from leerlijnen import voortgang
from ui import export as trainingsexport
from ui import startpagina
from ui.opmaak import registreer_filters
from wedstrijden import kalender

HOST = "127.0.0.1"
VOORKEUR_POORT = 5050

#: Menu-items en losse links die nog geen eigen pagina hebben: (pad, titel).
BINNENKORT = {
    "wedstrijden": "Wedstrijden",
    "ploegen": "Ploegen",
    "leerlijnen": "Leerlijnen",
    "importeren": "Importeren",
    "instellingen": "Instellingen",
}
ATLEET_BINNENKORT = {
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

    @app.before_request
    def trainingen_klaarzetten():
        """Eén keer per dag (bij de eerste pagina): trainingen aanmaken voor de vaste trainingsdagen
        van alle groepen, tot een paar weken vooruit. Zie groepen.trainingen.trainingen_aanvullen()."""
        if request.endpoint == "static" or app.config.get("AVS_AANGEVULD_OP") == date.today():
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
        meldingen = get_flashed_messages()
        return render_template("atleet.html", pagina=pagina, fases=landingspagina.FASES,
                               melding=meldingen[0] if meldingen else None, actief_menu="atleten")

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

    # ---------------- nog te bouwen ----------------
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
