"""Unit tests for USCG Broadcast Notice to Mariners parsing (``parsers.uscg_bnm_parser``)."""

from __future__ import annotations

from src.parsers.uscg_bnm_parser import parse_uscg_bnm_feed


def _item(title, body, pub="Fri, 25 Sep 2026 13:24:01 -0500", link="https://example.org/b"):
    return (
        f"<item><title>{title}</title><description><![CDATA[{body}]]></description>"
        f"<pubDate>{pub}</pubDate><link>{link}</link><guid>1</guid></item>"
    )


def _feed(*items):
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{"".join(items)}</channel></rss>'


# Shaped like the GovDelivery feeds USDHSCG_414 / USDHSCG_422 (2026-10-19),
# vertex lists trimmed.
HEARTLAND = _item(
    "SAFETY/TX - GULF OF AMERICA - CARIBBEAN SEA/SPACE OPERATIONS/CGD-H BNM 0108-26",
    "<p>1. SPACE LAUNCH OPERATIONS, WHICH MAY BE HAZARDOUS TO SURFACE VESSELS, WILL "
    "BE CONDUCTED WITHIN PORTIONS OF THE FOLLOWING HAZARD AREAS FOR STARSHIP FLIGHT 14:<br />"
    "A. HIGH RISK HAZARD AREA<br />25-12-00N 092-58-00W, 25-31-00N 093-52-00W, "
    "25-11-42N 092-57-51W AND 24-45-00N 092-43-00W.<br />"
    "B. HAZARD AREA<br />25-58-00N 097-13-00W, 26-02-00N 097-13-00W AND 25-48-00N 097-05-00W.<br />"
    "2. PRIMARY AND BACKUP LAUNCH DAY HAZARD PERIODS INCLUDE:<br />"
    "28/1215Z SEP 26 TO 28/1414Z SEP 26<br />30/2315Z SEP 26 TO 01/0122Z OCT 26<br />"
    "3. NAVIGATION HAZARDS WITHIN THE HAZARD AREAS MAY INCLUDE FREE FALLING DEBRIS.<br />"
    "CANCEL AT//041514Z OCT 26//</p><p>BT</p>",
)
SOUTHEAST = _item(
    "SAFETY/GULF OF AMERICA/SPACE OPERATIONS/CGD-SE BNM 9066-26",
    "1. SPACE LAUNCH OPERATIONS, WHICH MAY BE HAZARDOUS TO SURFACE VESSELS, WILL BE "
    "CONDUCTED WITHIN PORTIONS OF THE FOLLOWING HAZARD AREAS FOR STARSHIP FLIGHT 13: "
    "A. FROM 025-58-00N/097-13-00W TO 026-02-00N/097-13-00W TO 019-19-00N/077-54-00W "
    "TO BEGINNING 2. HAZARD PERIODS FOR PRIMARY LAUNCH DAY AND BACKUP LAUNCH DAYS (ALL "
    "TIMES ARE REPRESENTED AS ZULU TIME UNLESS OTHERWISE INDICATED): 20/2245 JUL 26 TO "
    "21/0056 JUL 26. 3. THE U.S. COAST GUARD IS PROVIDING THIS NOTICE. BT",
    pub="Sun, 19 Jul 2026 19:27:51 -0500",
)
CANCELLATION = _item(
    "CANCELLATION/GULF OF AMERICA/SPACE OPERATIONS/CGD-SE BNM 9066-26",
    "1. CANCEL CGD-SE BNM 9066-26 DTG 191351Z JUL 26 2. STARSHIP FLIGHT 13, "
    "SUCCESSFUL LAUNCH. BT",
    pub="Sat, 25 Jul 2026 21:08:46 -0500",
)
FALCON = _item(
    "SAFETY/ATLANTIC OCEAN-FLORIDA-CAPE CANAVERAL/SPACE OPERATIONS/CGD-SE BNM 9079-26",
    "1. SPACE LAUNCH OPERATIONS ... HAZARD AREAS FOR CRS-35: A. FROM "
    "31-04-00N/077-59-00W TO 31-36-00N/077-41-00W TO BEGINNING 2. HAZARD PERIODS: "
    "11/1500 OCT 26 TO 11/1700 OCT 26. BT",
)
NAVY = _item(
    "SAFETY/GULF OF AMERICA/LIVE FIRE EXERCISE/CGD-H BNM 0120-26",
    "A LIVE FIRE EXERCISE WILL BE HELD 30-10-01N 088-01-30W. BT",
)


