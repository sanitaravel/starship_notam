"""The NOTAM, FAA DRS and FCC ELS scrapers drive one HTTP session each."""

from __future__ import annotations

import json

import pytest
import requests

from src.core import config
from src.scrapers import faa_license_fetcher, fcc_els_fetcher, notam_scraper


class FakeResponse:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """Answers each request from ``handler(session, method, url, kwargs)``."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list = []
        self.cookies: dict = {}
        self.headers: dict = {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def get(self, url, **kwargs):
        return self._answer("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, kwargs)

    def _answer(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        response = self.handler(self, method, url, kwargs)
        if isinstance(response, Exception):
            raise response
        return response


def _sessions(monkeypatch, target, attr, handler):
    """Make ``target.attr`` build FakeSessions; return the list of them."""
    sessions: list[FakeSession] = []

    def make(*args, **kwargs):
        sessions.append(FakeSession(handler))
        return sessions[-1]

    monkeypatch.setattr(target, attr, make)
    return sessions


# --- NOTAM search -------------------------------------------------------


def _notam_page(numbers, total):
    return FakeResponse(json.dumps({
        "notamList": [{"notamNumber": n, "icaoMessage": f"{n} NOTAMN"} for n in numbers],
        "totalNotamCount": total,
        "error": "",
    }))


def test_notam_search_follows_pages_by_offset(monkeypatch):
    pages = {"0": ["A1/26", "A2/26"], "2": ["A3/26"]}

    def handler(session, method, url, kwargs):
        return _notam_page(pages[kwargs["data"]["offset"]], total=3)

    sessions = _sessions(monkeypatch, notam_scraper, "_session", handler)

    rows = notam_scraper.search_notams("starship")

    assert [r["number"] for r in rows] == ["A1/26", "A2/26", "A3/26"]
    assert [c[2]["data"]["offset"] for c in sessions[0].calls] == ["0", "2"]
    assert sessions[0].calls[0][2]["data"]["freeFormText"] == "starship"
    assert sessions[0].closed


def test_notam_search_stops_on_an_empty_page(monkeypatch):
    sessions = _sessions(
        monkeypatch, notam_scraper, "_session", lambda *a: _notam_page([], total=5)
    )

    assert notam_scraper.search_notams("starship") == []
    assert len(sessions[0].calls) == 1


def test_notam_search_raises_on_a_blocked_request(monkeypatch):
    _sessions(
        monkeypatch, notam_scraper, "_session",
        lambda *a: FakeResponse("Access Denied", status=403),
    )

    with pytest.raises(requests.HTTPError):
        notam_scraper.search_notams("starship")


def test_many_keywords_share_one_session_and_survive_a_failure(monkeypatch):
    def handler(session, method, url, kwargs):
        keyword = kwargs["data"]["freeFormText"]
        if keyword == "bad":
            return FakeResponse("Access Denied", status=403)
        return _notam_page([keyword], total=1)

    sessions = _sessions(monkeypatch, notam_scraper, "_session", handler)

    results = notam_scraper.search_notams_many(["a", "bad", "c"])

    assert {k: [r["number"] for r in v] for k, v in results.items()} == {
        "a": ["a"], "bad": [], "c": ["c"],
    }
    assert len(sessions) == 1 and sessions[0].closed


# --- FAA DRS license ----------------------------------------------------

SUMMARY = {"docUniqueId": "DRSDOCID1", "docNumber": "VOL 23-129", "metadatas": []}


def _drs(set_cookies=True, summary_status=200):
    def handler(session, method, url, kwargs):
        if url == config.FAA_LICENSE_GUEST_LOGIN_URL:
            if set_cookies:
                session.cookies.update({"jwt": "token", "user": "G"})
            return FakeResponse(status=302)
        return FakeResponse(json.dumps(SUMMARY), status=summary_status)

    return handler


def _drs_sessions(monkeypatch, handler):
    return _sessions(monkeypatch, faa_license_fetcher.requests, "Session", handler)


def test_license_summary_is_requested_with_the_guest_token(monkeypatch):
    sessions = _drs_sessions(monkeypatch, _drs())

    record = faa_license_fetcher.fetch_faa_license()

    assert record["doc_number"] == "VOL 23-129"
    (_, login_url, login), (_, summary_url, summary) = sessions[0].calls
    assert login_url == config.FAA_LICENSE_GUEST_LOGIN_URL
    assert login["allow_redirects"] is False
    assert summary_url == config.FAA_LICENSE_SUMMARY_URL
    assert summary["headers"]["jwt"] == "token" and summary["headers"]["user"] == "G"


def test_license_fetch_returns_none_without_a_guest_token(monkeypatch):
    sessions = _drs_sessions(monkeypatch, _drs(set_cookies=False))

    assert faa_license_fetcher.fetch_faa_license() is None
    assert len(sessions[0].calls) == 1


def test_license_fetch_returns_none_when_the_summary_is_refused(monkeypatch):
    _drs_sessions(monkeypatch, _drs(summary_status=403))

    assert faa_license_fetcher.fetch_faa_license() is None


def test_license_fetch_returns_none_on_a_network_error(monkeypatch):
    _drs_sessions(monkeypatch, lambda *a: requests.ConnectionError("down"))

    assert faa_license_fetcher.fetch_faa_license() is None


# --- FCC ELS ------------------------------------------------------------

SEARCH_FORM = (
    "<form name='generic_search_form'"
    " action='/oetcf/els/reports/GenericSearchResult.cfm?RequestTimeout=500'>"
    "<input name='name_licensee'><input name='receipt_date_from'>"
    "<input name='receipt_date_to'><input name='show_records' value='10'>"
    "<input name='fetchfrom' value='0'></form>"
)
RESULTS_URL = (
    "https://apps.fcc.gov/oetcf/els/reports/GenericSearchResult.cfm?RequestTimeout=500"
)


def _fcc_sessions(monkeypatch, handler, rows):
    monkeypatch.setattr(fcc_els_fetcher, "parse_fcc_els_results_html", lambda html: rows)
    monkeypatch.setattr(
        fcc_els_fetcher, "parse_fcc_els_detail_html", lambda html: {"Page": html}
    )
    return _sessions(monkeypatch, fcc_els_fetcher.cffi_requests, "Session", handler)


def _row(file_number):
    return {
        "file_number": file_number,
        "current_detail_url": f"/oetcf/els/reports/STA_Print.cfm?f={file_number}",
    }


def _fcc_site(detail):
    def handler(session, method, url, kwargs):
        if url == config.FCC_ELS_SEARCH_URL:
            return FakeResponse(SEARCH_FORM)
        if url == RESULTS_URL:
            return FakeResponse("results")
        return detail(url)

    return handler


def test_fcc_search_posts_the_whole_form_and_reads_each_detail(monkeypatch):
    handler = _fcc_site(lambda url: FakeResponse(f"detail {url[-4:]}"))
    sessions = _fcc_sessions(monkeypatch, handler, [_row("0001"), _row("0002")])

    apps = fcc_els_fetcher.fetch_fcc_els_applications()

    assert [a["detail"] for a in apps] == [{"Page": "detail 0001"}, {"Page": "detail 0002"}]
    method, url, kwargs = sessions[0].calls[1]
    assert (method, url) == ("POST", RESULTS_URL)
    assert kwargs["data"]["fetchfrom"] == "0"
    assert kwargs["data"]["name_licensee"] == config.FCC_ELS_SEARCH_TERM
    assert kwargs["data"]["show_records"] == str(config.FCC_ELS_RECORD_LIMIT)


def test_fcc_drops_a_row_whose_detail_keeps_failing(monkeypatch):
    handler = _fcc_site(
        lambda url: FakeResponse(status=503) if url.endswith("0001") else FakeResponse("ok")
    )
    sessions = _fcc_sessions(monkeypatch, handler, [_row("0001"), _row("0002")])

    apps = fcc_els_fetcher.fetch_fcc_els_applications()

    assert [a["file_number"] for a in apps] == ["0002"]
    failing = [c for c in sessions[0].calls if c[1].endswith("0001")]
    assert len(failing) == fcc_els_fetcher._DETAIL_MAX_ATTEMPTS


def test_fcc_returns_empty_when_the_search_page_is_refused(monkeypatch):
    _fcc_sessions(monkeypatch, lambda *a: FakeResponse(status=403), [_row("0001")])

    assert fcc_els_fetcher.fetch_fcc_els_applications() == []


def test_fcc_returns_empty_when_the_page_has_no_form(monkeypatch):
    sessions = _fcc_sessions(
        monkeypatch, lambda *a: FakeResponse("<p>maintenance</p>"), [_row("0001")]
    )

    assert fcc_els_fetcher.fetch_fcc_els_applications() == []
    assert len(sessions[0].calls) == 1
