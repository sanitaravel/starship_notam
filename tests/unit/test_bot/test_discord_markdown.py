"""Telegram HTML from the formatters becomes safe Discord markdown."""

from __future__ import annotations

import pytest

from src.bot.discord_markdown import split_message, to_discord_markdown
from src.bot.formatting import format_compass_file


@pytest.mark.parametrize(
    "html_text, expected",
    [
        ("<b>Файл:</b> deck.pdf", "**Файл:** deck.pdf"),
        ("<i>a</i> <code>b</code>", "*a* `b`"),
        ('<a href="https://x.org/a">Ссылка</a>', "[Ссылка](https://x.org/a)"),
        ("Tom &amp; Jerry &lt;3", "Tom & Jerry <3"),
        ("<u>kept</u>", "kept"),
    ],
)
def test_tags_are_translated(html_text, expected):
    assert to_discord_markdown(html_text) == expected


def test_link_target_parentheses_and_spaces_are_encoded():
    md = to_discord_markdown('<a href="https://x.org/a (1).pdf">PDF</a>')

    assert md == "[PDF](https://x.org/a%20%281%29.pdf)"


def test_source_text_cannot_become_markdown():
    md = to_discord_markdown("snake_case *star* ~x~ `t` |p| [a](b)")

    assert md == r"snake\_case \*star\* \~x\~ \`t\` \|p\| \[a\](b)"


@pytest.mark.parametrize(
    "line", ["# Heading", "## Sub", "-# small", "> quote", "- item", "+ item", "1. item"]
)
def test_line_start_markers_are_escaped(line):
    md = to_discord_markdown(f"<b>X</b>\n{line}")

    assert md == f"**X**\n\\{line}"


def test_marker_mid_line_and_hashtags_are_left_alone():
    md = to_discord_markdown("Flight - 1. done\n#SpaceUpdates #NOTAM")

    assert md == "Flight - 1. done\n#SpaceUpdates #NOTAM"


def test_blockquote_prefixes_every_line():
    md = to_discord_markdown(
        "Подробности:\n\n<blockquote expandable><b>A:</b> one\n\ntwo</blockquote>\n\n#NOTAM"
    )

    assert md == "Подробности:\n\n> **A:** one\n>\n> two\n\n#NOTAM"


def test_unclosed_tags_are_flushed():
    assert to_discord_markdown('<a href="https://x.org">t') == "[t](https://x.org)"


def test_real_formatter_output():
    html_text = format_compass_file(
        {"filename": "Starship_Flight_15.pdf", "uploaded_at": "20.10.2026", "file_uuid": "u-1"}
    )

    md = to_discord_markdown(html_text)

    assert md.startswith("**📊 Новый файл в COMPASS (Master Slide Deck)**\n\n")
    assert "**Файл:** Starship\\_Flight\\_15.pdf" in md
    assert "[Скачать файл](https://compass.atfm.aero/public_svcdynamic/getfile?" in md
    assert md.endswith("#SpaceUpdates #COMPASS")
    assert "<" not in md


def test_split_keeps_short_text_whole():
    assert split_message("  short  ", 2000) == ["short"]


def test_split_prefers_paragraph_then_line_breaks():
    text = "a" * 6 + "\n\n" + "b" * 6 + "\n" + "c" * 6

    assert split_message(text, 10) == ["a" * 6, "b" * 6, "c" * 6]


def test_split_cuts_hard_without_breaks():
    assert split_message("x" * 25, 10) == ["x" * 10, "x" * 10, "x" * 5]
