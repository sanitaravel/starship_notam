"""Regulations.gov API parsing.

Pure-function parsers for the JSON:API payloads of the Regulations.gov v4 API.
A document search (``/documents?filter[searchTerm]=...``) looks like::

    {"data": [{"id": "FAA-2026-12808-0001", "type": "documents",
               "attributes": {"agencyId": "FAA", "docketId": "FAA-2026-12808",
                              "documentType": "Notice",
                              "subtype": "Request for Comments",
                              "frDocNum": "2026-20963", "title": "...",
                              "postedDate": "2026-10-14T04:00:00Z",
                              "commentEndDate": "2026-12-01T04:59:59Z",
                              "withdrawn": false, ...}}, ...],
     "meta": {...}}

A single document with ``include=attachments`` carries the document's own
files in ``data.attributes.fileFormats`` and each attachment in
``included[]``, with ``attributes.title``, ``docOrder`` and ``fileFormats``
(``[{"fileUrl": "...", "format": "pdf", "size": 231269}]``).

They perform no network, database, or filesystem operations.

Public API:
    parse_regulations_gov_documents(payload: dict | str) -> list[dict]
    parse_regulations_gov_files(payload: dict | str) -> list[dict]
"""

from __future__ import annotations

import json
from typing import Any

from src.core.logging import logger


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _load(payload: Any) -> dict | None:
    """Return *payload* as a JSON object, or None (logged) if it is not one."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            logger.error("Regulations.gov response is not valid JSON")
            return None
    if not isinstance(payload, dict):
        logger.error("Regulations.gov response is not a JSON object")
        return None
    return payload


def parse_regulations_gov_documents(payload: Any) -> list[dict]:
    """Normalize a document search payload into a list of document records.

    Parameters
    ----------
    payload : dict or str
        The parsed JSON, or the raw JSON text.

    Returns
    -------
    list[dict]
        One record per document, in the order the server returned them, each
        with the keys ``document_id``, ``docket_id``, ``agency_id``,
        ``document_type``, ``subtype``, ``title``, ``fr_doc_num``,
        ``posted_date`` and ``comment_end_date`` (ISO UTC timestamps, or
        ``""``). Results without an id and withdrawn documents are dropped;
        junk input yields ``[]``.
    """
    payload = _load(payload)
    if payload is None:
        return []

    data = payload.get("data") or []
    if not isinstance(data, list):
        logger.error("Regulations.gov response has no 'data' list")
        return []

    records = []
    for row in data:
        if not isinstance(row, dict):
            continue
        document_id = _text(row.get("id"))
        attributes = row.get("attributes")
        if not document_id or not isinstance(attributes, dict):
            logger.info("Skipping Regulations.gov result without id: %s", row)
            continue
        if attributes.get("withdrawn"):
            logger.info("Skipping withdrawn Regulations.gov document %s", document_id)
            continue
        records.append(
            {
                "document_id": document_id,
                "docket_id": _text(attributes.get("docketId")),
                "agency_id": _text(attributes.get("agencyId")),
                "document_type": _text(attributes.get("documentType")),
                "subtype": _text(attributes.get("subtype")),
                "title": _text(attributes.get("title")),
                "fr_doc_num": _text(attributes.get("frDocNum")),
                "posted_date": _text(attributes.get("postedDate")),
                "comment_end_date": _text(attributes.get("commentEndDate")),
            }
        )
    return records


def _first_file(file_formats: Any) -> tuple[str, str]:
    """Return ``(url, format)`` of the preferred file: the PDF, else the first."""
    files = [
        f for f in (file_formats or [])
        if isinstance(f, dict) and _text(f.get("fileUrl"))
    ]
    if not files:
        return "", ""
    chosen = next((f for f in files if _text(f.get("format")).lower() == "pdf"), files[0])
    return _text(chosen.get("fileUrl")), _text(chosen.get("format")).lower()


def parse_regulations_gov_files(payload: Any) -> list[dict]:
    """List the downloadable files of one document (``include=attachments``).

    Returns
    -------
    list[dict]
        ``{"title", "url", "format"}`` per file: the document's own content
        first (titled ``""``), then the attachments in ``docOrder``. Each
        entry links its PDF when there is one, otherwise its first format.
        Entries without a file URL are dropped; junk input yields ``[]``.
    """
    payload = _load(payload)
    if payload is None:
        return []

    files = []
    data = payload.get("data")
    if isinstance(data, dict):
        url, fmt = _first_file((data.get("attributes") or {}).get("fileFormats"))
        if url:
            files.append({"title": "", "url": url, "format": fmt})

    attachments = []
    for item in payload.get("included") or []:
        if not isinstance(item, dict) or item.get("type") != "attachments":
            continue
        attributes = item.get("attributes") or {}
        url, fmt = _first_file(attributes.get("fileFormats"))
        if not url:
            continue
        order = attributes.get("docOrder")
        attachments.append(
            (
                order if isinstance(order, int) else 10**9,
                {"title": _text(attributes.get("title")), "url": url, "format": fmt},
            )
        )
    attachments.sort(key=lambda pair: pair[0])
    return files + [entry for _, entry in attachments]
