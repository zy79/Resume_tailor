from __future__ import annotations

import html
import re
from collections.abc import Iterator

from docxtpl import RichText

_INLINE_MARKER = re.compile(r"\*\*(?P<bold>.+?)\*\*|\*(?P<italic>[^*]+?)\*", re.DOTALL)
_MARKDOWN_SPECIALS = re.compile(r"([\\`*_{}\[\]()#+\-.!|])")


def _segments(value: str) -> Iterator[tuple[str, bool, bool]]:
    position = 0
    for match in _INLINE_MARKER.finditer(value):
        if match.start() > position:
            yield value[position : match.start()], False, False
        bold_text = match.group("bold")
        italic_text = match.group("italic")
        if bold_text is not None:
            yield bold_text, True, False
        elif italic_text is not None:
            yield italic_text, False, True
        position = match.end()
    if position < len(value):
        yield value[position:], False, False


def to_rich_text(value: str) -> RichText:
    result = RichText()
    for text, bold, italic in _segments(value):
        result.add(text, bold=bold, italic=italic)
    return result


def to_html_inline(value: str) -> str:
    parts: list[str] = []
    for text, bold, italic in _segments(value):
        escaped = html.escape(text, quote=True).replace("\n", "<br>")
        if bold:
            escaped = f"<strong>{escaped}</strong>"
        elif italic:
            escaped = f"<em>{escaped}</em>"
        parts.append(escaped)
    return "".join(parts)


def to_markdown_inline(value: str) -> str:
    parts: list[str] = []
    for text, bold, italic in _segments(value):
        escaped = html.escape(text, quote=False)
        escaped = _MARKDOWN_SPECIALS.sub(r"\\\1", escaped)
        if bold:
            escaped = f"**{escaped}**"
        elif italic:
            escaped = f"*{escaped}*"
        parts.append(escaped)
    return "".join(parts)


def plain_text(value: str) -> str:
    return "".join(text for text, _, _ in _segments(value))