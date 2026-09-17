"""FAA DRS launch-license summary parsing.

Pure-function parser for the FAA Dynamic Regulatory System (DRS) document
"summary" JSON returned by
``/api/browse/documents/summaryguiddocview/<DRSDOCID>``. That JSON backs the
"Document Details" panel shown in the DRS document viewer -- the only part of
the page we track for a Starship launch (Vehicle Operator) license.

These functions accept the summary payload (a dict, or a JSON string) and
return a normalized record dict. They perform no network, database, or
filesystem operations.

Public API:
    parse_faa_license_summary(payload: dict | str) -> dict
"""

from __future__ import annotations

import json
from typing import Any

from starship_notam.core.logging import logger

# The ordered set of "Document Details" fields we surface. Order controls how
# the fields are rendered in the Telegram message. Every key is looked up in
# the summary payload's ``metadatas`` object; missing keys become "".
DETAIL_FIELDS: tuple[str, ...] = (
    "Document Type",
    "License Number",
    "Status",
    "Revision Number",
    "Document Issue Date",
    "Document Expiration Date",
    "Company",
    "Vehicles",
    "Location",
    "Service/Office",
    "Office of Primary Responsibility",
    "CFR Part Reference",
    "CFR Subpart/Appendix Reference",
    "CFR Section Reference",
)


def _coerce_payload(payload: Any) -> dict:
    """Return ``payload`` as a dict, tolerating a JSON string or junk input."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def parse_faa_license_summary(payload: dict | str) -> dict:
    """Normalize a DRS document-summary payload into a launch-license record.

    Parameters
    ----------
    payload : dict or str
        The parsed JSON (or a JSON string) returned by the DRS
        ``summaryguiddocview`` endpoint.

    Returns
    -------
    dict
        A record with the keys:

        ``doc_unique_id``
            The stable ``DRSDOCID...`` document identifier.
        ``content_guid``
            The underlying content object id (``id`` in the payload). This
            changes when the document file is replaced, so it is a strong
            change signal even if the visible metadata is unchanged.
        ``doc_number``
            The license number (e.g. ``"VOL 23-129"``).
        ``doc_name``
            The stored document/file name.
        ``doc_type_label``
            The DRS document-type label (e.g.
            ``"LAUNCH_VEHICLE_OPERATOR_LICENSES"``).
        ``status``, ``revision_number``, ``issue_date``, ``expiration_date``
            Convenience copies of the most change-relevant detail fields,
            pulled from ``metadatas``.
        ``details``
            An ordered ``{label: value}`` dict containing exactly the
            :data:`DETAIL_FIELDS` (the "Document Details" panel). Missing
            fields are included with an empty-string value so the shape is
            stable across revisions.

        Returns ``{}`` when the payload is missing the document identifier
        (nothing meaningful to track).
    """
    data = _coerce_payload(payload)
    if not data:
        return {}

    metadatas = data.get("metadatas")
    if not isinstance(metadatas, dict):
        metadatas = {}

    def _md(label: str) -> str:
        value = metadatas.get(label, "")
        return "" if value is None else str(value).strip()

    doc_unique_id = str(data.get("docUniqueId") or "").strip()
    if not doc_unique_id:
        logger.info(
            "Excluding FAA DRS license summary: missing docUniqueId (keys=%s)",
            sorted(data.keys()),
        )
        return {}

    # The ordered "Document Details" panel: exactly the fields we track.
    details = {label: _md(label) for label in DETAIL_FIELDS}

    record = {
        "doc_unique_id": doc_unique_id,
        "content_guid": str(data.get("id") or "").strip(),
        "doc_number": str(data.get("docNumber") or "").strip(),
        "doc_name": str(data.get("docName") or "").strip(),
        "doc_type_label": str(data.get("docTypeUrlLabel") or "").strip(),
        "status": details.get("Status", ""),
        "revision_number": details.get("Revision Number", ""),
        "issue_date": details.get("Document Issue Date", ""),
        "expiration_date": details.get("Document Expiration Date", ""),
        "details": details,
    }
    return record
