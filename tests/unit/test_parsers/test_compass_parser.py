"""Unit tests for the COMPASS slide-list parser."""

from __future__ import annotations

import json

from starship_notam.parsers.compass_parser import parse_compass_file_list

_PAYLOAD = {
    "rows": [
        {
            "fileuuid": "c93d4b4a-3d80-4e46-9923-d95d338d8fad",
            "createtimestamp_format": "05/Oct/2026 14:26",
            "filename": "Host Master  - CADENA PLANNING WEB CONFERENCE  -  10 05 2026.pptx",
        },
        {"fileuuid": "", "filename": "no uuid"},
        "junk",
        {
            "fileuuid": "212b2a43-34e1-4526-a563-8da031cf1073",
            "createtimestamp_format": "01/Oct/2026 14:31",
            "filename": "older.pptx",
        },
    ]
}


def test_parses_rows_in_server_order_and_drops_rows_without_uuid():
    records = parse_compass_file_list(_PAYLOAD)

    assert records == [
        {
            "file_uuid": "c93d4b4a-3d80-4e46-9923-d95d338d8fad",
            "filename": "Host Master  - CADENA PLANNING WEB CONFERENCE  -  10 05 2026.pptx",
            "uploaded_at": "05/Oct/2026 14:26",
        },
        {
            "file_uuid": "212b2a43-34e1-4526-a563-8da031cf1073",
            "filename": "older.pptx",
            "uploaded_at": "01/Oct/2026 14:31",
        },
    ]


def test_accepts_json_text():
    assert parse_compass_file_list(json.dumps(_PAYLOAD)) == parse_compass_file_list(_PAYLOAD)


def test_junk_input_yields_empty_list():
    assert parse_compass_file_list("not json") == []
    assert parse_compass_file_list({"rows": None}) == []
    assert parse_compass_file_list(None) == []
