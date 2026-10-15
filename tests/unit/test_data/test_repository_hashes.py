"""Stored payload hashes must never change for an existing record.

Change detection compares a freshly computed hash with the stored one. If the
hash formula of a repository changed, every stored row would look "changed"
once after a deploy, and the sources that re-post on change (FAA activities,
FCC ELS applications, FAA licenses) would post everything again. These
values were captured from the repositories before they were moved onto the
shared base class; they must stay byte-for-byte identical.
"""

from __future__ import annotations

import pytest

from starship_notam.data import (
    save_compass_file,
    save_faa_activity,
    save_faa_license,
    save_fcc_els_application,
    save_federal_register_document,
)
from starship_notam.data.connection import get_connection

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

EXPECTED_FAA_ACTIVITY = "192ff71ec0fe2b0074c8070078b237d717641730194a5cebd10e51166606816e"
EXPECTED_FCC = "1432405b56c7b924a288e7bef4d68246763a5dff16a82152c7514a68f1c79e46"
EXPECTED_LICENSE = "ca0fa1f8eaeef96e54d4a974b040b0b9baf630f4ce7c82b8ae5c369caadb9600"
EXPECTED_COMPASS = "27f2633f9ac9895d8676f35203e39f274d203710d292de691d0f1a430a0814eb"
EXPECTED_FR = "0a828313cd958511ccd4d6d265eef996880eb826bc6a46bf248ce89c47ee079d"

CASES = [
    (save_faa_activity, FAA_ACTIVITY, "faa_activities", "mission",
     EXPECTED_FAA_ACTIVITY),
    (save_fcc_els_application, FCC_APPLICATION, "fcc_els_applications", "file_number",
     EXPECTED_FCC),
    (save_faa_license, FAA_LICENSE, "faa_licenses", "doc_unique_id",
     EXPECTED_LICENSE),
    (save_compass_file, COMPASS_FILE, "compass_files", "file_uuid",
     EXPECTED_COMPASS),
    (save_federal_register_document, FEDERAL_REGISTER_DOCUMENT,
     "federal_register_documents", "document_number", EXPECTED_FR),
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
