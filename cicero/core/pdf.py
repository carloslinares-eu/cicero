"""Translating the text of a PDF in place.

A PDF has no paragraphs or text boxes, only glyphs placed at coordinates. PyMuPDF groups
them into *blocks* (roughly paragraphs), *lines* and *spans* (text with one font, size and
colour). Each block becomes one paragraph to translate, its spans the runs. On saving,
the original glyphs of every translated block are removed with a redaction (pictures and
drawings are kept) and the translation is laid out in the same rectangle as HTML,
keeping each span's size, weight, style and colour, shrunk if needed to fit.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from cicero.core.blocks import TextBlock, make_block, save_atomically
from cicero.core.errors import DocumentError

log = logging.getLogger(__name__)

BOLD_FLAG = 16  # span["flags"] bits, see PyMuPDF's TEXT_FONT_* constants
ITALIC_FLAG = 2
MONOSPACED_FLAG = 8
SERIF_FLAG = 4
PAGE_MARGIN = 18  # points kept clear at the page edge when a translation needs more room
GAP = 3  # points kept clear of neighbouring text, images and frame edges


@dataclass(slots=True)
class PdfSpan:
    """A run of PDF text with one style. ``text`` is what gets translated."""

    text: str
    size: float
    color: int  # 0xRRGGBB
    bold: bool
    italic: bool
    family: str  # CSS generic family: "sans-serif", "serif" or "monospace"

    @property
    def style(self) -> tuple:
        return self.size, self.color, self.bold, self.italic, self.family

    def to_html(self) -> str:
        css = [f"font-size:{self.size:.1f}pt", f"color:#{self.color:06x}", f"font-family:{self.family}"]
        if self.bold:
            css.append("font-weight:bold")
        if self.italic:
            css.append("font-style:italic")
        text = html.escape(self.text, quote=False).replace("\n", "<br>").replace("\t", "&emsp;")
        return f'<span style="{";".join(css)}">{text}</span>'


@dataclass(slots=True)
class _Region:
    page: int  # 0-based index
    rect: pymupdf.Rect
    block: TextBlock
    spans: list[PdfSpan]
    centered: bool
    single_line: bool
    line_height: float  # CSS line-height, measured from the original lines


@dataclass(slots=True)
class _PageLayout:
    """What a translation must not run into on a page, measured before anything is removed."""

    obstacles: list[pymupdf.Rect]  # every text block and image
    boxes: list[pymupdf.Rect]  # drawn rectangles (frames, shaded panels) text may sit inside


class PdfDocument:
    """An open PDF, the paragraphs found in it, and how to save a translated copy."""

    kind = "PDF"
    unit = "page"

    def __init__(self, path: str | Path) -> None:
        self.pdf = open_pdf(path)
        self._regions: list[_Region] = []
        self._layouts: dict[int, _PageLayout] = {}
        self.warnings: list[str] = []
        self.blocks = self._collect()

    @property
    def page_count(self) -> int:
        return self.pdf.page_count

    def _collect(self) -> list[TextBlock]:
        blocks = []
        for index, page in enumerate(self.pdf):
            content = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
            obstacles = [pymupdf.Rect(item["bbox"]) for item in content["blocks"]]
            obstacles += [pymupdf.Rect(image["bbox"]) for image in page.get_image_info()]
            boxes = [pymupdf.Rect(drawing["rect"]) for drawing in page.get_drawings()
                     if drawing["rect"].width > 20 and drawing["rect"].height > 10]
            self._layouts[index] = _PageLayout(obstacles, boxes)
            for item in content["blocks"]:
                region = _read_block(index, item)
                if region is not None:
                    self._regions.append(region)
                    blocks.append(region.block)
        return blocks

    def save(self, path: str | Path) -> None:
        translated = [region for region in self._regions if region.block.translation]
        too_small = 0
        for index in sorted({region.page for region in translated}):
            page = self.pdf[index]
            on_page = [region for region in translated if region.page == index]
            for region in on_page:
                page.add_redact_annot(region.rect)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                                  text=pymupdf.PDF_REDACT_TEXT_REMOVE)
            for region in on_page:
                rect = _layout_rect(region, page.rect, self._layouts[index])
                spare_height, _scale = page.insert_htmlbox(rect, _region_html(region), scale_low=0)
                if spare_height < 0:
                    too_small += 1
        if too_small:
            self.warnings.append(f"{too_small} translated paragraph(s) didn't fit in their original space "
                                 "even at a smaller size, and may be cut off.")
        save_atomically(lambda temporary: self.pdf.save(temporary, garbage=3, deflate=True), path)


def _read_block(page_index: int, item: dict) -> _Region | None:
    if item.get("type") != 0:  # 1 is an image
        return None
    lines = [line for line in item["lines"] if line["spans"]]
    if not lines or any(abs(line["dir"][1]) > 0.01 for line in lines):
        return None  # rotated or vertical text: left as it is
    spans: list[PdfSpan] = []
    for number, line in enumerate(lines):
        for position, raw in enumerate(line["spans"]):
            text = raw["text"]
            if number > 0 and position == 0 and spans:
                text = _join_line(spans[-1], text)
            span = _span(raw, text)
            if spans and spans[-1].style == span.style:
                spans[-1].text += span.text
            else:
                spans.append(span)
    original = "".join(span.text for span in spans)
    block = make_block(page_index + 1, "Text", spans, original)
    if block is None:
        return None
    rect = pymupdf.Rect(item["bbox"])
    return _Region(page_index, rect, block, spans, _is_centered(rect, lines), len(lines) == 1,
                   _line_height(lines, max(span.size for span in spans)))


def _join_line(previous: PdfSpan, text: str) -> str:
    """Join a line to the one before: words broken with a hyphen are rejoined, others get a space."""
    if previous.text.endswith("-") and text[:1].islower():
        previous.text = previous.text[:-1]
        return text
    if previous.text.endswith((" ", "\n")) or text.startswith(" "):
        return text
    return " " + text


def _span(raw: dict, text: str) -> PdfSpan:
    flags, font = raw.get("flags", 0), raw.get("font", "").lower()
    if flags & MONOSPACED_FLAG or "mono" in font or "courier" in font:
        family = "monospace"
    elif flags & SERIF_FLAG or "times" in font or "serif" in font and "sans" not in font:
        family = "serif"
    else:
        family = "sans-serif"
    return PdfSpan(
        text=text,
        size=round(raw.get("size", 11.0), 1),
        color=raw.get("color", 0) & 0xFFFFFF,
        bold=bool(flags & BOLD_FLAG) or "bold" in font,
        italic=bool(flags & ITALIC_FLAG) or "italic" in font or "oblique" in font,
        family=family,
    )


def _is_centered(rect: pymupdf.Rect, lines: list[dict]) -> bool:
    """Every line of a multi-line block has its middle near the block's middle (and lines differ in width)."""
    if len(lines) < 2:
        return False
    middle = (rect.x0 + rect.x1) / 2
    widths = [line["bbox"][2] - line["bbox"][0] for line in lines]
    centred = all(abs((line["bbox"][0] + line["bbox"][2]) / 2 - middle) < 2 for line in lines)
    return centred and max(widths) - min(widths) > 4


