"""Translating the text of a PDF in place.

A PDF has no paragraphs or text boxes, only glyphs placed at coordinates. PyMuPDF groups
them into *blocks*, *lines* and *spans* (text with one font, size and color). A block is
often more than one paragraph: the cells of a table row, a label and its value, a date
next to a title. So each block is split again, and a line joins the one above it only if
it reads as the same paragraph wrapped. Each paragraph's spans are the runs to translate.

Some text is left as it is:

- Postal addresses (a line ending in a postcode and town, and the name and street lines
  above it), and the names in them wherever they appear again. Addresses must stay valid.
- Text drawn with fonts that OCR software traced from a scan (Acrobat's ClearScan names
  them with a leading "*"). It looks like the scan, logos included, but its letters are
  often misread, and redrawn in an ordinary font it would no longer look like the scan.

On saving, the original glyphs of every translated paragraph are removed with a redaction
(pictures and drawings are kept). The translation is then laid out in the same rectangle as
HTML. Each span keeps its size, weight, style and color, and the text shrinks only if it
can't fit.
"""

from __future__ import annotations

import html
import logging
import re
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
GAP = 3  # points kept clear of neighboring text, images and frame edges
LINE_PITCH = 1.9  # most font sizes between the baselines of a paragraph's lines (1.5 line spacing is ~1.7)
ADDRESS_PITCH = 1.35  # the same for the lines of an address, which are set close together

_LIST_ITEM = re.compile(r"\s*(?:[•◦▪▫■●○‣⁃∙·*–—-]|\d{1,2}[.)]|[a-z][.)])(?:\s|$)")
_POSTCODE_TOWN = re.compile(r"""
    (?:^|\s)(?P<country>[A-Z]{1,3}-)?\d{4,5}(?:\s[A-Z]{2})?\s+[^\W\d_][^\d]{0,40}$  # DE-86161 Augsburg, 1012 AB Amsterdam
  | \b[A-Z]{2}\s\d{5}(?:-\d{4})?$                                                  # Springfield, IL 62704
  | ^[A-Z]{1,2}\d[A-Z\d]?\s\d[A-Z]{2}$                                             # SW1A 1AA
""", re.VERBOSE)
_HOUSE_NUMBER = re.compile(r"[^\W\d_]{2,}\.?\s\d{1,4}[a-zA-Z]?\b|^\s*\d{1,5}[a-zA-Z]?\s[^\W\d_]")


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
class _Line:
    """A line of text as PyMuPDF found it (pieces of one row it split up are merged back)."""

    rect: pymupdf.Rect
    spans: list[dict]  # PyMuPDF's span dictionaries
    block: int  # PyMuPDF's block number: its lines are set close together

    @property
    def text(self) -> str:
        return "".join(span["text"] for span in self.spans)

    @property
    def main(self) -> dict:
        """The span with the most text, which gives the line its style."""
        return max(self.spans, key=lambda span: len(span["text"].strip()))

    @property
    def size(self) -> float:
        return self.main["size"]

    @property
    def bold(self) -> bool:
        return _span(self.main, "").bold

    @property
    def baseline(self) -> float:
        return self.main["origin"][1]


@dataclass(slots=True)
class _Region:
    page: int  # 0-based index
    rect: pymupdf.Rect
    lines: list[pymupdf.Rect]
    block: TextBlock
    spans: list[PdfSpan]
    align: str  # CSS text-align: "left", "center" or "right"
    single_line: bool
    line_height: float  # CSS line-height, measured from the original lines


