"""COMPASS Master Slide Deck file-list parsing.

Pure-function parser for the JSON returned by the COMPASS public endpoint
``public_svcdynamic/?key=public_getpublicslidelist``, which backs the
"Master Slide Deck" grid on ``vpublic_anspdetail.jsp?view=3``. The payload
looks like::

    {"rows": [{"fileuuid": "...", "createtimestamp_format": "05/Oct/2026 14:26",
               "filename": "Host Master - ... .pptx"}, ...]}

It performs no network, database, or filesystem operations.

Public API:
    parse_compass_file_list(payload: dict | str) -> list[dict]
"""

from __future__ import annotations

import json
from typing import Any

from starship_notam.core.logging import logger


def parse_compass_file_list(payload: Any) -> list[dict]:
    """Normalize the slide-list payload into a list of file records.

    Parameters
    ----------
    payload : dict or str
        The parsed JSON, or the raw JSON text (the server answers with
        ``text/plain``).

    Returns
    -------
    list[dict]
        One record per file, in the order the server returned them (newest
        first), each with the keys ``file_uuid``, ``filename`` and
        ``uploaded_at`` (the upload time exactly as the site shows it). Rows
        without a ``fileuuid`` are dropped. Junk input yields ``[]``.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            logger.error("COMPASS file list is not valid JSON")
            return []
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        logger.error("COMPASS file list has no 'rows' list")
        return []

    records = []
    for row in payload["rows"]:
        if not isinstance(row, dict):
            continue
        file_uuid = str(row.get("fileuuid") or "").strip()
        if not file_uuid:
            logger.info("Skipping COMPASS row without fileuuid: %s", row)
            continue
        records.append(
            {
                "file_uuid": file_uuid,
                "filename": str(row.get("filename") or "").strip(),
                "uploaded_at": str(row.get("createtimestamp_format") or "").strip(),
            }
        )
    return records
