"""FCC ELS (Experimental Licensing System) HTML parsing.

Pure-function parser for the FCC ELS Generic Search results page and the
STA_Print application detail page. These functions accept an HTML string and
return structured data without performing any network, database, or filesystem
operations.

Public API:
    parse_fcc_els_results_html(html: str) -> list[dict]
    parse_fcc_els_detail_html(html: str) -> dict
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup

from starship_notam.core.logging import logger


# Header-label -> canonical result-dict field key. Labels are matched
# case-insensitively against a whitespace-normalized header cell text.
_HEADER_FIELD_MAP = {
    "file number": "file_number",
    "call sign": "call_sign",
    "applicant": "applicant_name",
    "applicant name": "applicant_name",
    "receipt date": "receipt_date",
    "status": "status",
    "status date": "status_date",
}

# Labels that must be present in a header row for it to be treated as the
# results table header.
_REQUIRED_HEADER_LABELS = ("file number",)


def _normalize_label(text: str) -> str:
    """Lower-case and collapse whitespace in a header label."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _build_header_map(header_cells: list) -> dict[str, int]:
    """Map canonical field keys to the column index of their header cell.

    Parameters
    ----------
    header_cells : list
        The header row's ``<th>``/``<td>`` cell elements, in order.

    Returns
    -------
    dict[str, int]
        A mapping from canonical field key (e.g. ``"file_number"``) to the
        zero-based column index at which that field's values appear.
    """
    header_map: dict[str, int] = {}
    for index, cell in enumerate(header_cells):
        label = _normalize_label(cell.get_text(" ", strip=True))
        field = _HEADER_FIELD_MAP.get(label)
        if field is not None and field not in header_map:
            header_map[field] = index
    return header_map


def _find_results_table(soup: BeautifulSoup) -> tuple | None:
    """Locate the results table and return ``(table, header_map)``.

    The results table is identified as the first table whose header row
    contains the expected column labels (at minimum a "File Number" column).
    Returns ``None`` when no such table is found.
    """
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # The header row is the first row that contains any recognizable
        # column labels.
        for row in rows:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            header_map = _build_header_map(cells)
            if all(
                label in {_normalize_label(c.get_text(" ", strip=True)) for c in cells}
                for label in _REQUIRED_HEADER_LABELS
            ) and "file_number" in header_map:
                return table, header_map
            # Only the first non-empty row of a table is considered as a
            # potential header; move on to the next table otherwise.
            break

    return None


def _cell_text(cells: list, header_map: dict[str, int], field: str) -> str:
    """Return the stripped text of the cell for ``field``, or ``""``."""
    index = header_map.get(field)
    if index is None or index >= len(cells):
        return ""
    return cells[index].get_text(" ", strip=True).strip()


def _normalize_call_sign(value: str) -> str:
    """Normalize a call-sign value.

    Returns an empty string when the trimmed value is empty, all-whitespace,
    or equals "N/A" (case-insensitive); otherwise returns the trimmed value.
    """
    trimmed = value.strip()
    if not trimmed or trimmed.upper() == "N/A":
        return ""
    return trimmed


def _find_current_detail_link(row) -> str | None:
    """Find the "View Form -> Current" detail link href in a data row.

    Matches an ``<a>`` whose href contains both ``STA_Print.cfm`` and
    ``mode=current`` as substrings (case-insensitive). Returns the href string
    or ``None`` when no matching link is present.
    """
    for anchor in row.find_all("a", href=True):
        href = anchor["href"]
        lowered = href.lower()
        if "sta_print.cfm" in lowered and "mode=current" in lowered:
            return href
    return None


def parse_fcc_els_results_html(html: str) -> list[dict]:
    """Parse FCC ELS Generic Search results HTML into application rows.

    Parameters
    ----------
    html : str
        Raw HTML content from the FCC ELS Generic Search results page.

    Returns
    -------
    list[dict]
        One dict per valid application row. Each dict has keys:
        ``file_number``, ``call_sign``, ``applicant_name``, ``receipt_date``,
        ``status``, ``status_date``, ``current_detail_url``, and
        ``application_seq``. Returns ``[]`` when the results table has no
        data rows (or no results table is present).

    Notes
    -----
    A row is excluded (and logged) when it is missing a ``file_number``, a
    "Current" detail link, or an ``application_seq`` value.
    """
    soup = BeautifulSoup(html, "html.parser")

    found = _find_results_table(soup)
    if found is None:
        return []

    table, header_map = found

    rows = table.find_all("tr")
    results: list[dict] = []

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            # Header row (uses <th>) or a spacer row with no data cells.
            continue

        file_number = _cell_text(cells, header_map, "file_number")
        call_sign = _normalize_call_sign(
            _cell_text(cells, header_map, "call_sign")
        )
        applicant_name = _cell_text(cells, header_map, "applicant_name")
        receipt_date = _cell_text(cells, header_map, "receipt_date")
        status = _cell_text(cells, header_map, "status")
        status_date = _cell_text(cells, header_map, "status_date")

        href = _find_current_detail_link(row)

        application_seq = None
        if href is not None:
            application_seq = parse_qs(urlparse(href).query).get(
                "application_seq", [None]
            )[0]

        # Exclude rows that are missing any of the required identifiers.
        if not file_number or href is None or not application_seq:
            row_label = file_number or "<unknown file number>"
            logger.info(
                "Excluding FCC ELS result row '%s': "
                "file_number=%r, current_detail_url=%r, application_seq=%r",
                row_label,
                file_number,
                href,
                application_seq,
            )
            continue

        results.append(
            {
                "file_number": file_number,
                "call_sign": call_sign,
                "applicant_name": applicant_name,
                "receipt_date": receipt_date,
                "status": status,
                "status_date": status_date,
                "current_detail_url": href,
                "application_seq": application_seq,
            }
        )

    return results


