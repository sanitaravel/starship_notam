"""Convert the Telegram HTML built by ``bot.formatting`` to Discord markdown.

The formatters write Telegram's HTML subset; Discord renders markdown. This
module translates the tags they use and escapes everything else, so text from
a source can never turn into markdown by accident (a line starting with
``# `` would become a heading, ``*`` would start italics):

    <b>, <strong>        -> **bold**
    <i>, <em>            -> *italic*
    <code>               -> `code`
    <a href="url">t</a>  -> [t](url)
    <blockquote>         -> every line prefixed with "> " (Discord has no
                            collapsed quote, so ``expandable`` is dropped)

Other tags are dropped and their text kept. Standard library only.

Public API:
    to_discord_markdown(html_text) -> str
    split_message(text, limit) -> list[str]
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import quote

# Characters that start inline markdown anywhere in a line.
_INLINE_SPECIAL = re.compile(r"([\\*_~`|\[\]])")
# Markers that only count at the start of a line: headings ("# ", "-# "),
# quotes, bullet and numbered lists.
_LINE_START_SPECIAL = re.compile(r"^(\s*)(#{1,3}|-#|>|-|\+|\d+\.)(?=\s)")

_WRAP = {"b": "**", "strong": "**", "i": "*", "em": "*", "code": "`"}


def _escape_line_start(line: str) -> str:
    return _LINE_START_SPECIAL.sub(r"\1\\\2", line)


def _escape(text: str, at_line_start: bool) -> str:
    """Escape markdown in *text*; its first line starts a line when *at_line_start*."""
    lines = _INLINE_SPECIAL.sub(r"\\\1", text).split("\n")
    return "\n".join(
        _escape_line_start(line) if i or at_line_start else line
        for i, line in enumerate(lines)
    )


def _quote_lines(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.split("\n"))


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # One output buffer per open container: the message itself, then each
        # open <a> or <blockquote>, whose text is rewritten when it closes.
        self._stack: list[tuple[str, dict, list[str]]] = [("", {}, [])]

    @property
    def _out(self) -> list[str]:
        return self._stack[-1][2]

    def _at_line_start(self) -> bool:
        for _tag, _attrs, out in reversed(self._stack):
            text = "".join(out)
            if text:
                return text.endswith("\n")
            # An empty <a> or <blockquote> buffer: look at what precedes it.
        return True

    def handle_starttag(self, tag, attrs):
        if tag in _WRAP:
            self._out.append(_WRAP[tag])
        elif tag in ("a", "blockquote"):
            self._stack.append((tag, dict(attrs), []))

    def handle_endtag(self, tag):
        if tag in _WRAP:
            self._out.append(_WRAP[tag])
            return
        if tag not in ("a", "blockquote") or self._stack[-1][0] != tag:
            return
        _tag, attrs, out = self._stack.pop()
        inner = "".join(out)
        if tag == "a":
            href = attrs.get("href") or ""
            # Parentheses and spaces would end the link target early.
            href = quote(href, safe=":/?#[]@!$&'*+,;=%~-._")
            self._out.append(f"[{inner}]({href})" if href else inner)
        else:
            self._out.append(_quote_lines(inner.strip("\n")))

    def handle_data(self, data):
        self._out.append(_escape(data, self._at_line_start()))

    def result(self) -> str:
        self.close()
        # Close anything the HTML left open.
        while len(self._stack) > 1:
            self.handle_endtag(self._stack[-1][0])
        return "".join(self._out)


def to_discord_markdown(html_text: str) -> str:
    """Translate Telegram-style HTML into escaped Discord markdown."""
    converter = _Converter()
    converter.feed(html_text or "")
    return converter.result()


def split_message(text: str, limit: int) -> list[str]:
    """Split *text* into chunks of at most *limit* characters.

    Cuts at the last paragraph break that fits, then the last line break,
    then hard at *limit*, so a long post becomes several readable messages.
    """
    chunks = []
    rest = text.strip()
    while len(rest) > limit:
        window = rest[: limit + 1]
        cut = window.rfind("\n\n")
        if cut <= 0:
            cut = window.rfind("\n")
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks
