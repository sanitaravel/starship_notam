"""HTTP-based COMPASS Master Slide Deck file-list fetching.

The COMPASS page ``vpublic_anspdetail.jsp?view=3`` renders its file grid from
a public JSON endpoint, so a plain HTTP GET of that endpoint is enough (no
browser needed). Parsing is delegated to
:func:`starship_notam.parsers.compass_parser.parse_compass_file_list`.

The fetcher performs no persistence and never raises: on failure it logs and
returns ``None`` so callers can tell "fetch failed" apart from "no files".
"""

from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.parsers.compass_parser import parse_compass_file_list
from starship_notam.scrapers.http_fetcher import HttpFetcher


class CompassFileListFetcher(HttpFetcher):
    """COMPASS public slide-list endpoint -> Master Slide Deck files."""

    name = "COMPASS file list"
    headers = {"User-Agent": "Mozilla/5.0"}

    @property
    def url(self) -> str:
        return config.COMPASS_SLIDE_LIST_URL

    def parse(self, text: str) -> list[dict]:
        return parse_compass_file_list(text)

    def failure(self) -> None:
        return None

    def describe(self, result: list[dict]) -> str:
        return f"{len(result)} file(s)"


def fetch_compass_files() -> list[dict] | None:
    """Fetch the Master Slide Deck file list.

    Returns
    -------
    list[dict] or None
        The parsed file records (newest first, see
        :func:`parse_compass_file_list`), or ``None`` when the request failed.
    """
    return CompassFileListFetcher().fetch()


if __name__ == "__main__":
    for f in fetch_compass_files() or []:
        logger.info(f"COMPASS file: {f}")