def _detail_cell_text(cell) -> str:
    """Return the stripped, whitespace-collapsed text of a detail cell."""
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()


# The STA "Explanation" (why an STA is necessary) fieldset renders its label and
# free-text answer inside a *single* table cell, so the generic label/value row
# extraction (which needs two cells) never captures it. We locate the fieldset
# by its ``<legend>`` text and pull the answer out of the trailing content span.
_EXPLANATION_LEGEND = "explanation"
_EXPLANATION_PROMPT_RE = re.compile(
    r"please explain.*why an sta is necessary", re.IGNORECASE
)
# Canonical key under which the extracted explanation value is stored.
_EXPLANATION_KEY = "Explanation"


def _extract_explanation(soup: BeautifulSoup) -> str:
    """Extract the STA "Explanation" free-text answer, or ``""`` if absent.

    The answer lives in a ``<fieldset>`` whose ``<legend>`` reads "Explanation"
    and whose single cell contains a bold prompt ("Please explain ... why an STA
    is necessary:") followed by the answer in a ``small-content`` span. We return
    the answer text, whitespace-collapsed, preferring the ``small-content`` span
    and falling back to the cell text with the prompt removed.
    """
    for fieldset in soup.find_all("fieldset"):
        legend = fieldset.find("legend")
        if legend is None:
            continue
        if _normalize_label(legend.get_text(" ", strip=True)) != _EXPLANATION_LEGEND:
            continue

        # Preferred: the answer is the (last) small-content span in the cell.
        answer_spans = fieldset.select("span.small-content")
        for span in reversed(answer_spans):
            text = re.sub(r"\s+", " ", span.get_text(" ", strip=True)).strip()
            if text:
                return text

        # Fallback: take the fieldset text, drop the legend and the bold prompt.
        cell_text = re.sub(r"\s+", " ", fieldset.get_text(" ", strip=True)).strip()
        cell_text = re.sub(
            r"^\s*explanation\s*", "", cell_text, flags=re.IGNORECASE
        )
        cell_text = _EXPLANATION_PROMPT_RE.sub("", cell_text)
        return cell_text.strip(" :").strip()

    return ""


def parse_fcc_els_detail_html(html: str) -> dict:
    """Parse an STA_Print detail-page HTML into a ``{label: value}`` dict.

    The STA_Print application detail page is a print-style label/value form.
    Each recognized row contributes one entry, keyed by the (colon-trimmed)
    label and valued by the corresponding cell text.

    Parameters
    ----------
    html : str
        Raw HTML content from an FCC ELS STA_Print detail page.

    Returns
    -------
    dict
        A mapping from field label to its extracted text value. Returns ``{}``
        when no label/value pairs are recognized (tolerant of malformed or
        partial pages — unrecognized structure yields ``{}`` rather than
        raising).

    Notes
    -----
    For each ``<tr>`` with two or more ``<td>``/``<th>`` cells, the first
    non-empty cell is treated as the label and the next non-empty cell as the
    value; both are trimmed and a trailing colon is stripped from the label.
    Section-header rows (a single spanning cell) and rows with an empty value
    are skipped. Duplicate labels keep the last occurrence.

    Additionally, the STA "Explanation" answer (why an STA is necessary) — whose
    label and value share a single cell and so is invisible to the row loop — is
    extracted from its ``<fieldset>`` and stored under the ``"Explanation"`` key
    when present.
    """
    soup = BeautifulSoup(html, "html.parser")

    detail: dict[str, str] = {}

    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        # Section-header rows (a single spanning cell) and empty rows are
        # skipped; a label/value pair requires at least two cells.
        if len(cells) < 2:
            continue

        # The first non-empty cell is the label; the next non-empty cell after
        # it is the value.
        texts = [_detail_cell_text(cell) for cell in cells]

        label = ""
        value = ""
        label_index = None
        for index, text in enumerate(texts):
            if text:
                label = text
                label_index = index
                break

        if not label or label_index is None:
            continue

        for text in texts[label_index + 1:]:
            if text:
                value = text
                break

        # Strip a single trailing colon from the label ("File Number:" ->
        # "File Number").
        if label.endswith(":"):
            label = label[:-1].strip()

        # Skip rows with an empty label (after colon trimming) or empty value.
        if not label or not value:
            continue

        # Duplicate labels keep the last occurrence.
        detail[label] = value

    # The STA "Explanation" answer lives in a single cell (label + value in one
    # <td>), so the row loop above cannot capture it. Extract it separately and
    # store it under a dedicated key when present.
    explanation = _extract_explanation(soup)
    if explanation:
        detail[_EXPLANATION_KEY] = explanation

    return detail
