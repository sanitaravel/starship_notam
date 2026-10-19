"""Stored payload hashes must never change for an existing record.

Change detection compares a freshly computed hash with the stored one. If the
hash formula of a repository changed, every stored row would look "changed"
once after a deploy, and the sources that re-post on change (FAA activities,
FCC ELS applications, FAA licenses) would post everything again. Starbase
alerts are keyed by a hash too: a different key would store the same closure
as a new row and post it again. These values were captured from the
repositories before they were moved onto the shared base class; they must
stay byte-for-byte identical.
"""

from __future__ import annotations

import pytest

from src.data import (
    beach_alerts,
    compass_files,
    faa_activities,
    faa_licenses,
    fcc_els_applications,
    federal_register_documents,
    regulations_gov_documents,
    road_alerts,
    sec_edgar_filings,
    uscg_bnm_notices,
)
from src.data.connection import get_connection

FAA_ACTIVITY = {
    "mission": "SpaceX Starship Flight 12, Boca Chica",
    "primary_window": "10/15/26 1200Z-1400Z",
    "backup_window": None,
}

FCC_APPLICATION = {
    "file_number": "0123-EX-ST-2026",
    "application_seq": "1",
    "applicant_name": "Space Exploration Technologies Corp.",
    "call_sign": "WK2XYZ",
    "receipt_date": "10/01/2026",
    "status": "Granted",
    "status_date": "10/10/2026",
    "current_detail_url": "/oetcf/els/reports/STA_Print.cfm?mode=current&application_seq=1",
    "detail": {"Explanation": "Starship flight — telemetry", "Please explain the purpose of operation": "Launch"},
}

FAA_LICENSE = {
    "doc_unique_id": "DRSDOCID123",
    "content_guid": "guid-1",
    "doc_number": "VOL 23-129",
    "doc_name": "VOL 23-129 Rev 5.pdf",
    "doc_type_label": "LAUNCH_VEHICLE_OPERATOR_LICENSES",
    "status": "Current",
    "revision_number": "5",
    "issue_date": "10/01/2026",
    "expiration_date": "04/14/2028",
    "details": {"License Number": "VOL 23-129", "Status": "Current", "Location": "Starbase, Texas"},
}

COMPASS_FILE = {
    "file_uuid": "c0ffee-uuid",
    "filename": "Master Slide Deck 15-Oct.pptx",
    "uploaded_at": "15/Oct/2026 08:00",
}

FEDERAL_REGISTER_DOCUMENT = {
    "document_number": "2026-12345",
    "title": "Environmental Assessment for SpaceX Starship",
    "doc_type": "Notice",
    "abstract": "The FAA announces …",
    "publication_date": "2026-10-14",
    "comments_close_on": "2026-11-13",
    "html_url": "https://www.federalregister.gov/d/2026-12345",
    "pdf_url": "https://www.govinfo.gov/content/pkg/FR-2026-10-14/pdf/2026-12345.pdf",
}

REGULATIONS_GOV_DOCUMENT = {
    "document_id": "FAA-2026-12808-0001",
    "docket_id": "FAA-2026-12808",
    "agency_id": "FAA",
    "document_type": "Notice",
    "subtype": "Request for Comments",
    "title": "Notice of Intent To Prepare a Programmatic EIS for SpaceX Starship",
    "fr_doc_num": "2026-20963",
    "posted_date": "2026-10-14T04:00:00Z",
    "comment_end_date": "2026-12-01T04:59:59Z",
}

SEC_EDGAR_FILING = {
    "accession_number": "0001628280-26-056945",
    "form": "8-K",
    "items": "2.01,3.02,9.01",
    "filing_date": "2026-08-14",
    "report_date": "2026-08-14",
    "acceptance_datetime": "2026-08-14T12:23:02.000Z",
    "description": "8-K",
    "document_url": "https://www.sec.gov/Archives/edgar/data/1181412/000162828026056945/spcx-20260814.htm",
    "index_url": "https://www.sec.gov/Archives/edgar/data/1181412/000162828026056945/0001628280-26-056945-index.htm",
}

USCG_BNM_NOTICE = {
    "notice_key": "SAFETY CGD-H BNM 0108-26",
    "bnm_id": "CGD-H BNM 0108-26",
    "kind": "SAFETY",
    "region": "TX - GULF OF AMERICA - CARIBBEAN SEA",
    "title": "SAFETY/TX - GULF OF AMERICA - CARIBBEAN SEA/SPACE OPERATIONS/CGD-H BNM 0108-26",
    "flight": "14",
    "mission": "STARSHIP FLIGHT 14",
    "starship": True,
    "areas": [{"label": "HAZARD AREA", "coords": [[25.966667, -97.216667], [26.033333, -97.216667]]}],
    "windows": [["2026-09-28T12:15:00Z", "2026-09-28T14:14:00Z"]],
    "cancel_at": "2026-10-04T15:14:00Z",
    "cancels": "",
    "outcome": "",
    "published_at": "2026-09-25T18:24:01Z",
    "link": "https://content.govdelivery.com/accounts/USDHSCG/bulletins/42c8bcc",
}

