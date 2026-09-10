"""Property-based tests for :mod:`starship_notam.parsers.fcc_els_parser`.

Covers ``parse_fcc_els_results_html`` with Hypothesis-generated results-table
HTML. The strategies build a results table from field/value records with:

- random surrounding whitespace on every cell value,
- random call-sign values (blank / all-whitespace / "N/A" in varied
  capitalization, plus ordinary sign values),
- "Current" detail links carrying extra query parameters in arbitrary order,
- interleaved *invalid* rows that are missing a file number, missing a Current
  link, or missing an ``application_seq`` parameter.

Properties (design doc, feature ``fcc-els-scraper``):

- Property 1: One result dict per valid row (Requirements 2.1, 2.2)
- Property 2: Valid rows round-trip their field values (Requirements 2.3, 2.5, 2.6)
- Property 3: Call-sign normalization (Requirements 2.4)
- Property 4: Exclusion invariant for incomplete rows (Requirements 2.7)
- Property 5: Detail label/value extraction (Requirements 3.4, 3.5)

Also covers ``parse_fcc_els_detail_html`` with Hypothesis-generated STA_Print
detail forms, plus example tests for the empty-results (Requirement 2.8) and
unrecognized-detail (Requirement 3.5) edge cases.

Imports only the parsers layer (Requirement 9.2). The parser under test is
imported directly from its module because the package ``__init__`` re-export
is added by a later task.
"""

from __future__ import annotations

import html as html_lib

from hypothesis import given, settings
from hypothesis import strategies as st

from starship_notam.parsers.fcc_els_parser import (
    parse_fcc_els_detail_html,
    parse_fcc_els_results_html,
)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

# Canonical results-table columns, in the order they are rendered below. The
# parser resolves fields by a header-label -> index map, so a fixed order here
# is a faithful sample of the real page.
_FIELD_ORDER = [
    ("file_number", "File Number"),
    ("call_sign", "Call Sign"),
    ("applicant_name", "Applicant Name"),
    ("receipt_date", "Receipt Date"),
    ("status", "Status"),
    ("status_date", "Status Date"),
]

# "Clean" text tokens: alphanumeric only, so BeautifulSoup's
# ``get_text(" ", strip=True)`` + ``.strip()`` round-trips the value exactly
# once random surrounding whitespace is stripped. Kept simple (no filters) so
# input generation stays fast.
_clean_text = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    min_size=1,
    max_size=10,
)

# Ordinary (non-blank, non-"N/A") call-sign values -- alphanumerics are never
# equal to "N/A" so no filtering is needed.
_normal_call_sign = _clean_text

# Values the parser must normalize to "": empty, all-whitespace, or "N/A" in
# any capitalization.
_blank_call_sign = st.sampled_from(
    ["", " ", "   ", "\t", "N/A", "n/a", "N/a", "n/A"]
)

_call_sign_value = st.one_of(_normal_call_sign, _blank_call_sign)

# Random surrounding whitespace the parser must strip away.
_ws = st.text(alphabet=" \t\n", max_size=3)

# A numeric application_seq value.
_seq = st.text(alphabet="0123456789", min_size=1, max_size=6)

# Extra query params (name -> value); names avoid the reserved keys.
_extra_params = st.dictionaries(
    keys=st.text(alphabet="abcdefghijklmnop", min_size=1, max_size=5).filter(
        lambda k: k not in ("application_seq", "mode")
    ),
    values=st.text(alphabet="0123456789abcdef", min_size=1, max_size=5),
    max_size=3,
)


@st.composite
def _valid_records(draw):
    """A record describing one *valid* result row."""
    return {
        "kind": "valid",
        "file_number": draw(_clean_text),
        "call_sign": draw(_call_sign_value),
        "applicant_name": draw(_clean_text),
        "receipt_date": draw(_clean_text),
        "status": draw(_clean_text),
        "status_date": draw(_clean_text),
        "application_seq": draw(_seq),
        "extra_params": draw(_extra_params),
        "lead": draw(_ws),
        "trail": draw(_ws),
        # A concrete permutation of all query params (including application_seq).
        "order": draw(st.randoms(use_true_random=False)),
    }