def test_heartland_safety_notice():
    [notice] = parse_uscg_bnm_feed(_feed(HEARTLAND))

    assert notice["notice_key"] == "SAFETY CGD-H BNM 0108-26"
    assert notice["bnm_id"] == "CGD-H BNM 0108-26"
    assert notice["kind"] == "SAFETY"
    assert notice["region"] == "TX - GULF OF AMERICA - CARIBBEAN SEA"
    assert notice["flight"] == "14"
    assert notice["mission"] == "STARSHIP FLIGHT 14"
    assert notice["starship"] is True
    high, hazard = notice["areas"]
    assert high["label"] == "HIGH RISK HAZARD AREA"
    # The vertex after "AND" is kept; seconds count.
    assert high["coords"] == [
        [25.2, -92.966667],
        [25.516667, -93.866667],
        [25.195, -92.964167],
        [24.75, -92.716667],
    ]
    assert hazard["label"] == "HAZARD AREA"
    assert len(hazard["coords"]) == 3
    assert notice["windows"] == [
        ["2026-09-28T12:15:00Z", "2026-09-28T14:14:00Z"],
        ["2026-09-30T23:15:00Z", "2026-10-01T01:22:00Z"],
    ]
    assert notice["cancel_at"] == "2026-10-04T15:14:00Z"
    assert notice["cancels"] == ""
    assert notice["published_at"] == "2026-09-25T18:24:01Z"
    assert notice["link"] == "https://example.org/b"


def test_southeast_from_to_syntax_with_three_digit_latitude():
    [notice] = parse_uscg_bnm_feed(_feed(SOUTHEAST))

    [area] = notice["areas"]
    assert area["label"] == ""
    assert area["coords"] == [
        [25.966667, -97.216667],
        [26.033333, -97.216667],
        [19.316667, -77.9],
    ]
    # No "Z" after the time, still UTC; no CANCEL AT line.
    assert notice["windows"] == [["2026-07-20T22:45:00Z", "2026-07-21T00:56:00Z"]]
    assert notice["cancel_at"] == ""


def test_cancellation_names_the_cancelled_notice_and_outcome():
    [notice] = parse_uscg_bnm_feed(_feed(CANCELLATION))

    assert notice["notice_key"] == "CANCELLATION CGD-SE BNM 9066-26"
    assert notice["cancels"] == "CGD-SE BNM 9066-26"
    assert notice["outcome"] == "STARSHIP FLIGHT 13, SUCCESSFUL LAUNCH"
    assert notice["flight"] == "13"
    assert notice["areas"] == []
    assert notice["windows"] == []


def test_only_space_operations_are_returned_and_flagged():
    notices = parse_uscg_bnm_feed(_feed(HEARTLAND, NAVY, FALCON))

    assert [n["bnm_id"] for n in notices] == ["CGD-H BNM 0108-26", "CGD-SE BNM 9079-26"]
    falcon = notices[1]
    assert falcon["starship"] is False
    assert falcon["mission"] == "CRS-35"
    assert falcon["flight"] == ""


def test_old_district_names_are_recognised():
    item = _item(
        "CANCELLATION/GULF/SPACE OPERATIONS/CCGD7 BNM 9106-25",
        "1. CANCEL CCGD7 BNM 9106-25 DTG 222045Z AUG 25 2. STARSHIP FLIGHT 10, "
        "SUCCESSFUL LAUNCH. BT",
    )
    [notice] = parse_uscg_bnm_feed(_feed(item))

    assert notice["bnm_id"] == "CCGD7 BNM 9106-25"
    assert notice["cancels"] == "CCGD7 BNM 9106-25"


def test_junk_input():
    assert parse_uscg_bnm_feed("not xml") == []
    assert parse_uscg_bnm_feed(_feed()) == []
