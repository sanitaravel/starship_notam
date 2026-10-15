"""Selenium scrapers open the browser through one helper that always quits it."""

from __future__ import annotations

import pytest

from starship_notam.scrapers import driver as driver_module
from starship_notam.scrapers.faa_license_fetcher import fetch_faa_license
from starship_notam.scrapers.fcc_els_fetcher import fetch_fcc_els_applications
from starship_notam.scrapers.notam_scraper import search_notams


class FakeDriver:
    def __init__(self, quit_error: Exception | None = None):
        self.quit_calls = 0
        self.quit_error = quit_error

    def quit(self):
        self.quit_calls += 1
        if self.quit_error:
            raise self.quit_error


@pytest.fixture
def fake_driver(monkeypatch):
    drv = FakeDriver()
    monkeypatch.setattr(driver_module, "create_driver", lambda: drv)
    return drv


def test_browser_is_quit_after_normal_use(fake_driver):
    with driver_module.browser_session() as drv:
        assert drv is fake_driver

    assert fake_driver.quit_calls == 1


def test_browser_is_quit_when_the_scrape_raises(fake_driver):
    with pytest.raises(RuntimeError, match="page broke"):
        with driver_module.browser_session():
            raise RuntimeError("page broke")

    assert fake_driver.quit_calls == 1


def test_failing_quit_does_not_hide_the_result(monkeypatch):
    drv = FakeDriver(quit_error=RuntimeError("session already gone"))
    monkeypatch.setattr(driver_module, "create_driver", lambda: drv)

    with driver_module.browser_session():
        result = "scraped"

    assert result == "scraped" and drv.quit_calls == 1


@pytest.fixture
def browser_will_not_start(monkeypatch):
    def broken():
        raise RuntimeError("grid unreachable")

    monkeypatch.setattr(driver_module, "create_driver", broken)


def test_license_fetch_returns_none_when_the_browser_will_not_start(browser_will_not_start):
    assert fetch_faa_license() is None


def test_fcc_fetch_returns_empty_when_the_browser_will_not_start(browser_will_not_start):
    assert fetch_fcc_els_applications() == []


def test_notam_search_still_raises_when_the_browser_will_not_start(browser_will_not_start):
    # search_notams reports failures to its caller on purpose.
    with pytest.raises(RuntimeError, match="grid unreachable"):
        search_notams("starship")