@dataclass(slots=True)
class _PageLayout:
    """What a translation must not run into on a page, measured before anything is removed."""

    obstacles: list[pymupdf.Rect]  # every line of text, image and ruled line
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
        pages: list[list[list[_Line]]] = []
        names: set[str] = set()  # from addresses, kept wherever they appear
        rows: dict[int, list[pymupdf.Rect]] = {}  # every line of text on each page
        for index, page in enumerate(self.pdf):
            content = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
            texts = [item for item in content["blocks"] if item.get("type") == 0]
            drawings = [pymupdf.Rect(drawing["rect"]) for drawing in page.get_drawings()]
            rows[index] = [pymupdf.Rect(line["bbox"]) for item in texts for line in item["lines"]]
            obstacles = rows[index] + [pymupdf.Rect(image["bbox"]) for image in page.get_image_info()]
            obstacles += [rect + (-0.5, -0.5, 0.5, 0.5) for rect in drawings if _is_rule(rect)]
            boxes = [rect for rect in drawings if rect.width > 20 and rect.height > 10]
            self._layouts[index] = _PageLayout(obstacles, boxes)

            spans = [span for item in texts for line in item["lines"] for span in line["spans"] if span["text"].strip()]
            mixed = any(_traced(span) for span in spans) and not all(_traced(span) for span in spans)
            paragraphs = _paragraphs([line for item in texts for line in _lines(item, skip_traced=mixed)])
            addresses = _addresses(paragraphs)
            names |= {_plain(paragraph[0].text) for paragraph in addresses
                      if not any(character.isdigit() for character in paragraph[0].text)}
            pages.append([paragraph for paragraph in paragraphs if not any(paragraph is kept for kept in addresses)])

        blocks = []
        for index, paragraphs in enumerate(pages):
            for paragraph in paragraphs:
                if _plain(" ".join(line.text for line in paragraph)) in names:
                    continue
                cell = len(paragraph) == 1 and _shares_row(paragraph[0].rect, rows[index])
                region = _read_paragraph(index, paragraph, "Table cell" if cell else "Text", rows[index])
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
            for line in (line for region in on_page for line in region.lines):
                # Only the middle of the line: a redaction removes every glyph it touches, and the line
                # above or below may be one that stays.
                page.add_redact_annot(line + (0.5, line.height / 4, -0.5, -line.height / 4))
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


def _traced(span: dict) -> bool:
    """Drawn with a font that OCR software traced from a scan (Acrobat's ClearScan)."""
    return span["font"].startswith("*")


def _is_rule(rect: pymupdf.Rect) -> bool:
    """A drawn line (or a thin bar): a table rule or a separator."""
    return rect.height <= 3 and rect.width >= 10 or rect.width <= 3 and rect.height >= 10


def _plain(text: str) -> str:
    return " ".join(text.split())


def _lines(block: dict, skip_traced: bool) -> list[_Line]:
    """The block's horizontal lines that can be translated, with the pieces of a row PyMuPDF split merged back."""
    if any("�" in span["text"] for line in block["lines"] for span in line["spans"]):
        return []  # some characters can't be read: the block is left as it is
    lines: list[_Line] = []
    for raw in block["lines"]:
        spans = [span for span in raw["spans"] if span["text"]]
        if not spans or abs(raw["dir"][1]) > 0.01:
            continue  # rotated or vertical text: left as it is
        if skip_traced and any(_traced(span) for span in spans):
            continue  # traced from the scanned letterhead under the text
        line = _Line(pymupdf.Rect(raw["bbox"]), spans, block["number"])
        last = lines[-1] if lines else None
        gap = line.rect.x0 - last.rect.x1 if last else -1
        if last and abs(line.baseline - last.baseline) < 0.2 * last.size and 0 <= gap < 0.6 * last.size:
            if gap > 0.1 * last.size and not last.text.endswith(" ") and not line.text.startswith(" "):
                spans = [{**spans[0], "text": " " + spans[0]["text"]}, *spans[1:]]
            lines[-1] = _Line(last.rect | line.rect, last.spans + spans, last.block)
        else:
            lines.append(line)
    return lines


def _paragraphs(lines: list[_Line]) -> list[list[_Line]]:
    """Group a page's lines into paragraphs: a line joins the paragraph it continues, or starts a new one.

    PyMuPDF's blocks don't decide it: it puts the lines of a widely spaced paragraph in blocks of
    their own, and a table row's cells in one.
    """
    paragraphs: list[list[_Line]] = []
    for line in lines:
        recent = reversed(paragraphs[-30:])  # enough for a table row of many cells before the cell above
        home = next((paragraph for paragraph in recent if _continues(paragraph, line, lines)), None)
        if home is None:
            paragraphs.append([line])
        else:
            home.append(line)
    return paragraphs


def _continues(paragraph: list[_Line], line: _Line, lines: list[_Line]) -> bool:
    """Whether ``line`` is the next line of ``paragraph``, wrapped.

    It must sit right below the paragraph's last line, line up with it and have its style,
    and the text must have been wrapped there. Short lines (cells, labels, the lines of an
    address) stay apart. Large text (a heading over two lines) needs no more than that.
    """
    above = paragraph[-1]
    size = above.size
    pitch = line.baseline - above.baseline
    if abs(line.size - size) > 0.6 or line.bold != above.bold or not 0.5 * size < pitch <= LINE_PITCH * size:
        return False
    if len(paragraph) > 1 and abs(pitch - (above.baseline - paragraph[-2].baseline)) > 0.25 * size:
        return False  # spaced unlike the paragraph's other lines
    if not _aligned(paragraph, line) or _LIST_ITEM.match(line.text):
        return False
    return size >= 14 or _wrapped(above, line, lines)


