"""Start AVS: `python src` (vanuit de repo-root) of de gebouwde .exe.

Zet de databases klaar, start de lokale webserver en opent de browser. AVS stopt vanzelf
als het laatste AVS-tabblad dicht is, of met de knop 'AVS afsluiten' (ui/levensduur.py).

    AVS.exe                   starten en de browser openen
    AVS.exe --geen-browser    starten zonder de browser te openen (zelf naar het adres gaan)
    AVS.exe --zelftest        controleren of alles in deze AVS werkt, dan stoppen (0 = goed)

De .exe heeft geen eigen venster (PyInstaller --windowed): er is dan geen console om naar te
schrijven. Gestart vanuit een opdrachtprompt (zoals build.py de zelftest doet) schrijft AVS
naar dat venster; bij een dubbelklik gaat tekst nergens heen en verschijnt een onverwachte
fout als Windows-melding.
"""

import argparse
import os
import sys
import traceback


def _console_koppelen() -> bool:
    """Zonder eigen console (--windowed): schrijf naar het venster waaruit AVS is gestart, als dat er is.

    Geeft True als er nu een console is om naar te schrijven.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):            # ATTACH_PARENT_PROCESS
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
                sys.stderr = sys.stdout
                return True
        except (OSError, AttributeError):
            pass
    leeg = open(os.devnull, "w", encoding="utf-8")                  # print() e.d. mogen niet falen
    sys.stdout = sys.stdout or leeg
    sys.stderr = sys.stderr or leeg
    return False


def _melding(tekst: str) -> None:
    """Een fout laten zien: in de console als die er is, anders als Windows-melding."""
    print(tekst, file=sys.stderr)
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, tekst, "AVS - Atleet Volg Systeem", 0x10)   # MB_ICONERROR
        except (OSError, AttributeError):
            pass


def main(argv: list[str] | None = None) -> int:
    _console_koppelen()
    parser = argparse.ArgumentParser(prog="AVS", description="Atleet Volg Systeem.")
    parser.add_argument("--geen-browser", action="store_true",
                        help="de browser niet zelf openen; ga zelf naar http://127.0.0.1:5050/")
    parser.add_argument("--zelftest", action="store_true",
                        help="controleer of alles in deze AVS werkt (raakt je gegevens niet aan) en stop")
    parser.add_argument("--details", action="store_true", help="bij --zelftest: volledige foutmeldingen")
    args = parser.parse_args(argv)

    if args.zelftest:
        from zelftest import zelftest
        return zelftest(details=args.details)

    try:
        from ui.app import start
        start(browser=not args.geen_browser)
    except Exception as e:                                          # noqa: BLE001 - laatste vangnet
        traceback.print_exc()
        _melding(f"AVS kon niet starten of is onverwacht gestopt:\n\n{type(e).__name__}: {e}\n\n"
                 "Je gegevens zijn niet aangeraakt. Probeer het opnieuw; blijft dit gebeuren, "
                 "start dan 'AVS.exe --zelftest' vanuit een opdrachtprompt.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