EXPECTED_FAA_ACTIVITY = "192ff71ec0fe2b0074c8070078b237d717641730194a5cebd10e51166606816e"
EXPECTED_FCC = "1432405b56c7b924a288e7bef4d68246763a5dff16a82152c7514a68f1c79e46"
EXPECTED_LICENSE = "ca0fa1f8eaeef96e54d4a974b040b0b9baf630f4ce7c82b8ae5c369caadb9600"
EXPECTED_COMPASS = "27f2633f9ac9895d8676f35203e39f274d203710d292de691d0f1a430a0814eb"
EXPECTED_FR = "0a828313cd958511ccd4d6d265eef996880eb826bc6a46bf248ce89c47ee079d"
EXPECTED_REGULATIONS_GOV = "19c9521d3e70e2c27fe07cd9136ab0dda475e5489a2f924f1c3c8224961ec54d"
EXPECTED_SEC_EDGAR = "1c14e3d59c18ba67834e2214bf09ed83b675768c093a762dd18ca4e4b2f062db"
EXPECTED_USCG_BNM = "748624a2e3ab671a68a3b0530e94f42844282219eef442e4b2a4a8352a895785"

CASES = [
    (faa_activities.save, FAA_ACTIVITY, "faa_activities", "mission",
     EXPECTED_FAA_ACTIVITY),
    (fcc_els_applications.save, FCC_APPLICATION, "fcc_els_applications", "file_number",
     EXPECTED_FCC),
    (faa_licenses.save, FAA_LICENSE, "faa_licenses", "doc_unique_id",
     EXPECTED_LICENSE),
    (compass_files.save, COMPASS_FILE, "compass_files", "file_uuid",
     EXPECTED_COMPASS),
    (federal_register_documents.save, FEDERAL_REGISTER_DOCUMENT,
     "federal_register_documents", "document_number", EXPECTED_FR),
    (regulations_gov_documents.save, REGULATIONS_GOV_DOCUMENT,
     "regulations_gov_documents", "document_id", EXPECTED_REGULATIONS_GOV),
    (sec_edgar_filings.save, SEC_EDGAR_FILING,
     "sec_edgar_filings", "accession_number", EXPECTED_SEC_EDGAR),
    (uscg_bnm_notices.save, USCG_BNM_NOTICE,
     "uscg_bnm_notices", "notice_key", EXPECTED_USCG_BNM),
]


def _stored_hash(db_path, table, key_col, key):
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            f"SELECT payload_hash FROM {table} WHERE {key_col} = ?", (key,)
        ).fetchone()
    finally:
        conn.close()
    return row["payload_hash"]


@pytest.mark.parametrize(
    "save, record, table, key_col, expected", CASES, ids=[c[2] for c in CASES]
)
def test_stored_hash_is_unchanged(initialized_db, save, record, table, key_col, expected):
    save(dict(record), initialized_db)

    assert _stored_hash(initialized_db, table, key_col, record[key_col]) == expected


BEACH_ALERT = {
    "description": "Beach closed for Starship testing",
    "start_utc": "2026-10-15T13:00:00Z",
    "end_utc": "2026-10-16T01:00:00Z",
    "raw_date": "Oct 15, 8:00 AM - 8:00 PM",
    "periods": [
        {
            "start_utc": "2026-10-15T13:00:00Z",
            "end_utc": "2026-10-16T01:00:00Z",
            "raw_date": "Oct 15 — primary",
        }
    ],
}

ROAD_ALERT = {
    "origin": "Production",
    "destination": "Pad",
    "description": "Transport of Starship",
    "start_utc": "2026-10-15T05:00:00Z",
    "end_utc": "2026-10-15T11:00:00Z",
    "raw_date": "Oct 15, 12:00 AM - 6:00 AM",
}

STARBASE_CASES = [
    (
        beach_alerts,
        BEACH_ALERT,
        "a1ce2e6b3bc0a099ecbd368ac190c6a3bbbc03b4cafba6478234bbfc80a4f8e5",
        "56dbd9cc95f233598e81e3b5c630f942e6d68404fa31470850918c5a9ad266a6",
    ),
    (
        road_alerts,
        ROAD_ALERT,
        "730629501ff304d013a5e5349078534d1df994d18cfed417ff1ebaaeb1c6903a",
        "7fcaa54b5055f11ddfb031f14a95b1ee75684b677accde84caaf0ecc22fa7479",
    ),
]


@pytest.mark.parametrize(
    "repo, alert, expected_key, expected_hash", STARBASE_CASES, ids=["beach", "road"]
)
def test_starbase_key_and_hash_are_unchanged(
    initialized_db, repo, alert, expected_key, expected_hash
):
    repo.save(dict(alert), initialized_db)

    conn = get_connection(initialized_db)
    try:
        row = conn.execute(f"SELECT alert_key, payload_hash FROM {repo.table}").fetchone()
    finally:
        conn.close()
    assert (row["alert_key"], row["payload_hash"]) == (expected_key, expected_hash)