def _wrapped(above: _Line, line: _Line, lines: list[_Line]) -> bool:
    """Whether the text was wrapped from ``above`` to ``line``.

    A word broken with a hyphen is. Otherwise the line above must hold a few words (or, in
    the same PyMuPDF block, the next line start in lowercase), and the next line's first word
    must not have fitted at the end of it, before the right edge of the longest line that
    starts where it starts.
    """
    text, following = above.text.rstrip(), line.text.split()
    if text.endswith("-"):
        return True
    lowercase = bool(following) and following[0][:1].islower() and line.block == above.block
    if not following or len(text.split()) < 4 and not lowercase:
        return False
    tolerance = max(2.0, 0.3 * above.size)
    edge = max(other.rect.x1 for other in lines if abs(other.rect.x0 - above.rect.x0) <= tolerance)
    return edge - above.rect.x1 < pymupdf.get_text_length(" " + following[0], fontsize=above.size)


def _aligned(paragraph: list[_Line], line: _Line) -> bool:
    """Left-aligned or centered with the line above; or under a first line that is indented or a list item."""
    above = paragraph[-1].rect
    tolerance = max(2.0, 0.3 * paragraph[-1].size)
    if abs(line.rect.x0 - above.x0) <= tolerance or abs((line.rect.x0 + line.rect.x1 - above.x0 - above.x1) / 2) <= tolerance:
        return True
    if len(paragraph) > 1:
        return False
    first = paragraph[0]
    indent = line.rect.x0 - above.x0
    if _LIST_ITEM.match(first.text):
        return 0 < indent <= 3 * first.size  # under the text after the bullet
    return 0 < -indent <= 4 * first.size  # the first line is indented


def _addresses(paragraphs: list[list[_Line]]) -> list[list[_Line]]:
    """The paragraphs that are postal addresses, which are not translated.

    An address ends in a line with a postcode and a town, with a country code or a house
    number to tell it from other text that ends in a number and a word. The lines just above
    it in the same column, short and set close together, are its name, company and street.
    """
    singles = [paragraph[0] for paragraph in paragraphs if len(paragraph) == 1]
    found: list[_Line] = []
    for line in singles:
        text = line.text.strip()
        match = _POSTCODE_TOWN.search(text)
        if match is None or len(text) > 100:
            continue
        above = _address_lines_above(line, singles)
        streets = [text[:match.start()], *(other.text for other in above)]
        if match.group("country") or any(_HOUSE_NUMBER.search(street) for street in streets):
            found += [line, *above]
    return [paragraph for paragraph in paragraphs if len(paragraph) == 1 and any(paragraph[0] is line for line in found)]


def _address_lines_above(line: _Line, lines: list[_Line]) -> list[_Line]:
    above: list[_Line] = []
    current = line
    while len(above) < 4:
        tolerance = max(2.0, 0.3 * current.size)
        candidates = [other for other in lines
                      if abs(other.rect.x0 - current.rect.x0) <= tolerance and abs(other.size - current.size) <= 0.6
                      and 0 < current.baseline - other.baseline <= ADDRESS_PITCH * current.size
                      and len(other.text.split()) <= 6 and not other.text.rstrip().endswith(":")]
        if not candidates:
            break
        current = max(candidates, key=lambda other: other.baseline)
        above.append(current)
    return above


def _shares_row(rect: pymupdf.Rect, lines: list[pymupdf.Rect]) -> bool:
    """Another line of the same height sits level with this one, as in a table, or a form's label and value."""
    tolerance = 0.15 * rect.height
    return any(abs(other.y0 - rect.y0) <= tolerance and abs(other.y1 - rect.y1) <= tolerance
               and (other.x0 >= rect.x1 or other.x1 <= rect.x0) for other in lines)


