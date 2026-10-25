"""What every document type has in common: paragraphs to translate, and saving safely."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from cicero.core.errors import DocumentError
from cicero.core.segments import decode_runs, encode_runs, needs_translation, split_edges


class TextRun(Protocol):
    """A piece of text with one formatting: python-pptx and python-docx runs both fit."""

    text: str


@dataclass(slots=True)
class TextBlock:
    """One paragraph to translate: its runs that contain text, and the HTML sent to the translator."""

    page: int  # slide or page number, from 1; 0 for slide masters, and for Word documents (no fixed pages)
    location: str  # where in the page, e.g. "Title 1", "Table: Table 3", "Notes", "Header"
    runs: list[TextRun]
    edges: list[tuple[str, str]]  # whitespace stripped from the start and end of each run
    original: str  # the paragraph as plain text
    source_html: str
    translation: str = field(default="")  # plain text, filled in by ``apply``


class Document(Protocol):
    """An open file whose paragraphs can be translated and saved as a copy."""

    kind: str  # for messages: "presentation", "Word document", …
    unit: str | None  # what ``TextBlock.page`` counts ("slide", "page"), or None if nothing
    page_count: int
    blocks: list[TextBlock]
    warnings: list[str]  # problems found while saving that didn't stop it

    def save(self, path: str | Path) -> None: ...


def make_block(page: int, location: str, runs: Sequence[TextRun], original: str | None = None) -> TextBlock | None:
    """A block for a paragraph made of ``runs``, or None if it has nothing worth translating."""
    texts = [run for run in runs if run.text.strip()]
    if not texts or not needs_translation("".join(run.text for run in texts)):
        return None
    pieces = [split_edges(run.text) for run in texts]
    return TextBlock(
        page=page,
        location=location,
        runs=texts,
        edges=[(before, after) for before, _, after in pieces],
        original=original if original is not None else "".join(run.text for run in runs),
        source_html=encode_runs([core for _, core, _ in pieces]),
    )


def apply(block: TextBlock, translated_html: str) -> None:
    """Write a translation into the block's runs. Each run keeps its own formatting."""
    texts = decode_runs(translated_html, len(block.runs))
    for run, (before, after), text in zip(block.runs, block.edges, texts):
        run.text = f"{before}{text}{after}" if text else ""
    block.translation = "".join(run.text for run in block.runs)


def save_atomically(save: Callable[[str], object], path: str | Path) -> None:
    """Call ``save(temporary_path)``, then move the result onto ``path``.

    An existing file is therefore only ever replaced by a complete one.
    """
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".cicero-partial", dir=path.parent)
    os.close(descriptor)
    try:
        save(temporary)
        os.replace(temporary, path)
    except PermissionError:
        raise DocumentError(f"Can't write the file. Is it open in another program?\n{path}") from None
    except OSError as exc:
        raise DocumentError(f"Can't save the file:\n{path}\n\n{exc}") from None
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
