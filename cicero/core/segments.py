"""Packing a paragraph's runs into one string for the translator, and unpacking the translation.

A PowerPoint paragraph is a list of *runs*: pieces of text that each carry their own
formatting (a bold word, a link, a different colour). Translating runs one by one gives
poor results, because the translator only sees sentence fragments. Instead the whole
paragraph is sent as HTML, each run wrapped in ``<span id="N">``. Google Cloud Translation
keeps tags in place and moves them with the words they wrap, so the translated text of
each run can be put back into the run it came from, keeping its formatting.

Whitespace at the edges of runs and tabs inside them would be lost in HTML, so edges are
stripped before sending and restored afterwards, and tabs travel as empty marker tags.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_TAB_TAG = '<span class="tab"></span>'
_EDGES = re.compile(r"^(\s*)(.*?)(\s*)$", re.DOTALL)


def needs_translation(text: str) -> bool:
    """False for text with no letters at all (numbers, bullets, symbols): it would come back unchanged."""
    return any(character.isalpha() for character in text)


def split_edges(text: str) -> tuple[str, str, str]:
    """``"  Hello world "`` → ``("  ", "Hello world", " ")``."""
    match = _EDGES.match(text)
    assert match is not None  # the pattern matches any string
    return match.group(1), match.group(2), match.group(3)


def encode_runs(texts: list[str]) -> str:
    """Join run texts into one HTML string. ``texts`` should already have their edges stripped."""
    return "".join(
        f'<span id="{index}">{html.escape(text, quote=False).replace(chr(9), _TAB_TAG)}</span>'
        for index, text in enumerate(texts)
    )


def decode_runs(translated: str, count: int) -> list[str]:
    """Split a translated HTML string back into ``count`` run texts.

    Text the translator moved outside every span is given to the run before it (or the
    first run), so no words are ever dropped. Runs whose span disappeared come back empty.
    """
    parser = _RunParser(count)
    parser.feed(translated)
    parser.close()
    return [re.sub(r"[ \r\n]+", " ", "".join(parts)).strip(" ") for parts in parser.parts]


class _RunParser(HTMLParser):
    def __init__(self, count: int) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[list[str]] = [[] for _ in range(max(count, 1))]
        self._stack: list[int | None] = []  # run index of each open span (None for non-run tags)
        self._last = 0  # where stray text goes

    def _current(self) -> int:
        for index in reversed(self._stack):
            if index is not None:
                return index
        return self._last

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "span" and attributes.get("class") == "tab":
            self.parts[self._current()].append("\t")
            self._stack.append(None)
            return
        index = None
        if tag == "span" and (attributes.get("id") or "").isdigit():
            candidate = int(attributes["id"])  # type: ignore[arg-type]
            if candidate < len(self.parts):
                index = candidate
        if tag == "br":  # void element, never closed
            self.parts[self._current()].append(" ")
            return
        self._stack.append(index)

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            index = self._stack.pop()
            if index is not None:
                self._last = index

    def handle_data(self, data: str) -> None:
        self.parts[self._current()].append(data)
