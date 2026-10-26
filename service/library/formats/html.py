"""HTML saved from Microsoft Word."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from ...common.text import decode_bytes
from .blocks import clean


class _BookHTML(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "template", "head", "xml"})
    _BLOCK = frozenset(
        {"p", "div", "li", "tr", "td", "th", "table", "blockquote", "pre", "dd", "dt", "br"}
    )
    _HEADING = {f"h{n}": n for n in range(1, 7)}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple] = []
        self.title_parts: list[str] = []
        self._buffer: list[str] = []
        self._skip = 0
        self._in_title = False
        self._heading: int | None = None
        self._body = False

    def _flush(self) -> None:
        text = clean("".join(self._buffer))
        self._buffer = []
        if text:
            self.blocks.append(
                ("heading", self._heading, text, True) if self._heading else ("para", text)
            )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "body":
            self._body = True
        elif tag == "title":
            self._in_title = True
        elif tag in self._SKIP:
            self._skip += 1
        elif tag in self._HEADING:
            self._flush()
            self._heading = self._HEADING[tag]
        elif tag in self._BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._HEADING:
            self._flush()
            self._heading = None
        elif tag in self._BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._body and not self._skip:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def extract_html(data: bytes) -> dict[str, Any]:
    text, _ = decode_bytes(data)
    parser = _BookHTML()
    parser.feed(text)
    parser.close()
    title = clean("".join(parser.title_parts))
    return {
        "blocks": parser.blocks,
        "metadata": {"title": title} if title else {},
        "fragment": False,
    }