@st.composite
def _invalid_records(draw):
    """A record describing one *invalid* result row that must be excluded."""
    return {
        "kind": "invalid",
        "defect": draw(
            st.sampled_from(["missing_file", "missing_link", "missing_seq"])
        ),
        "file_number": draw(_clean_text),
        "call_sign": draw(_call_sign_value),
        "applicant_name": draw(_clean_text),
        "receipt_date": draw(_clean_text),
        "status": draw(_clean_text),
        "status_date": draw(_clean_text),
        "application_seq": draw(_seq),
        "extra_params": draw(_extra_params),
        "lead": draw(_ws),
        "trail": draw(_ws),
        "order": draw(st.randoms(use_true_random=False)),
    }


def _build_current_href(application_seq, extra_params, rng):
    """Build a Current-detail href.

    Always contains ``STA_Print.cfm`` and ``mode=current``; when
    ``application_seq`` is not ``None`` it is included among the params. All
    params (including ``application_seq``) are shuffled into an arbitrary order
    so the parser must be robust to param ordering. No param is ever dropped.
    """
    params = list(extra_params.items())
    if application_seq is not None:
        params.append(("application_seq", application_seq))
    rng.shuffle(params)
    query = "&".join(f"{k}={v}" for k, v in params)
    base = "https://apps.fcc.gov/oetcf/els/reports/STA_Print.cfm?mode=current"
    return f"{base}&{query}" if query else base


def _cell(value: str, lead: str = "", trail: str = "") -> str:
    """Render a ``<td>`` cell, escaping and surrounding the value."""
    return f"<td>{lead}{html_lib.escape(value)}{trail}</td>"


