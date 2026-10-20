"""Start AVS: `python src` (vanuit de repo-root) of de gebouwde .exe.

Zet de databases klaar, start de lokale webserver en opent de browser.

    AVS.exe                   starten en de browser openen
    AVS.exe --geen-browser    starten zonder de browser te openen (zelf naar het adres gaan)
    AVS.exe --zelftest        controleren of alles in deze AVS werkt, dan stoppen (0 = goed)
"""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="AVS", description="Atleet Volg Systeem.")
    parser.add_argument("--geen-browser", action="store_true",
                        help="de browser niet zelf openen; het adres staat in dit venster")
    parser.add_argument("--zelftest", action="store_true",
                        help="controleer of alles in deze AVS werkt (raakt je gegevens niet aan) en stop")
    parser.add_argument("--details", action="store_true", help="bij --zelftest: volledige foutmeldingen")
    args = parser.parse_args(argv)

    if args.zelftest:
        from zelftest import zelftest
        return zelftest(details=args.details)

    from ui.app import start
    start(browser=not args.geen_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
