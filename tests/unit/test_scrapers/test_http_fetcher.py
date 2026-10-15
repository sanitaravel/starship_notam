"""HTTP fetchers share one fetch flow; failures return each source's own value."""

from __future__ import annotations

import pytest
import requests

from src.core import config
from src.scrapers import http_fetcher
from src.scrapers.compass_fetcher import compass_files_fetcher
from src.scrapers.faa_fetcher import FAA_ADVISORY_URL, faa_advisory_fetcher
from src.scrapers.federal_register_fetcher import federal_register_documents_fetcher
from src.scrapers.starbase_fetcher import starbase_status_fetcher


class FakeResponse:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class EchoFetcher(http_fetcher.HttpFetcher):
    name = "echo"
    url = "https://example.test/echo"

    def parse(self, text):
        return text.split(",")

    def failure(self):
        return []


@pytest.fixture
def get(monkeypatch):
    """Replace requests.get; record calls; answer with ``get.response``."""

    class Recorder:
        response = FakeResponse()
        calls: list = []

        def __call__(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

    recorder = Recorder()
    recorder.calls = []
    monkeypatch.setattr(http_fetcher.requests, "get", recorder)
    return recorder


def test_successful_response_is_parsed(get):
    get.response = FakeResponse("a,b")

    assert EchoFetcher().fetch() == ["a", "b"]
    assert get.calls == [
        ("https://example.test/echo", {"params": None, "headers": None, "timeout": 30})
    ]


def test_network_error_returns_failure_value(get):
    get.response = requests.ConnectionError("down")

    assert EchoFetcher().fetch() == []


def test_http_error_status_is_a_failure_not_parsed(get):
    get.response = FakeResponse("<html>Service Unavailable</html>", status=503)

    assert EchoFetcher().fetch() == []


@pytest.mark.parametrize(
    "fetch, expected",
    [
        (faa_advisory_fetcher.fetch, []),
        (starbase_status_fetcher.fetch, {"beach": None, "road_delays": []}),
        (compass_files_fetcher.fetch, None),
        (federal_register_documents_fetcher.fetch, None),
    ],
    ids=["faa", "starbase", "compass", "federal_register"],
)
def test_each_source_keeps_its_failure_value(get, fetch, expected):
    get.response = FakeResponse(status=500)

    assert fetch() == expected


def test_failure_values_are_fresh_objects(get):
    get.response = FakeResponse(status=500)

    first = starbase_status_fetcher.fetch()
    first["road_delays"].append("mutated")

    assert starbase_status_fetcher.fetch() == {"beach": None, "road_delays": []}


def test_sources_send_their_own_request_options(get):
    get.response = requests.ConnectionError("down")

    faa_advisory_fetcher.fetch()
    federal_register_documents_fetcher.fetch()

    (faa_url, faa_kwargs), (fr_url, fr_kwargs) = get.calls
    assert faa_url == FAA_ADVISORY_URL
    assert faa_kwargs["params"] is None and faa_kwargs["headers"] is None
    assert fr_url == config.FEDERAL_REGISTER_API_URL
    assert fr_kwargs["params"] == config.FEDERAL_REGISTER_PARAMS
    assert fr_kwargs["headers"] == {"User-Agent": "Mozilla/5.0"}


def test_config_url_is_read_at_fetch_time(get, monkeypatch):
    monkeypatch.setattr(config, "COMPASS_SLIDE_LIST_URL", "https://example.test/compass")
    get.response = requests.ConnectionError("down")

    compass_files_fetcher.fetch()

    assert get.calls[0][0] == "https://example.test/compass"
