"""Property test for :func:`starship_notam.bot.formatting.format_fcc_els_application`.

Exercises **Property 13** from the fcc-els-scraper design: the formatter output
is well-formed and escaped. The formatter is a pure standard-library function
that performs no network or database I/O, so the tests use plain generated
input dicts with no mocking or fixtures.

Property tests use Hypothesis (``@settings(max_examples=100)``) and are tagged
``# Feature: fcc-els-scraper, Property N: <text>``.

Covers Requirement 7.3.
"""

from __future__ import annotations

import html
import json
import re

from hypothesis import given, settings, strategies as st

from starship_notam.bot import formatting


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
# Text that may embed the HTML special characters we care about (``<``, ``>``,
# ``&``) mixed in with ordinary characters, so generated field values regularly
# exercise the escaping path. We interleave a small alphabet that always
# contains the three special characters with arbitrary (non-surrogate) text.
_special = st.sampled_from(["<", ">", "&"])
_ordinary = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=0,
    max_size=10,
)


@st.composite
def _htmlish_text(draw):
    """Generate text likely to contain ``<``, ``>`` and/or ``&``."""
    chunks = draw(
        st.lists(st.one_of(_special, _ordinary), min_size=0, max_size=8)
    )
    return "".join(chunks)


# The scalar fields the formatter reads off the application dict.
_SCALAR_FIELDS = [
    "applicant_name",
    "file_number",
    "call_sign",
    "status",
    "receipt_date",
    "status_date",
]

# The literal structural markup the formatter is allowed to emit. These are the
# ONLY unescaped ``<``/``>`` sequences that may legitimately appear in output.
_ALLOWED_TAGS = [
    "<b>",
    "</b>",
    "<blockquote expandable>",
    "</blockquote>",
]

# The two detail keys the formatter renders inside the expandable blockquote:
# the STA_Print "purpose of operation" field and the parser's "Explanation" key.
_PURPOSE_KEY = "Please explain the purpose of operation"
_EXPLANATION_KEY = "Explanation"


@st.composite
def _detail_strategy(draw):
    """Generate a detail mapping with HTML-special content.

    Only the two keys the formatter reads (purpose + explanation) are populated,
    each optionally present, since any other keys are ignored by the formatter.
    """
    detail = {}
    if draw(st.booleans()):
        detail[_PURPOSE_KEY] = draw(_htmlish_text())
    if draw(st.booleans()):
        detail[_EXPLANATION_KEY] = draw(_htmlish_text())
    return detail


@st.composite
def _app_strategy(draw):
    """Generate an application dict whose field values embed ``<``, ``>``, ``&``."""
    app = {field: draw(_htmlish_text()) for field in _SCALAR_FIELDS}
    detail = draw(_detail_strategy())
    # Randomly deliver detail as a dict or as a JSON string (the formatter
    # accepts both, mirroring format_beach_alert's periods_json handling).
    if draw(st.booleans()):
        app["detail_json"] = json.dumps(detail, ensure_ascii=False)
    else:
        app["detail_json"] = detail
    # Optionally include a detail URL so the link-rendering path is exercised.
    if draw(st.booleans()):
        app["current_detail_url"] = draw(_htmlish_text())
    app["_detail_source"] = detail  # kept for assertions; ignored by formatter
    return app


def _strip_allowed_tags(text: str) -> str:
    """Remove the fixed set of allowed structural tags from *text*.

    The optional source link is emitted as ``<a href="URL">...</a>`` where URL
    is produced by ``html.escape(..., quote=True)`` (so it contains no raw
    ``<``/``>``/``&``). We strip the whole opening anchor tag and the closing
    tag before checking for leaked special characters.
    """
    text = re.sub(r'<a href="[^"]*">', "", text)
    text = text.replace("</a>", "")
    for tag in _ALLOWED_TAGS:
        text = text.replace(tag, "")
    return text


