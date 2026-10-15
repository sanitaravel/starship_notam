"""Short Russian title lines for Starship-related NOTAMs."""

from __future__ import annotations

import re


def extract_starship_template(notam: str) -> str | None:
    """Return a descriptive Russian-language line for Starship-related NOTAMs.

    Returns None when the NOTAM text does not match a known Starship template.
    """
    if not notam:
        return None
    text = " ".join(notam.upper().split())

    # 0. TFR ground/surface hazard area wording
    if any(keyword in text for keyword in [
        "SURFACE HAZARD OPERATIONS WI AN AREA DEFINED",
        "SURFACE HAZARD WI AN AREA DEFINED",
        "GROUND HAZARD WI AN AREA DEFINED",
    ]):
        return "GROUND HAZARD AREA"

    # 0b. High energy testing TFR (SpaceX Starship-related, no flight number)
    if "HIGH ENERGY TESTING" in text and "SPACEX" in text:
        return "ВЫСОКОЭНЕРГЕТИЧЕСКИЕ ТЕСТИРОВАНИЯ"

    # 0b-2. Space launch rehearsal TFR (SpaceX, no flight number). The real FAA
    # feed misspells "REHEARSAL" as "REHERSAL", so match both spellings. Guarded
    # by SPACEX so it only fires for SpaceX rehearsal restrictions.
    if (
        ("LAUNCH REHERSAL" in text or "LAUNCH REHEARSAL" in text)
        and "SPACEX" in text
    ):
        return "РЕПЕТИЦИЯ ЗАПУСКА SPACEX"

    # ----------------------------
    # Extract flight number
    # ----------------------------
    # Run flight extraction BEFORE the flight-free branches (0c) so a NOTAM that
    # carries a recognizable Starship flight number gets the specific, flight-
    # referencing template rather than the generic flight-free summary. Real
    # NOTAM feeds contain OCR/transcription quirks, so the patterns tolerate:
    #   * "SPACE X STARSHIP" (space inside "SPACEX")
    #   * "FTL-14" (transposed letters for the intended "FLT-14")
    flight = None

    patterns = [
        # Accept FLT and the transposed-typo FTL, with optional separators, and
        # the "SPACE X" spacing variant before STARSHIP.
        r"STARSHIP\s+F(?:LT|TL)[- ]?(\d+)",
        r"STARSHIP\s+FLIGHT[- ]?(\d+)",
        r"SPACE\s?X\s+STARSHIP\s+F(?:LT|TL)[- ]?(\d+)",
        r"SPACE\s?X\s+STARSHIP\s+FLIGHT[- ]?(\d+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            flight = m.group(1)
            break

    # 0c. Space vehicle re-entry / splashdown with NO recognizable flight number
    # (e.g. "RE-ENTRY OF SPACE VEHICLE OVER PACIFIC OCEAN WITH SPLASHDOWN").
    # Only fires when flight extraction above found nothing, so flighted
    # re-entry NOTAMs fall through to the flight-carrying template (branch 2).
    if flight is None and "RE-ENTRY" in text and (
        "SPACE VEHICLE" in text
        or "PACIFIC OCEAN" in text
        or "SPLASHDOWN" in text
    ):
        return (
            "ЗОНА ВХОДА В АТМОСФЕРУ И ПРИВОДНЕНИЯ"
        )

    if not flight:
        return None

    # ----------------------------
    # Classification
    # ----------------------------

    # 1. Airspace closure during ascent
    if any(keyword in text for keyword in [
        "ASCENT",
        "ALT RESERVATION",
        "AIRSPACE DCC",
        "STNR ALT RESERVATION"
    ]):
        return (
            f"ЗАКРЫТИЕ ВОЗДУШНЕГО ПРОСТРАНСТВА "
            f"В СВЯЗИ С ЗАПУСКОМ SPACEX STARSHIP "
            f"FLT-{flight}"
        )

    # 2. Reentry + splashdown
    if (
        ("REENTRY" in text or "RE-ENTRY" in text)
        and "SPLASHDOWN" in text
    ):
        return (
            f"ЗОНА ВХОДА В АТМОСФЕРУ И ПРИВОДНЕНИЯ "
            f"SPACEX STARSHIP FLT-{flight}"
        )

    # 3. Reentry only
    if any(keyword in text for keyword in [
        "REENTRY OF ROCKET",
        "RE-ENTRY",
        "FOR REENTRY",
        "REENTRY"
    ]):
        return (
            f"ЗОНА ВХОДА В АТМОСФЕРУ "
            f"КОСМИЧЕСКОГО КОРАБЛЯ SPACEX STARSHIP "
            f"FLT-{flight}"
        )

    # 4. Debris / launch hazard
    if any(keyword in text for keyword in [
        "DANGEROUS AREA",
        "DEBRIS RESPONSE AREA",
        "DEBRIS RESPONSE AREAS", "HAZARDOUS OPERATION",
        "FALLING DEBRIS",
        "POSSIBILITY OF FALLING DEBRIS",
        "ACFT HAZARD AREA",
        "DUE LAUNCH OF SPACEX STARSHIP",
        "DUE TO THE LAUNCH OF THE",
        "TEMPORARY DANGER AREAS",
        "TEMPORARY DANGER AREA",
        "SPACE DEBRIS",
        "DEBRIS RETURN",
        "SPACE DEBRIS RETURN",
    ]):
        return (
            f"ВОЗМОЖНОЕ ПАДЕНИЕ ОБЛОМКОВ "
            f"В РЕЗУЛЬТАТЕ ЗАПУСКА SPACEX STARSHIP "
            f"FLT-{flight}"
        )

    # 5. Ascent
    if any(keyword in text for keyword in [
        "STARSHIP ASCENT",
        "SPACEX STARSHIP ASCENT"
    ]):
        return (
            f"ЗОНА ЗАПУСКА SPACEX STARSHIP "
            f"FLT-{flight}"
        )

    # 6. Generic fallback for recognized Starship flights.
    # A flight number was extracted but no specific branch matched. Return a
    # concise flight-referencing summary line instead of None so the card shows
    # a shortened line rather than the full raw NOTAM text. Non-Starship text
    # never reaches here (it returns None earlier when no flight is found).
    return f"ЗОНА NOTAM SPACEX STARSHIP FLT-{flight}"
