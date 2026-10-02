"""Scraped NOTAMs are only saved when they actually contain the keyword.

Regression test for fix-plan step 4: the FAA free-text search for
``re-entry`` returned French "VFR ENTRY" notices (e.g. A6286/26 at LFBH),
which were saved, rendered and posted.
"""

from __future__ import annotations

import pytest

from starship_notam.bot import orchestrator

LA_ROCHELLE = (
    "A6286/26 NOTAMN Q) LFBB/QPFCA/V/NBO/E/000/050/4617N00107W023 A) LFBH "
    "B) 2609281130 C) 2609281600 E) VFR ENTRY WI LA ROCHELLE CTR AND TMA 1, "
    "2.1 AND 2.2 UNDER 5000FT QNH SUBJECT TO 10MIN PN TO LA ROCHELLE INFO "
    "124.205MHZ."
)
REENTRY = (
    "!FDC 6/1234 ZAK PART 1 OF 2 SPACE VEHICLE RE-ENTRY OVER PACIFIC OCEAN "
    "WITH SPLASHDOWN WI AN AREA DEFINED AS 200000N1600000W TO "
    "210000N1600000W TO 210000N1590000W SFC-UNL 2610011200-2610011400"
)
BROWNSVILLE_TFR = (
    "!FDC 6/5082 ZHU TX..AIRSPACE BROWNSVILLE, TX..TEMPORARY FLIGHT "
    "RESTRICTIONS. LAUNCH REHERSAL WI AN AREA DEFINED AS 2.5NM RADIUS OF "
    "255950N970921W SFC-10000FT AGL ONLY RELIEF ACFT OPS UNDER DIRECTION OF "
    "SPACEX ARE AUTH IN THE AIRSPACE. 2609230500-2610070500"
)


@pytest.fixture
def saved(monkeypatch):
    names: list[str] = []
    monkeypatch.setattr(
        orchestrator, "save_notam", lambda name, parsed, db_path: names.append(name)
    )
    return names


def test_vfr_entry_notice_is_not_saved_for_reentry_search(saved):
    orchestrator._persist_notam_results(
        [{"number": "A6286/26", "icao_message": LA_ROCHELLE}], "re-entry"
    )

    assert saved == []


def test_real_reentry_notam_is_saved(saved):
    orchestrator._persist_notam_results(
        [{"number": "6/1234", "icao_message": REENTRY}], "re-entry"
    )

    assert saved == ["6_1234"]


def test_multi_word_keyword_matches_in_any_order(saved):
    # The TFR says BROWNSVILLE before SPACEX.
    orchestrator._persist_notam_results(
        [{"number": "6/5082", "icao_message": BROWNSVILLE_TFR}], "spacex brownsville"
    )

    assert saved == ["6_5082"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("RE-ENTRY OF ROCKET", True),
        ("REENTRY AREA", True),
        ("RE ENTRY AREA", True),
        ("VFR ENTRY WITHIN CTR", False),
        ("LA ROCHELLE ILE DE RE CTR, VFR ENTRY", False),
    ],
)
def test_hyphenated_keyword_variants(text, expected):
    assert orchestrator._matches_keyword(text, "re-entry") is expected