# ---------------------------------------------------------------------------
# Property 13
# ---------------------------------------------------------------------------
@settings(max_examples=100)
@given(app=_app_strategy())
def test_formatter_output_is_well_formed_and_escaped(app):
    # Feature: fcc-els-scraper, Property 13: Formatter output is well-formed and escaped
    """For any application dict, the rendered string contains the applicant
    name and file number HTML-escaped, uses ``<b>`` label tags, and never emits
    unescaped ``<``, ``>`` or ``&`` originating from input field values (Req 7.3)."""
    detail_source = app.pop("_detail_source")
    out = formatting.format_fcc_els_application(app)

    # (1) It is an HTML message that uses <b> tags for labels (Req 7.3).
    assert "<b>" in out and "</b>" in out
    assert out.startswith("<b>Новая заявка FCC ELS</b>")

    # (2) The applicant name and file number appear, HTML-escaped.
    escaped_applicant = html.escape(str(app["applicant_name"]))
    escaped_file_number = html.escape(str(app["file_number"]))
    assert escaped_applicant in out
    assert escaped_file_number in out

    # (3) No unescaped HTML special characters from the input leak through.
    # Every legitimate ``<``/``>`` in the output belongs to one of the fixed
    # structural tags; after removing those tags, no raw ``<`` or ``>`` may
    # remain (they must all have become ``&lt;``/``&gt;``). Likewise every
    # ``&`` must be the start of an HTML entity, never a raw input ampersand.
    residual = _strip_allowed_tags(out)
    assert "<" not in residual, f"unescaped '<' leaked: {residual!r}"
    assert ">" not in residual, f"unescaped '>' leaked: {residual!r}"

    # Ampersands: after removing the allowed tags (which contain no ``&``),
    # every ``&`` must begin a valid escape entity produced by html.escape,
    # i.e. one of &lt; &gt; &amp; &#x27; &quot;.
    for match in re.finditer(r"&", residual):
        tail = residual[match.start(): match.start() + 6]
        assert re.match(r"&(lt|gt|amp|#x27|quot);", tail), (
            f"raw '&' leaked (not an escape entity): {tail!r}"
        )


# ---------------------------------------------------------------------------
# Focused examples reinforcing the property
# ---------------------------------------------------------------------------
def test_formatter_escapes_special_chars_in_scalar_fields():
    """Angle brackets and ampersands in scalar fields are escaped, not raw."""
    app = {
        "applicant_name": "Space & <Exploration>",
        "file_number": "0123<EX>&ST",
        "call_sign": "",
        "status": "Granted & <ok>",
        "receipt_date": "01/01/2025",
        "status_date": "01/15/2025",
        "detail_json": {},
    }
    out = formatting.format_fcc_els_application(app)

    assert "Space &amp; &lt;Exploration&gt;" in out
    assert "0123&lt;EX&gt;&amp;ST" in out
    # The raw unescaped forms must not appear anywhere.
    assert "<Exploration>" not in out
    assert "0123<EX>" not in out


def test_formatter_renders_purpose_and_explanation_escaped():
    """The purpose and explanation values are rendered under their own labels
    inside the expandable blockquote, with special chars escaped."""
    app = {
        "applicant_name": "SpaceX",
        "file_number": "0123-EX-ST-2025",
        "call_sign": "WX2XAB",
        "status": "Granted",
        "receipt_date": "01/01/2025",
        "status_date": "01/15/2025",
        "detail_json": {
            "Please explain the purpose of operation": "Testing 2000 & up",
            "Explanation": "STA needed for <ground> testing",
            # An unrelated detail key must NOT appear in the output.
            "Note": "<b>ignored</b>",
        },
    }
    out = formatting.format_fcc_els_application(app)

    assert "<blockquote expandable>" in out
    assert "</blockquote>" in out
    # Both fields render under their Russian labels, escaped.
    assert "<b>Цель эксплуатации:</b> Testing 2000 &amp; up" in out
    assert "<b>Обоснование:</b> STA needed for &lt;ground&gt; testing" in out
    # Unrelated detail fields are not rendered.
    assert "ignored" not in out


def test_formatter_renders_source_link():
    """A root-relative ``current_detail_url`` is resolved to an absolute,
    escaped link to the FCC ELS application."""
    app = {
        "applicant_name": "SpaceX",
        "file_number": "0123-EX-ST-2025",
        "call_sign": "WX2XAB",
        "status": "Granted",
        "receipt_date": "01/01/2025",
        "status_date": "01/15/2025",
        "detail_json": {},
        "current_detail_url": (
            "/oetcf/els/reports/STA_Print.cfm"
            "?mode=current&application_seq=153622"
        ),
    }
    out = formatting.format_fcc_els_application(app)

    # Absolute URL, with the ampersand in the query escaped for HTML.
    assert (
        '<a href="https://apps.fcc.gov/oetcf/els/reports/STA_Print.cfm'
        "?mode=current&amp;application_seq=153622\">" in out
    )
    assert "Открыть заявку</a>" in out


def test_formatter_omits_blockquote_and_link_when_absent():
    """With no purpose/explanation and no detail URL, neither the blockquote
    nor the link is emitted."""
    app = {
        "applicant_name": "SpaceX",
        "file_number": "0123-EX-ST-2025",
        "call_sign": "WX2XAB",
        "status": "Granted",
        "receipt_date": "01/01/2025",
        "status_date": "01/15/2025",
        "detail_json": {"Note": "unrelated"},
    }
    out = formatting.format_fcc_els_application(app)

    assert "<blockquote expandable>" not in out
    assert "<a href=" not in out
