"""Trimmed NOTAM captions must stay valid Telegram HTML.

Regression test for fix-plan step 7: the caption used to be cut at a fixed
length *after* escaping, which could split an entity such as ``&amp;`` or a
tag and make Telegram reject the whole caption.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from starship_notam.bot import formatting

LIMIT = formatting._CAPTION_LIMIT
# An "&" that does not start a complete entity means one was cut in half.
BROKEN_ENTITY = re.compile(r"&(?!(?:amp|lt|gt|quot|#x27);)")


def _assert_valid(caption: str, code_tag: str) -> None:
    assert len(caption) <= LIMIT
    assert not BROKEN_ENTITY.search(caption)
    assert caption.count("<blockquote") == caption.count("</blockquote>")
    assert caption.count("<b>") == caption.count("</b>")
    assert caption.endswith(code_tag)


def test_cut_never_splits_an_entity():
    # Try many lengths so the cut lands on every offset of "&amp;" / "&lt;".
    for pad in range(12):
        parsed = {"E": "X" * pad + "A&B<C>D " * 400}
        caption = formatting.build_notam_caption("A0001_26", parsed)
        _assert_valid(caption, "#A000126")
        assert caption.rstrip().endswith("…</blockquote>\n\n#SpaceUpdates #NOTAM #A000126")


def test_short_caption_is_unchanged():
    parsed = {"E": "STARSHIP & SUPER HEAVY <TEST>"}
    caption = formatting.build_notam_caption("A0001_26", parsed)

    assert "STARSHIP &amp; SUPER HEAVY &lt;TEST&gt;</blockquote>" in caption
    assert "…" not in caption


def test_long_schedule_without_details_still_fits():
    # A daily window over ~3 months expands to ~90 schedule lines.
    start = datetime(2026, 7, 1, 8, 0)
    parsed = {
        "B": start.isoformat() + "Z",
        "C": (start + timedelta(days=90)).isoformat() + "Z",
        "D": "DLY 0800-2059",
    }
    caption = formatting.build_notam_caption("A0002_26", parsed)

    _assert_valid(caption, "#A000226")
    # Cuts happen on whole lines only.
    assert all(
        line.startswith(("<b>", "#")) or re.match(r"^\w+ \d\d, \d\d:\d\d - \d\d:\d\d$", line)
        for line in caption.split("\n")
        if line
    )
