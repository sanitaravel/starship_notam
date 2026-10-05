"""NOTAM searches share one browser session and pick selectors by priority.

Regression test for fix-plan step 11: every keyword used to start its own
browser, wait 5s per missed selector, and sleep 5s before quitting.
"""

from __future__ import annotations

from starship_notam.scrapers import notam_scraper


class FakeDriver:
    def __init__(self):
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1


def test_many_keywords_share_one_driver_and_survive_a_failure(monkeypatch):
    drivers: list[FakeDriver] = []

    def make_driver():
        drivers.append(FakeDriver())
        return drivers[-1]

    calls = []

    def fake_search(driver, keyword, consent_timeout):
        calls.append((driver, keyword, consent_timeout))
        if keyword == "bad":
            raise RuntimeError("page broke")
        return [{"number": keyword}]

    monkeypatch.setattr(notam_scraper, "create_driver", make_driver)
    monkeypatch.setattr(notam_scraper, "_search_with_driver", fake_search)

    results = notam_scraper.search_notams_many(["a", "bad", "c"])

    assert results == {"a": [{"number": "a"}], "bad": [], "c": [{"number": "c"}]}
    assert len(drivers) == 1 and drivers[0].quit_calls == 1
    assert all(driver is drivers[0] for driver, _, _ in calls)
    # Only the first search waits the full time for the consent dialog.
    assert [timeout for _, _, timeout in calls] == [
        notam_scraper._STEP_TIMEOUT,
        notam_scraper._REPEAT_CONSENT_TIMEOUT,
        notam_scraper._REPEAT_CONSENT_TIMEOUT,
    ]


class FakeElement:
    def __init__(self, displayed=True, enabled=True):
        self._displayed, self._enabled = displayed, enabled

    def is_displayed(self):
        return self._displayed

    def is_enabled(self):
        return self._enabled


class PageDriver:
    def __init__(self, elements_by_xpath):
        self.elements_by_xpath = elements_by_xpath

    def find_elements(self, by, xpath):
        return self.elements_by_xpath.get(xpath, [])


def test_first_clickable_respects_priority_and_skips_hidden():
    hidden, visible, later = FakeElement(displayed=False), FakeElement(), FakeElement()
    driver = PageDriver({"//first": [hidden], "//second": [visible], "//third": [later]})

    condition = notam_scraper._first_clickable(["//first", "//second", "//third"])

    assert condition(driver) == (visible, "//second")


def test_first_clickable_returns_false_when_nothing_matches():
    condition = notam_scraper._first_clickable(["//missing"])

    assert condition(PageDriver({})) is False
