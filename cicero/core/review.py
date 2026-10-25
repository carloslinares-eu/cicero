"""The optional review spreadsheet: every original paragraph next to its translation."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from cicero.core.errors import PresentationError
from cicero.core.presentation import TextBlock

COLUMNS = ["Slide", "Location", "Original", "Translation"]


def review_path_for(output: str | Path) -> Path:
    """``Deck (es).pptx`` → ``Deck (es).csv``."""
    return Path(output).with_suffix(".csv")


def write_review(path: str | Path, blocks: Iterable[TextBlock]) -> None:
    # utf-8-sig so Excel recognises the encoding and accents display correctly.
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(COLUMNS)
            for block in blocks:
                writer.writerow([block.slide, block.location, block.original, block.translation])
    except OSError as exc:
        raise PresentationError(f"Can't write the review file:\n{path}\n\n{exc}") from None
