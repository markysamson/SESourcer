"""Small text helpers shared by parsing and fetching."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_BLANK = re.compile(r"\n{3,}")


_BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\u061c]")


def decode_text(value: str) -> str:
    """Unescape HTML (including double-escaped entities) and collapse whitespace."""
    text = value or ""
    for _ in range(3):
        nxt = unescape(text)
        if nxt == text:
            break
        text = nxt
    text = _BIDI.sub("", text)
    text = _TAG.sub(" ", text)
    return " ".join(text.split())


class _JobTextParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "form", "iframe"}
    _BREAK = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._in_title = False
        self.parts: list[str] = []
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self._BREAK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "li", "h1", "h2", "h3", "tr", "section"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._skip:
            return
        self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Return ``(title, visible text)`` from a job-posting page."""
    parser = _JobTextParser()
    parser.feed(html or "")
    parser.close()
    title = " ".join("".join(parser.title_parts).split())
    lines: list[str] = []
    for raw in "".join(parser.parts).splitlines():
        line = _WS.sub(" ", raw).strip()
        if line:
            lines.append(line)
    text = "\n".join(lines)
    text = _BLANK.sub("\n\n", text).strip()
    return title[:300], text[:40000]