def _render_valid_row(rec) -> str:
    """Render a valid row's ``<tr>`` markup for the fixed column order."""
    href = _build_current_href(
        rec["application_seq"], rec["extra_params"], rec["order"]
    )
    lead, trail = rec["lead"], rec["trail"]
    cells = [
        _cell(rec["file_number"], lead, trail),
        _cell(rec["call_sign"], lead, trail),
        _cell(rec["applicant_name"], lead, trail),
        _cell(rec["receipt_date"], lead, trail),
        _cell(rec["status"], lead, trail),
        _cell(rec["status_date"], lead, trail),
        f'<td><a href="{html_lib.escape(href)}">View Form</a></td>',
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def _render_invalid_row(rec) -> str:
    """Render an invalid row that the parser must exclude."""
    defect = rec["defect"]
    lead, trail = rec["lead"], rec["trail"]
    file_number = "" if defect == "missing_file" else rec["file_number"]

    if defect == "missing_link":
        link_cell = "<td>View Form</td>"  # no <a> at all
    elif defect == "missing_seq":
        # A Current link but without an application_seq param.
        href = _build_current_href(None, rec["extra_params"], rec["order"])
        link_cell = f'<td><a href="{html_lib.escape(href)}">View Form</a></td>'
    else:  # missing_file -> a valid link so ONLY the file number is bad
        href = _build_current_href(
            rec["application_seq"], rec["extra_params"], rec["order"]
        )
        link_cell = f'<td><a href="{html_lib.escape(href)}">View Form</a></td>'

    cells = [
        _cell(file_number, lead, trail),
        _cell(rec["call_sign"], lead, trail),
        _cell(rec["applicant_name"], lead, trail),
        _cell(rec["receipt_date"], lead, trail),
        _cell(rec["status"], lead, trail),
        _cell(rec["status_date"], lead, trail),
        link_cell,
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def _header_row() -> str:
    """Render the header row using ``<th>`` so it is not a data row."""
    ths = "".join(f"<th>{label}</th>" for _key, label in _FIELD_ORDER)
    return f"<tr>{ths}<th>View Form</th></tr>"


@st.composite
def _results_html(draw):
    """Generate ``(html, records)`` for a results table.

    ``records`` preserves row order; valid rows carry the field values that
    should survive parsing (surrounding whitespace already accounted for).
    """
    records = draw(
        st.lists(
            st.one_of(_valid_records(), _invalid_records()),
            min_size=0,
            max_size=5,
        )
    )

    rows_markup = [_header_row()]
    for rec in records:
        if rec["kind"] == "valid":
            rows_markup.append(_render_valid_row(rec))
        else:
            rows_markup.append(_render_invalid_row(rec))

    html = "<html><body><table>" + "".join(rows_markup) + "</table></body></html>"
    return html, records


def _expected_call_sign(raw: str) -> str:
    """Mirror the parser's call-sign normalization for assertions."""
    trimmed = raw.strip()
    if not trimmed or trimmed.upper() == "N/A":
        return ""
    return trimmed


# ---------------------------------------------------------------------------
# Property 1
# ---------------------------------------------------------------------------
# Feature: fcc-els-scraper, Property 1: The parser returns exactly one result
# dict per valid results-table row (and none for the header or invalid rows).
@settings(max_examples=100)
@given(_results_html())
def test_property_one_dict_per_valid_row(data):
    html, records = data
    results = parse_fcc_els_results_html(html)

    expected_valid = [r for r in records if r["kind"] == "valid"]

    assert isinstance(results, list)
    assert len(results) == len(expected_valid)
    for item in results:
        assert set(item.keys()) == {
            "file_number",
            "call_sign",
            "applicant_name",
            "receipt_date",
            "status",
            "status_date",
            "current_detail_url",
            "application_seq",
        }


# ---------------------------------------------------------------------------
# Property 2
# ---------------------------------------------------------------------------
# Feature: fcc-els-scraper, Property 2: Valid rows round-trip their field
# values -- file number, applicant, dates, status, the current link, and
# application_seq match the source record (whitespace trimmed).
@settings(max_examples=100)
@given(_results_html())
def test_property_valid_rows_round_trip(data):
    html, records = data
    results = parse_fcc_els_results_html(html)

    expected_valid = [r for r in records if r["kind"] == "valid"]

    # Row order is preserved, so source records zip to parsed results.
    assert len(results) == len(expected_valid)
    for rec, item in zip(expected_valid, results):
        assert item["file_number"] == rec["file_number"]
        assert item["applicant_name"] == rec["applicant_name"]
        assert item["receipt_date"] == rec["receipt_date"]
        assert item["status"] == rec["status"]
        assert item["status_date"] == rec["status_date"]
        # application_seq round-trips regardless of extra params / ordering.
        assert item["application_seq"] == rec["application_seq"]
        # The current detail URL is the Current-mode STA_Print link.
        lowered = item["current_detail_url"].lower()
        assert "sta_print.cfm" in lowered
        assert "mode=current" in lowered
        assert f"application_seq={rec['application_seq']}" in item["current_detail_url"]


# ---------------------------------------------------------------------------
# Property 3
# ---------------------------------------------------------------------------
# Feature: fcc-els-scraper, Property 3: Call-sign normalization -- blank,
# all-whitespace, or "N/A" (any capitalization) becomes "", otherwise the
# trimmed value is preserved.
@settings(max_examples=100)
@given(_results_html())
def test_property_call_sign_normalization(data):
    html, records = data
    results = parse_fcc_els_results_html(html)

    expected_valid = [r for r in records if r["kind"] == "valid"]
    assert len(results) == len(expected_valid)
    for rec, item in zip(expected_valid, results):
        assert item["call_sign"] == _expected_call_sign(rec["call_sign"])
        # A normalized call sign is never a stray "N/A" or whitespace-only.
        assert item["call_sign"].upper() != "N/A"
        assert item["call_sign"] == item["call_sign"].strip()


# ---------------------------------------------------------------------------
# Property 4
# ---------------------------------------------------------------------------
# Feature: fcc-els-scraper, Property 4: Exclusion invariant -- rows missing a
# file number, a Current link, or an application_seq are never present in the
# returned list.
@settings(max_examples=100)
@given(_results_html())
def test_property_exclusion_invariant(data):
    html, records = data
    results = parse_fcc_els_results_html(html)

    # Every returned dict carries all three required identifiers.
    for item in results:
        assert item["file_number"]
        assert item["current_detail_url"] is not None
        assert "sta_print.cfm" in item["current_detail_url"].lower()
        assert "mode=current" in item["current_detail_url"].lower()
        assert item["application_seq"]

    # The count matches only the valid records; invalid ones are excluded.
    expected_valid = [r for r in records if r["kind"] == "valid"]
    assert len(results) == len(expected_valid)

# ---------------------------------------------------------------------------
# Detail-parser building blocks
# ---------------------------------------------------------------------------
# The STA_Print detail page is a print-style label/value form. Each recognized
# ``<tr>`` contributes one ``{label: value}`` entry: the first non-empty cell is
# the (colon-trimmed) label, the next non-empty cell is the value; both are
# trimmed and whitespace-collapsed. Section-header rows (a single cell) and rows
# with an empty value are skipped, and duplicate labels keep the LAST value.

# "Clean" label/value tokens: single alphanumeric words so the parser's
# ``get_text(" ", strip=True)`` + whitespace collapse round-trips them exactly.
# Labels deliberately never end in a colon (the parser strips a trailing colon),
# so the generated label equals the parsed key.
_detail_token = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    min_size=1,
    max_size=12,
)


@st.composite
def _detail_pairs(draw):
    """Generate ``(html, expected)`` for an STA_Print detail form.

    ``expected`` is the ``{label: value}`` dict the parser must return. Labels
    are drawn as a *set* (unique) so ordering/duplicate concerns don't muddy the
    round-trip; the empty/no-field case is included via ``min_size=0``. Random
    surrounding whitespace is added to each cell to exercise trimming/collapsing.
    """
    labels = draw(
        st.lists(_detail_token, min_size=0, max_size=6, unique=True)
    )
    pairs = [(label, draw(_detail_token)) for label in labels]

    rows_markup = []
    for label, value in pairs:
        lead = draw(_ws)
        trail = draw(_ws)
        # A trailing colon on the rendered label is stripped by the parser, so
        # the expected key is the bare label either way; render without one to
        # keep the round-trip exact.
        label_cell = f"<td>{lead}{html_lib.escape(label)}{trail}</td>"
        value_cell = f"<td>{lead}{html_lib.escape(value)}{trail}</td>"
        rows_markup.append(f"<tr>{label_cell}{value_cell}</tr>")

    html = "<html><body><table>" + "".join(rows_markup) + "</table></body></html>"
    expected = dict(pairs)
    return html, expected


# ---------------------------------------------------------------------------
# Property 5
# ---------------------------------------------------------------------------
# Feature: fcc-els-scraper, Property 5: Detail label/value extraction -- for any
# STA_Print detail HTML built from label/value pairs, the parser returns a dict
# mapping each (colon-trimmed, trimmed) label to its trimmed value; a detail page
# with no recognizable label/value structure yields {}.
@settings(max_examples=100)
@given(_detail_pairs())
def test_property_detail_label_value_extraction(data):
    # Validates: Requirements 3.4, 3.5
    html, expected = data
    detail = parse_fcc_els_detail_html(html)

    assert isinstance(detail, dict)
    assert detail == expected
    # No-field detail HTML round-trips to the empty dict.
    if not expected:
        assert detail == {}


# ---------------------------------------------------------------------------
# Example tests
# ---------------------------------------------------------------------------
def test_empty_results_html_returns_empty_list():
    # Validates: Requirement 2.8
    # Empty string -> no table at all.
    assert parse_fcc_els_results_html("") == []
    # HTML with no <table>.
    assert (
        parse_fcc_els_results_html("<html><body><p>No results found.</p></body></html>")
        == []
    )
    # A results table with the header row but no data rows.
    header_only = (
        "<html><body><table>" + _header_row() + "</table></body></html>"
    )
    assert parse_fcc_els_results_html(header_only) == []


def test_unrecognized_detail_html_returns_empty_dict():
    # Validates: Requirement 3.5
    # Empty string.
    assert parse_fcc_els_detail_html("") == {}
    # HTML with no <tr> at all.
    assert (
        parse_fcc_els_detail_html("<html><body><p>Nothing here.</p></body></html>")
        == {}
    )
    # Section-header-only rows (a single spanning cell each) are skipped.
    header_rows = (
        "<html><body><table>"
        "<tr><td colspan='2'>Application Details</td></tr>"
        "<tr><th colspan='2'>Licensee Information</th></tr>"
        "</table></body></html>"
    )
    assert parse_fcc_els_detail_html(header_rows) == {}
    # Rows with a label but an empty value are skipped.
    empty_values = (
        "<html><body><table>"
        "<tr><td>File Number</td><td>   </td></tr>"
        "<tr><td>Call Sign</td><td></td></tr>"
        "</table></body></html>"
    )
    assert parse_fcc_els_detail_html(empty_values) == {}
