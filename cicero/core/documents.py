"""Choosing the right reader for a file."""

from __future__ import annotations

from pathlib import Path

from cicero.core.blocks import Document
from cicero.core.errors import DocumentError

# Extension → description, for file dialogs and messages.
SUPPORTED = {
    ".pptx": "PowerPoint presentation",
    ".docx": "Word document",
}


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED


def open_document(path: str | Path, include_masters: bool = False) -> Document:
    """Open ``path`` with the reader for its type. ``include_masters`` only applies to presentations."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pptx":
        from cicero.core.presentation import PptxDocument

        return PptxDocument(path, include_masters=include_masters)
    if suffix == ".docx":
        from cicero.core.word import DocxDocument

        return DocxDocument(path)
    raise DocumentError(
        f"Cicero can't translate {suffix or 'this kind of'} files.\n\n"
        f"Supported: {', '.join(f'{name} ({ext})' for ext, name in SUPPORTED.items())}.\n"
        "Older .ppt and .doc files can be saved as .pptx and .docx from PowerPoint or Word."
    )
