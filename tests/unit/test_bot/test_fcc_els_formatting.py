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


@st.composite
def _detail_strategy(draw):
    """Generate a detail mapping (label -> value) with HTML-special content."""
    labels = draw(
        st.lists(_htmlish_text(), min_size=0, max_size=5, unique=True)
    )
    return {label: draw(_htmlish_text()) for label in labels}


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
    app["_detail_source"] = detail  # kept for assertions; ignored by formatter
    return app


def _strip_allowed_tags(text: str) -> str:
    """Remove the fixed set of allowed structural tags from *text*."""
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


def test_formatter_escapes_special_chars_in_detail_values():
    """Detail labels/values containing special chars are escaped inside the
    expandable blockquote."""
    app = {
        "applicant_name": "SpaceX",
        "file_number": "0123-EX-ST-2025",
        "call_sign": "WX2XAB",
        "status": "Granted",
        "receipt_date": "01/01/2025",
        "status_date": "01/15/2025",
        "detail_json": {"Freq <MHz>": "2000 & up", "Note": "<b>bold</b>"},
    }
    out = formatting.format_fcc_els_application(app)

    assert "<blockquote expandable>" in out
    assert "</blockquote>" in out
    assert "Freq &lt;MHz&gt;: 2000 &amp; up" in out
    # The detail's literal HTML tag must be escaped, not passed through raw.
    assert "&lt;b&gt;bold&lt;/b&gt;" in out
