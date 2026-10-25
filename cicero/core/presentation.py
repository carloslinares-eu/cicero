"""Finding every piece of translatable text in a presentation and putting translations back."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pptx
import pptx.exc
from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part, XmlPart
from pptx.oxml import parse_xml
from pptx.presentation import Presentation
from pptx.shapes.group import GroupShape
from pptx.text.text import TextFrame, _Paragraph, _Run

from cicero.core.errors import PresentationError
from cicero.core.segments import decode_runs, encode_runs, needs_translation, split_edges

# SmartArt keeps its text in a "data model" part, and PowerPoint 2007+ also caches the
# rendered shapes, text included, in a "drawing" part. Both are translated so the cached
# drawing matches the data until PowerPoint redraws it.
RT_DIAGRAM_DRAWING = "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing"
SMARTART_RELATIONSHIPS = (RT.DIAGRAM_DATA, RT_DIAGRAM_DRAWING)
A_P = "{http://schemas.openxmlformats.org/drawingml/2006/main}p"


@dataclass(slots=True)
class TextBlock:
    """One paragraph to translate: its runs that contain text, and the HTML sent to the translator."""

    slide: int  # 1-based slide number; 0 for slide masters and layouts
    location: str  # shape name, "Table: …", "SmartArt", "Notes", or "Master: …"/"Layout: …" plus the shape
    runs: list[_Run]
    edges: list[tuple[str, str]]  # whitespace stripped from the start and end of each run
    original: str  # the paragraph as plain text
    source_html: str
    translation: str = field(default="")  # plain text, filled in by ``apply``


class PptxDocument:
    """An open presentation, the paragraphs found in it, and how to save it."""

    def __init__(self, path: str | Path, include_masters: bool = False) -> None:
        self.presentation = open_presentation(path)
        self.include_masters = include_masters
        self._xml_parts: list[_XmlBlob] = []  # parts python-pptx only knows as bytes (SmartArt)
        self.blocks = self._collect()

    @property
    def slide_count(self) -> int:
        return len(self.presentation.slides)

    def save(self, path: str | Path) -> None:
        for part in self._xml_parts:
            part.write_back()
        save_presentation(self.presentation, path)

    def _collect(self) -> list[TextBlock]:
        blocks = []
        for number, location, paragraphs in self._iter_paragraph_groups():
            for paragraph in paragraphs:
                block = make_block(number, location, paragraph)
                if block is not None:
                    blocks.append(block)
        return blocks

    def _iter_paragraph_groups(self) -> Iterator[tuple[int, str, Iterable[_Paragraph]]]:
        for number, slide in enumerate(self.presentation.slides, start=1):
            for location, frame in iter_text_frames(slide):
                yield number, location, frame.paragraphs
            for part in _smartart_parts(slide.part):
                blob = _XmlBlob(part)
                self._xml_parts.append(blob)
                yield number, "SmartArt", blob.paragraphs()
            if slide.has_notes_slide:  # reading slide.notes_slide would create an empty one
                frame = slide.notes_slide.notes_text_frame
                if frame is not None:
                    yield number, "Notes", frame.paragraphs
        if self.include_masters:
            # Text that appears on every slide using a layout (footers, labels, logos as text)
            # and the placeholder prompts shown while editing ("Click to edit Master title style").
            for master in self.presentation.slide_masters:
                masters = [(f"Master: {master.name or 'Slide Master'}", master)]
                masters += [(f"Layout: {layout.name}", layout) for layout in master.slide_layouts]
                for owner, container in masters:
                    for location, frame in iter_text_frames(container):
                        yield 0, f"{owner} › {location}", frame.paragraphs


def make_block(slide: int, location: str, paragraph: _Paragraph) -> TextBlock | None:
    """A block for ``paragraph``, or None if it has nothing worth translating."""
    runs = [run for run in paragraph.runs if run.text.strip()]
    if not runs or not needs_translation("".join(run.text for run in runs)):
        return None
    pieces = [split_edges(run.text) for run in runs]
    return TextBlock(
        slide=slide,
        location=location,
        runs=runs,
        edges=[(before, after) for before, _, after in pieces],
        original="".join(run.text for run in paragraph.runs),
        source_html=encode_runs([core for _, core, _ in pieces]),
    )


def open_presentation(path: str | Path) -> Presentation:
    try:
        return pptx.Presentation(str(path))
    except FileNotFoundError:
        raise PresentationError(f"File not found:\n{path}") from None
    except PermissionError:
        raise PresentationError(f"Can't open the file. Is it open in another program?\n{path}") from None
    except (pptx.exc.PackageNotFoundError, KeyError, ValueError) as exc:
        raise PresentationError(
            f"This isn't a PowerPoint .pptx file, or it is damaged.\n{path}\n\n"
            "Older .ppt files must first be saved as .pptx from PowerPoint.\n\n"
            f"Details: {exc}"
        ) from None


def iter_text_frames(slide) -> Iterator[tuple[str, TextFrame]]:
    """Text frames of a slide's (or master's, or layout's) shapes, looking inside groups and tables."""
    for shape in _iter_shapes(slide.shapes):
        if shape.has_text_frame:
            yield shape.name, shape.text_frame
        elif getattr(shape, "has_table", False):
            for cell in shape.table.iter_cells():
                if not cell.is_spanned:
                    yield f"Table: {shape.name}", cell.text_frame


def _iter_shapes(shapes) -> Iterator:
    """Shapes on a slide, looking inside groups (and groups of groups)."""
    for shape in shapes:
        if isinstance(shape, GroupShape):
            yield from _iter_shapes(shape.shapes)
        else:
            yield shape


def _smartart_parts(slide_part: Part) -> list[Part]:
    parts = []
    for relationship in slide_part.rels.values():
        if relationship.reltype in SMARTART_RELATIONSHIPS and not relationship.is_external:
            if relationship.target_part not in parts:
                parts.append(relationship.target_part)
    return parts


class _XmlBlob:
    """An XML part that python-pptx keeps as raw bytes, parsed so its paragraphs can be edited."""

    def __init__(self, part: Part) -> None:
        self.part = part
        self.element = part._element if isinstance(part, XmlPart) else parse_xml(part.blob)

    def paragraphs(self) -> list[_Paragraph]:
        # parse_xml gives python-pptx's own element classes, so <a:p> works with its text API.
        return [_Paragraph(p, None) for p in self.element.iter(A_P)]

    def write_back(self) -> None:
        if not isinstance(self.part, XmlPart):
            self.part._blob = etree.tostring(self.element, xml_declaration=True, encoding="UTF-8", standalone=True)


def apply(block: TextBlock, translated_html: str) -> None:
    """Write a translation into the block's runs. Each run keeps its own formatting."""
    texts = decode_runs(translated_html, len(block.runs))
    for run, (before, after), text in zip(block.runs, block.edges, texts):
        run.text = f"{before}{text}{after}" if text else ""
    block.translation = "".join(run.text for run in block.runs)


def save_presentation(presentation: Presentation, path: str | Path) -> None:
    """Save through a temporary file, so an existing file is only replaced by a complete one."""
    save_atomically(presentation.save, path)


def save_atomically(save, path: str | Path) -> None:
    """Call ``save(temporary_path)``, then move the result onto ``path``."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".cicero-partial", dir=path.parent)
    os.close(descriptor)
    try:
        save(temporary)
        os.replace(temporary, path)
    except PermissionError:
        raise PresentationError(f"Can't write the file. Is it open in another program?\n{path}") from None
    except OSError as exc:
        raise PresentationError(f"Can't save the file:\n{path}\n\n{exc}") from None
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
