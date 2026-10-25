"""The optional review spreadsheet: every original paragraph next to its translation."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from cicero.core.blocks import TextBlock
from cicero.core.errors import DocumentError


def review_path_for(output: str | Path) -> Path:
    """``Deck (es).pptx`` → ``Deck (es).csv``."""
    return Path(output).with_suffix(".csv")


def write_review(path: str | Path, blocks: Iterable[TextBlock], unit: str | None = "slide") -> None:
    """One row per paragraph. ``unit`` names the first column ("slide", "page"); None leaves it out."""
    # utf-8-sig so Excel recognises the encoding and accents display correctly.
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(([unit.capitalize()] if unit else []) + ["Location", "Original", "Translation"])
            for block in blocks:
                writer.writerow(([block.page] if unit else []) + [block.location, block.original, block.translation])
    except OSError as exc:
        raise DocumentError(f"Can't write the review file:\n{path}\n\n{exc}") from None