def _layout_rect(region: _Region, page: pymupdf.Rect, layout: _PageLayout) -> pymupdf.Rect:
    """Where the translation is laid out: the original box, grown into the free space around it.

    Translations are often longer than the original. Before the text has to shrink, the box
    may grow down (and, for a single left-aligned line such as a title or label, to the
    right) until it would touch another text block or image, the edge of a drawn frame
    it sits in, or the page margin.
    """
    original = region.rect
    frames = [box for box in layout.boxes if box.contains(original) and box != original]
    bound = min(frames, key=lambda box: box.get_area()) + (GAP, GAP, -GAP, -GAP) if frames else         page + (PAGE_MARGIN, PAGE_MARGIN, -PAGE_MARGIN, -PAGE_MARGIN)
    others = [rect for rect in layout.obstacles if not (rect & original).get_area() >= 0.9 * original.get_area()]

    rect = pymupdf.Rect(original)
    if region.single_line and not region.centered:
        right = [o.x0 for o in others if o.x0 >= original.x1 - 1 and o.y0 < original.y1 and o.y1 > original.y0]
        rect.x1 = max(original.x1, min([bound.x1, *[x - GAP for x in right]]))
    below = [o.y0 for o in others if o.y0 >= original.y1 - 1 and o.x0 < rect.x1 and o.x1 > rect.x0]
    rect.y1 = max(original.y1, min([bound.y1, *[y - GAP for y in below]]))
    return rect


def _line_height(lines: list[dict], size: float) -> float:
    """Distance between baselines as a multiple of the font size (1.15 for single lines)."""
    if len(lines) < 2 or size <= 0:
        return 1.15
    gaps = [b["spans"][0]["origin"][1] - a["spans"][0]["origin"][1] for a, b in zip(lines, lines[1:])]
    gaps = [gap for gap in gaps if gap > 0]
    return round(min(max(sum(gaps) / len(gaps) / size, 1.0), 2.0), 2) if gaps else 1.15


def _region_html(region: _Region) -> str:
    body = "".join(span.to_html() for span in region.spans if span.text)
    align = "center" if region.centered else "left"
    return f'<div style="text-align:{align};margin:0;padding:0;line-height:{region.line_height}">{body}</div>'


def open_pdf(path: str | Path) -> pymupdf.Document:
    try:
        pdf = pymupdf.open(str(path))
    except FileNotFoundError:
        raise DocumentError(f"File not found:\n{path}") from None
    except PermissionError:
        raise DocumentError(f"Can't open the file. Is it open in another program?\n{path}") from None
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise DocumentError(f"This isn't a PDF file, or it is damaged.\n{path}\n\nDetails: {exc}") from None
    if not pdf.is_pdf:
        pdf.close()
        raise DocumentError(f"This isn't a PDF file.\n{path}")
    if pdf.needs_pass:
        pdf.close()
        raise DocumentError("This PDF is password-protected. Remove the password (for example by printing it "
                            f"to a new PDF) and try again.\n{path}")
    return pdf
