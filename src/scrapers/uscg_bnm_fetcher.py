"""HTTP-based USCG Broadcast Notice to Mariners fetching.

Reads one Coast Guard GovDelivery RSS feed per topic in
:data:`core.config.USCG_BNM_TOPICS` (no key needed); each holds the topic's
last 100 bulletins with their full text. Parsing is delegated to
:func:`src.parsers.uscg_bnm_parser.parse_uscg_bnm_feed`, which keeps the
``SPACE OPERATIONS`` bulletins.

The fetcher performs no persistence and never raises: on failure it logs and
returns ``None`` so callers can tell "fetch failed" apart from "no bulletins".
"""

from src.core import config
from src.core.logging import logger
from src.parsers.uscg_bnm_parser import parse_uscg_bnm_feed
from src.scrapers.http_fetcher import HttpFetcher


class UscgBnmFetcher(HttpFetcher):
    """One GovDelivery topic feed -> its space-operations bulletins."""

    def __init__(self, topic: str):
        self.topic = topic
        self.name = f"USCG BNM feed {topic}"

    @property
    def url(self) -> str:
        return config.USCG_BNM_FEED_URL.format(topic=self.topic)

    def parse(self, text: str) -> list[dict]:
        return parse_uscg_bnm_feed(text)

    def failure(self) -> None:
        return None

    def describe(self, result: list[dict]) -> str:
        return f"{len(result)} space-operations bulletin(s)"


uscg_bnm_fetchers = [UscgBnmFetcher(topic) for topic in config.USCG_BNM_TOPICS]


if __name__ == "__main__":
    for fetcher in uscg_bnm_fetchers:
        for b in fetcher.fetch() or []:
            logger.info(f"USCG BNM: {b['notice_key']} {b['mission']}")
