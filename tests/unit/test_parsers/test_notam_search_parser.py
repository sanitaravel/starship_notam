"""The FAA NOTAM Search JSON maps onto the rows the NOTAM orchestrator persists."""

from __future__ import annotations

import json

import pytest

from src.parsers.notam_search_parser import parse_notam_search_page


def _page(notams, total=None, error=""):
    return json.dumps({
        "notamList": notams,
        "totalNotamCount": len(notams) if total is None else total,
        "error": error,
    })


INTERNATIONAL = {
    "facilityDesignator": "SCIZ",
    "notamNumber": "W3484/26",
    "featureName": "International",
    "startDate": "10/21/2026 0001",
    "endDate": "10/27/2026 0312",
    "traditionalMessageFrom4thWord": " ",
    "icaoMessage": "W3484/26 NOTAMN \r\nQ)SCIZ/QXXXX/IV/NBO/W/000/999/4406S11235W980\r\nA)SCIZ",
    "traditionalMessage": " ",
}


def test_international_notam_keeps_its_number_and_icao_text():
    rows, total = parse_notam_search_page(_page([INTERNATIONAL], total=31))

    assert total == 31
    assert rows == [{
        "location": "SCIZ",
        "number": "W3484/26",
        "class": "International",
        "start_date_utc": "10/21/2026 0001",
        "end_date_utc": "10/27/2026 0312",
        "condition": "",
        "icao_message": "W3484/26 NOTAMN \nQ)SCIZ/QXXXX/IV/NBO/W/000/999/4406S11235W980\nA)SCIZ",
    }]


def test_domestic_notam_falls_back_to_the_traditional_text():
    domestic = {**INTERNATIONAL, "icaoMessage": " ", "traditionalMessage": "!FDC 6/1234 ZHU TX..."}

    rows, _ = parse_notam_search_page(_page([domestic]))

    assert rows[0]["icao_message"] == "!FDC 6/1234 ZHU TX..."


def test_empty_search():
    assert parse_notam_search_page(_page([])) == ([], 0)


@pytest.mark.parametrize("body", ["<html>Access Denied</html>", "[]", json.dumps({"error": ""})])
def test_non_search_body_raises(body):
    with pytest.raises(ValueError):
        parse_notam_search_page(body)


def test_api_error_raises():
    with pytest.raises(ValueError, match="bad query"):
        parse_notam_search_page(_page([], error="bad query"))
