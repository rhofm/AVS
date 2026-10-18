"""De instellingen van de computer zelf uitlezen: eerste dag van de week en 12/24-uursklok.

Windows (waar de .exe draait): uit het register, `HKEY_CURRENT_USER\\Control Panel\\International`
— dat zijn de keuzes onder Instellingen > Tijd en taal > Taal en regio > Regionale notatie.
    iFirstDayOfWeek  '0' = maandag … '6' = zondag
    sShortTime       korte tijdnotatie, bijv. 'HH:mm' (24-uurs) of 'h:mm tt' (12-uurs)

Elders (ontwikkelen op Mac/Linux) of als het lezen mislukt: de Nederlandse
standaard (maandag, 24-uurs). Wordt elke keer opnieuw gelezen, zodat een
wijziging in Windows meteen meetelt zonder de app te herstarten.
"""

from __future__ import annotations

import sys

STANDAARD_EERSTE_WEEKDAG = 0          # maandag
STANDAARD_TIJD_24 = True

_SLEUTEL = r"Control Panel\International"


def _register(naam: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SLEUTEL) as k:
            waarde, _ = winreg.QueryValueEx(k, naam)
        return str(waarde)
    except OSError:
        return None


def eerste_weekdag() -> int:
    """0 = maandag … 6 = zondag."""
    waarde = _register("iFirstDayOfWeek")
    if waarde is not None and waarde.strip().isdigit() and 0 <= int(waarde) <= 6:
        return int(waarde)
    return STANDAARD_EERSTE_WEEKDAG


def tijd_24() -> bool:
    """True als de computer de 24-uursklok gebruikt."""
    notatie = _register("sShortTime")
    if notatie:
        if "H" in notatie:
            return True
        if "h" in notatie:
            return False
    i_time = _register("iTime")                  # ouder veld: '1' = 24-uurs, '0' = 12-uurs
    if i_time in ("0", "1"):
        return i_time == "1"
    return STANDAARD_TIJD_24
