"""HTTP-based COMPASS Master Slide Deck file-list fetching.

The COMPASS page ``vpublic_anspdetail.jsp?view=3`` renders its file grid from
a public JSON endpoint, so a plain HTTP GET of that endpoint is enough (no
browser needed). Parsing is delegated to
:func:`starship_notam.parsers.compass_parser.parse_compass_file_list`.

The fetcher performs no persistence and never raises: on failure it logs and
returns ``None`` so callers can tell "fetch failed" apart from "no files".
"""

import requests

from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.parsers.compass_parser import parse_compass_file_list


def fetch_compass_files() -> list[dict] | None:
    """Fetch the Master Slide Deck file list.

    Returns
    -------
    list[dict] or None
        The parsed file records (newest first, see
        :func:`parse_compass_file_list`), or ``None`` when the request failed.
    """
    url = config.COMPASS_SLIDE_LIST_URL
    logger.info("Fetching COMPASS file list from %s", url)
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to fetch COMPASS file list from %s", url)
        return None

    files = parse_compass_file_list(response.text)
    logger.info("Parsed %d files from the COMPASS file list", len(files))
    return files


if __name__ == "__main__":
    for f in fetch_compass_files() or []:
        logger.info(f"COMPASS file: {f}")
