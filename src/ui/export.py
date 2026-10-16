"""Een training exporteren om te delen: als markdown (.md) of als PDF.

Bevat de training van één dag: groep, datum, begintijd, onderwerp, warming-up,
kern A, kern B, cooling-down, notities en de afwijkende trainingen. Geen
aanwezigheid. Namen van atleten bij een afwijkende training staan er alleen in
als de trainer daarvoor kiest (`namen=True`); anders alleen het aantal. Een
gedeeld bestand staat buiten de versleutelde database, en een naam naast
bijvoorbeeld 'Revalidatie' zegt iets over een blessure.

PDF via fpdf2 (pip install fpdf2): puur Python, werkt ook in de .exe.
Gebruik vanuit de UI: /training/<id>/export.md en /training/<id>/export.pdf (?namen=1).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from groepen.trainingen import TrainingPagina

MAANDEN_LANG = ("januari", "februari", "maart", "april", "mei", "juni", "juli",
                "augustus", "september", "oktober", "november", "december")
DAGEN_LANG = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")
_KOP = re.compile(r"^(#{1,3})(\s+.*)$")


@dataclass
class Deel:
    """De gewone training of één afwijkende training."""
    kop: str                                   # 'Training' of 'Afwijkende training: Revalidatie'
    onderdelen: list[tuple[str, str]]          # (titel, markdown-tekst), notities als laatste
    voor: str | None = None                    # 'Voor Noor Vos' of 'Voor 2 atleten' (alleen afwijkend)


@dataclass
class Trainingsexport:
    titel: str                                 # onderwerp of 'Training'
    groep: str
    datum: str                                 # 'dinsdag 20 oktober 2026'
    starttijd: str | None
    periode: str | None
    delen: list[Deel] = field(default_factory=list)
    bestandsnaam: str = "training"             # zonder extensie

    @property
    def regel(self) -> str:
        """'U16 selectie · dinsdag 20 oktober 2026 · 18:30'."""
        return " · ".join(x for x in (self.groep, self.datum, self.starttijd) if x)


def _slug(tekst: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", tekst).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "groep"


def _onderdelen(t) -> list[tuple[str, str]]:
    return [*t.onderdelen, *((("Notities", t.notities),) if t.notities else ())]


def trainingsexport(tp: TrainingPagina, *, namen: bool = False) -> Trainingsexport:
    t = tp.training
    d = t.datum
    uit = Trainingsexport(
        titel=t.onderwerp or "Training", groep=tp.groep.naam,
        datum=f"{DAGEN_LANG[d.weekday()]} {d.day} {MAANDEN_LANG[d.month - 1]} {d.year}",
        starttijd=tp.starttijd, periode=tp.periode.naam if tp.periode else None,
        bestandsnaam=f"training-{d.isoformat()}-{_slug(tp.groep.naam)}")
    uit.delen.append(Deel("Training", _onderdelen(t)))
    for v, atleten in tp.varianten:
        if namen:
            voor = "Voor " + ", ".join(a.naam for a in atleten)
        else:
            n = len(atleten)
            voor = f"Voor {n} {'atleet' if n == 1 else 'atleten'}"
        uit.delen.append(Deel("Afwijkende training" + (f": {v.onderwerp}" if v.onderwerp else ""),
                              _onderdelen(v), voor))
    return uit


# ---------------- markdown ----------------
def _verlaag_koppen(tekst: str, extra: int) -> str:
    """Kopjes in een trainingstekst ('# Starts') onder de kop van het onderdeel zetten."""
    return "\n".join(_KOP.sub(lambda m: "#" * min(len(m.group(1)) + extra, 6) + m.group(2), r)
                     for r in tekst.replace("\r\n", "\n").split("\n"))


def naar_markdown(e: Trainingsexport) -> str:
    regels = [f"# {e.titel}", "", f"**{e.regel}**"]
    if e.periode:
        regels += ["", f"Periode: {e.periode}"]
    for i, deel in enumerate(e.delen):
        niveau = 2 if i == 0 else 3                       # onderdelen van de gewone training: ##
        if i > 0:
            regels += ["", "---", "", f"## {deel.kop}"]
            if deel.voor:
                regels += ["", f"*{deel.voor}*"]
        if not deel.onderdelen:
            regels += ["", "*Nog niet ingevuld.*"]
        for titel, tekst in deel.onderdelen:
            regels += ["", f"{'#' * niveau} {titel}", "", _verlaag_koppen(tekst.strip(), niveau)]
    return "\n".join(regels) + "\n"


# ---------------- PDF ----------------
ROOD = (192, 0, 0)
GRIJS = (90, 90, 90)


def _veilig(tekst: str) -> str:
    """De standaardletters van een PDF kennen alleen Windows-1252; de rest (bijv. emoji) valt weg."""
    return tekst.encode("cp1252", "ignore").decode("cp1252")


def naar_pdf(e: Trainingsexport) -> bytes:
    from fpdf import FPDF, TextStyle
    from ui.markdown import naar_html

    kopjes = {h: TextStyle(font_family="Helvetica", font_style="B", font_size_pt=10.5, color=(20, 20, 20),
                           t_margin=2, b_margin=0) for h in ("h3", "h4", "h5")}

    pdf = FPDF(format="A4")
    pdf.core_fonts_encoding = "windows-1252"
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_title(_veilig(f"{e.titel} - {e.groep} - {e.datum}"))
    pdf.set_creator("Atleet Volg Systeem")
    pdf.alias_nb_pages()

    def voet():
        pdf.set_y(-12)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GRIJS)
        pdf.cell(0, 5, _veilig(f"Atleet Volg Systeem · {e.groep} · {e.datum}"), align="L")
        pdf.set_x(-18 - 20)
        pdf.cell(20, 5, f"{pdf.page_no()}/{{nb}}", align="R")
    pdf.footer = voet
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 9, _veilig(e.titel), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*ROOD)
    pdf.multi_cell(0, 6, _veilig(e.regel), new_x="LMARGIN", new_y="NEXT")
    if e.periode:
        pdf.set_text_color(*GRIJS)
        pdf.multi_cell(0, 6, _veilig(f"Periode: {e.periode}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*ROOD)
    pdf.set_line_width(.6)
    pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
    pdf.ln(5)

    for i, deel in enumerate(e.delen):
        if i > 0:
            pdf.ln(3)
            if pdf.get_y() > pdf.h - 60:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(20, 20, 20)
            pdf.multi_cell(0, 7, _veilig(deel.kop), new_x="LMARGIN", new_y="NEXT")
            if deel.voor:
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(*ROOD)
                pdf.multi_cell(0, 5, _veilig(deel.voor), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        if not deel.onderdelen:
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(*GRIJS)
            pdf.multi_cell(0, 6, "Nog niet ingevuld.", new_x="LMARGIN", new_y="NEXT")
        for titel, tekst in deel.onderdelen:
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(*ROOD)
            pdf.multi_cell(0, 6, _veilig(titel.upper()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(20, 20, 20)
            pdf.set_font("Helvetica", "", 10.5)
            pdf.write_html(_veilig(str(naar_html(tekst))), li_prefix_color=ROOD, ul_bullet_char="\u2022",
                           tag_styles=kopjes)
            pdf.ln(2)
    return bytes(pdf.output())
