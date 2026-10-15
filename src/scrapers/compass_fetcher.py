"""HTTP-based COMPASS Master Slide Deck file-list fetching.

The COMPASS page ``vpublic_anspdetail.jsp?view=3`` renders its file grid from
a public JSON endpoint, so a plain HTTP GET of that endpoint is enough (no
browser needed). Parsing is delegated to
:func:`src.parsers.compass_parser.parse_compass_file_list`.

The fetcher performs no persistence and never raises: on failure it logs and
returns ``None`` so callers can tell "fetch failed" apart from "no files".
"""

from src.core import config
from src.core.logging import logger
from src.parsers.compass_parser import parse_compass_file_list
from src.scrapers.http_fetcher import HttpFetcher


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


compass_files_fetcher = CompassFileListFetcher()


if __name__ == "__main__":
    for f in compass_files_fetcher.fetch() or []:
        logger.info(f"COMPASS file: {f}")
