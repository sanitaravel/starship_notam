"""FAA advisory HTML parsing.

Extracts planned launch/reentry information from the FAA System Operations
advisory page HTML. This module is a pure-function parser: it accepts an HTML
string and returns structured data without performing any network, database,
or filesystem operations.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup


def parse_faa_advisory_html(html: str) -> list[dict]:
    """Parse FAA advisory HTML and return a list of launch dictionaries.

    Parameters
    ----------
    html : str
        Raw HTML content from the FAA advisory page.

    Returns
    -------
    list[dict]
        Each dict contains keys: ``mission`` (str), ``primary_window``
        (str | None), and ``backup_window`` (str | None).
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")

    # Extract the launch block from either advisory layout.
    launch_block_patterns = [
        r"PLANNED LAUNCH/REENTRY:\s*(.*?)(?:FLIGHT CHECK\(S\):|VIP MOVEMENT\(S\):|$)",
        r"AIRSPACE FLOW PROGRAM\(S\) PLANNED:\s*(?:NONE\s*)?(.*?)(?:FLIGHT CHECK\(S\):|VIP MOVEMENT\(S\):|$)",
    ]

    block: str | None = None
    for pattern in launch_block_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            block = match.group(1)
            break

    if not block:
        return []

    # Parse individual launches from the block text.
    launches: list[dict] = []
    current: dict | None = None
    launch_started = False

    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue

        if line == "NONE":
            continue

        if line.startswith("PRIMARY:"):
            if not current:
                continue
            current["primary_window"] = line.replace("PRIMARY:", "").strip()

        elif line.startswith("BACKUP:"):
            if not current:
                continue
            current["backup_window"] = line.replace("BACKUP:", "").strip()

        else:
            if not launch_started and "," not in line:
                continue

            # New launch entry
            if current:
                launches.append(current)

            current = {
                "mission": line,
                "primary_window": None,
                "backup_window": None,
            }
            launch_started = True

    if current:
        launches.append(current)

    return launches
