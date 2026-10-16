"""Klein, veilig stukje markdown voor trainingsteksten (warming-up, kern, ...).

Bewust beperkt en zonder extra pakket. Ondersteund:

    # Kopje / ## Kopje / ### Kopje
    - punt   of   * punt          (lijstje)
    1. stap                        (genummerd lijstje)
    **vet**, *schuin*, _schuin_
    lege regel = nieuwe alinea; enkele regelovergang blijft een regelovergang

Alle tekst wordt EERST ge-escaped, dus HTML in een notitie wordt nooit
uitgevoerd. Gebruik in een template: {{ training.kern_a | markdown }}
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

_KOP = re.compile(r"^(#{1,3})\s+(.*)$")
_PUNT = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMMER = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_VET = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_SCHUIN = re.compile(r"(?<![\w*])[*_](?=\S)(.+?)(?<=\S)[*_](?![\w*])")


def _regel(tekst: str) -> str:
    """Opmaak binnen één regel. `tekst` is al ge-escaped."""
    tekst = _VET.sub(r"<strong>\1</strong>", tekst)
    return _SCHUIN.sub(r"<em>\1</em>", tekst)


def naar_html(tekst: str | None) -> Markup:
    """Markdown-tekst -> veilige HTML (Markup). None of leeg -> lege Markup."""
    if not tekst or not str(tekst).strip():
        return Markup("")
    uit: list[str] = []
    lijst: str | None = None          # 'ul' of 'ol' als er een lijst open staat
    alinea: list[str] = []

    def sluit_alinea() -> None:
        if alinea:
            uit.append("<p>" + "<br>".join(alinea) + "</p>")
            alinea.clear()

    def sluit_lijst() -> None:
        nonlocal lijst
        if lijst:
            uit.append(f"</{lijst}>")
            lijst = None

    for ruw in str(tekst).replace("\r\n", "\n").split("\n"):
        regel = str(escape(ruw.rstrip()))
        if not regel.strip():
            sluit_alinea()
            sluit_lijst()
            continue
        if m := _KOP.match(regel):
            sluit_alinea()
            sluit_lijst()
            niveau = len(m.group(1)) + 2              # '#' -> h3: de pagina heeft zelf h1/h2
            uit.append(f"<h{niveau}>{_regel(m.group(2))}</h{niveau}>")
            continue
        soort, m = ("ul", _PUNT.match(regel)) if _PUNT.match(regel) else ("ol", _NUMMER.match(regel))
        if m:
            sluit_alinea()
            if lijst != soort:
                sluit_lijst()
                uit.append(f"<{soort}>")
                lijst = soort
            uit.append(f"<li>{_regel(m.group(1))}</li>")
            continue
        sluit_lijst()
        alinea.append(_regel(regel))
    sluit_alinea()
    sluit_lijst()
    return Markup("\n".join(uit))