def _read_paragraph(page_index: int, lines: list[_Line], location: str,
                    page_lines: list[pymupdf.Rect]) -> _Region | None:
    spans: list[PdfSpan] = []
    for number, line in enumerate(lines):
        for position, raw in enumerate(line.spans):
            text = raw["text"]
            if number > 0 and position == 0 and spans:
                text = _join_line(spans[-1], text)
            span = _span(raw, text)
            if spans and spans[-1].style == span.style:
                spans[-1].text += span.text
            else:
                spans.append(span)
    original = "".join(span.text for span in spans)
    block = make_block(page_index + 1, location, spans, original)
    if block is None:
        return None
    rect = pymupdf.Rect(lines[0].rect)
    for line in lines[1:]:
        rect |= line.rect
    return _Region(page_index, rect, [line.rect for line in lines], block, spans,
                   _alignment(rect, lines, page_lines), len(lines) == 1,
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


def _alignment(rect: pymupdf.Rect, lines: list[_Line], page_lines: list[pymupdf.Rect]) -> str:
    """How a paragraph is aligned: "left", "center" or "right".

    A paragraph of several lines is centered or right-aligned if its lines, of different
    widths, share their middle or their right edge. A single line is right-aligned if it
    ends where a line near it ends (a header above a page number, a column heading above
    its numbers) without starting where any line near it starts.
    """
    if len(lines) > 1:
        widths = [line.rect.width for line in lines]
        if max(widths) - min(widths) <= 4:
            return "left"
        if all(abs((line.rect.x0 + line.rect.x1 - rect.x0 - rect.x1) / 2) < 2 for line in lines):
            return "center"
        return "right" if all(abs(line.rect.x1 - rect.x1) < 2 for line in lines) else "left"
    near = [other for other in page_lines if abs((other.y0 + other.y1 - rect.y0 - rect.y1) / 2) <= 3 * rect.height]
    ends = any(abs(other.x1 - rect.x1) <= 1 and abs(other.x0 - rect.x0) > 2 for other in near)
    starts = any(abs(other.x0 - rect.x0) <= 1 and abs(other.x1 - rect.x1) > 2 for other in near)
    return "right" if ends and not starts else "left"


def _layout_rect(region: _Region, page: pymupdf.Rect, layout: _PageLayout) -> pymupdf.Rect:
    """Where the translation is laid out: the original box, grown into the free space around it.

    Translations are often longer than the original, so before the text has to shrink, the box
    may grow down. A single line, such as a title or a label, may also grow to the right (to
    the left if it is right-aligned). Either way it stops before other text, an image or a
    ruled line, the edge of a drawn frame it sits in, or the page margin.
    """
    original = region.rect
    frames = [box for box in layout.boxes if box.contains(original) and box != original]
    bound = min(frames, key=lambda box: box.get_area()) + (GAP, GAP, -GAP, -GAP) if frames else \
        page + (PAGE_MARGIN, PAGE_MARGIN, -PAGE_MARGIN, -PAGE_MARGIN)
    # Leave out the paragraph's own lines (mostly inside it) and what it sits on (a page-size scan, a panel).
    others = [rect for rect in layout.obstacles
              if (overlap := (rect & original).get_area()) < 0.9 * rect.get_area() and overlap < 0.9 * original.get_area()]

    rect = pymupdf.Rect(original)
    level = [o for o in others if o.y0 < original.y1 and o.y1 > original.y0]
    if region.single_line and region.align == "left":
        right = [o.x0 for o in level if o.x0 >= original.x1 - 1]
        rect.x1 = max(original.x1, min([bound.x1, *[x - GAP for x in right]]))
    elif region.single_line and region.align == "right":
        left = [o.x1 for o in level if o.x1 <= original.x0 + 1]
        rect.x0 = min(original.x0, max([bound.x0, *[x + GAP for x in left]]))
    below = [o.y0 for o in others if o.y0 >= original.y1 - 1 and o.x0 < rect.x1 and o.x1 > rect.x0]
    rect.y1 = max(original.y1, min([bound.y1, *[y - GAP for y in below]]))
    return rect


def _line_height(lines: list[_Line], size: float) -> float:
    """Distance between baselines as a multiple of the font size.

    For a single line, 1.15 or less if the original line was less tall, so that a cell or label
    with no room to grow keeps its size.
    """
    if size <= 0:
        return 1.15
    if len(lines) == 1:
        return max(1.0, min(1.15, int(lines[0].rect.height / size * 100) / 100))
    gaps = [b.baseline - a.baseline for a, b in zip(lines, lines[1:])]
    gaps = [gap for gap in gaps if gap > 0]
    return round(min(max(sum(gaps) / len(gaps) / size, 1.0), 2.0), 2) if gaps else 1.15


def _region_html(region: _Region) -> str:
    body = "".join(span.to_html() for span in region.spans if span.text)
    return f'<div style="text-align:{region.align};margin:0;padding:0;line-height:{region.line_height}">{body}</div>'


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
