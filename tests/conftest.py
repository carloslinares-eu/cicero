from __future__ import annotations

import html
import re
from collections.abc import Sequence
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches, Pt

from cicero.core.translator import Language

LANGUAGES = [Language("en", "English"), Language("es", "Spanish"), Language("zh-CN", "Chinese (Simplified)"),
             Language("pt-PT", "Portuguese (Portugal)")]


class FakeTranslator:
    """Upper-cases the text between tags, like a translator that keeps markup in place."""

    name = "Fake"
    description = "for tests"

    def __init__(self) -> None:
        self.max_segments = 100
        self.max_characters = 10_000
        self.requests: list[tuple[list[str], str, str | None]] = []
        self.on_request = None  # optional hook called before each request

    def languages(self) -> list[Language]:
        return list(LANGUAGES)

    def translate(self, html_segments: Sequence[str], target: str, source: str | None = None) -> list[str]:
        if self.on_request:
            self.on_request(len(self.requests))
        self.requests.append((list(html_segments), target, source))
        return [re.sub(r">([^<]+)<", lambda m: ">" + html.escape(html.unescape(m.group(1)).upper(), quote=False) + "<",
                       segment) for segment in html_segments]


@pytest.fixture
def fake_translator() -> FakeTranslator:
    return FakeTranslator()


@pytest.fixture
def sample_deck(tmp_path: Path) -> Path:
    """A presentation with text in every kind of place Cicero looks."""
    deck = Presentation()
    blank = deck.slide_layouts[6]

    first = deck.slides.add_slide(deck.slide_layouts[0])
    first.shapes.title.text = "Quarterly results"
    first.placeholders[1].text = "R&D <draft>"
    first.notes_slide.notes_text_frame.text = "Speak slowly"

    second = deck.slides.add_slide(blank)
    box = second.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    paragraph = box.text_frame.paragraphs[0]
    for text, bold in (("Hello ", False), ("bold", True), (" world", False)):
        run = paragraph.add_run()
        run.text = text
        run.font.bold = bold
        run.font.size = Pt(18)
    numbers = box.text_frame.add_paragraph()
    numbers.add_run().text = "2024 – 42 %"
    tabbed = box.text_frame.add_paragraph()
    tabbed.add_run().text = "Name:\t\tCarlos"

    group = second.shapes.add_group_shape()
    group.shapes.add_textbox(Inches(1), Inches(3), Inches(2), Inches(1)).text_frame.text = "inside group"
    inner = group.shapes.add_group_shape()
    inner.shapes.add_textbox(Inches(1), Inches(4), Inches(2), Inches(1)).text_frame.text = "nested group"

    third = deck.slides.add_slide(blank)
    table = third.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(2)).table
    table.cell(0, 0).text = "Product"
    table.cell(0, 1).text = "Price"
    table.cell(1, 0).text = "Apple"
    table.cell(1, 1).text = "3.50"

    path = tmp_path / "deck.pptx"
    deck.save(path)
    return path


SMARTART_DATA = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram"
    xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dgm:ptLst>{points}</dgm:ptLst></dgm:dataModel>"""
SMARTART_POINT = ('<dgm:pt modelId="{{{index}}}"><dgm:t><a:bodyPr/><a:p><a:r><a:rPr lang="en-US" b="1"/>'
                  '<a:t>{text}</a:t></a:r></a:p></dgm:t></dgm:pt>')
SMARTART_DRAWING = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<dsp:drawing xmlns:dsp="http://schemas.microsoft.com/office/drawing/2008/diagram"
    xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dsp:spTree>{shapes}</dsp:spTree></dsp:drawing>"""
SMARTART_SHAPE = ('<dsp:sp modelId="{{{index}}}"><dsp:txBody><a:bodyPr/><a:p><a:r><a:rPr lang="en-US"/>'
                  '<a:t>{text}</a:t></a:r></a:p></dsp:txBody></dsp:sp>')


def add_smartart(slide, texts: list[str], number: int = 1) -> None:
    """Attach SmartArt text parts to a slide the way PowerPoint stores them (data model plus cached drawing)."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.opc.package import Part
    from pptx.opc.packuri import PackURI

    from cicero.core.presentation import RT_DIAGRAM_DRAWING

    package = slide.part.package
    data = SMARTART_DATA.format(points="".join(SMARTART_POINT.format(index=i, text=t) for i, t in enumerate(texts)))
    drawing = SMARTART_DRAWING.format(shapes="".join(SMARTART_SHAPE.format(index=i, text=t)
                                                     for i, t in enumerate(texts)))
    slide.part.relate_to(Part(PackURI(f"/ppt/diagrams/data{number}.xml"),
                              "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml",
                              package, data.encode()), RT.DIAGRAM_DATA)
    slide.part.relate_to(Part(PackURI(f"/ppt/diagrams/drawing{number}.xml"),
                              "application/vnd.ms-office.drawingml.diagramDrawing+xml",
                              package, drawing.encode()), RT_DIAGRAM_DRAWING)


@pytest.fixture
def smartart_deck(tmp_path: Path) -> Path:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    add_smartart(slide, ["Plan", "Build", "Ship &amp; learn"])  # XML-escaped
    path = tmp_path / "smartart.pptx"
    deck.save(path)
    return path


@pytest.fixture
def sample_docx(tmp_path: Path) -> Path:
    """A Word document with text in the places Cicero looks, and some it must leave alone."""
    import docx
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    document = docx.Document()
    document.add_heading("Annual report", level=1)
    paragraph = document.add_paragraph()
    paragraph.add_run("Sales ")
    paragraph.add_run("grew").bold = True
    paragraph.add_run(" a lot")
    lines = document.add_paragraph()
    run = lines.add_run("Name:")
    run.add_tab()
    run.add_text("Carlos")
    run.add_break()
    run.add_text("Madrid")
    document.add_paragraph("2024 – 42 %")
    linked = document.add_paragraph("See ")
    linked._p.append(parse_xml(f'<w:hyperlink {nsdecls("w", "r")} r:id="rIdX"><w:r><w:t>our website</w:t></w:r>'
                               '</w:hyperlink>'))
    document.add_paragraph("Page ")._p.append(parse_xml(  # a run with a picture must not be emptied
        f'<w:r {nsdecls("w")}><w:t xml:space="preserve">with picture </w:t><w:drawing/></w:r>'))

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Region"
    inner = table.cell(0, 1).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "Nested cell"

    section = document.sections[0]
    section.header.paragraphs[0].text = "Confidential"
    section.footer.paragraphs[0].text = "Company name"

    path = tmp_path / "report.docx"
    document.save(path)
    return path


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Two pages: styled paragraphs, a hyphenated line break, numbers, an image, a drawn line, rotated text."""
    import pymupdf

    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 80), "Annual report", fontname="hebo", fontsize=20)
    page.insert_text((72, 130), "Sales grew a lot in the north-", fontname="helv", fontsize=11)
    page.insert_text((72, 144), "ern region this year.", fontname="helv", fontsize=11)
    page.insert_text((72, 200), "Warning", fontname="hebo", fontsize=12, color=(1, 0, 0))
    page.insert_text((72, 250), "2024 - 42 %", fontname="helv", fontsize=11)  # Base-14 fonts have no en dash
    page.insert_text((500, 700), "Draft", fontname="helv", fontsize=11, rotate=90)
    page.draw_line((72, 300), (520, 300), color=(0, 0, 1), width=2)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
    pixmap.set_rect(pixmap.irect, (0, 128, 255))
    page.insert_image(pymupdf.Rect(72, 320, 152, 400), pixmap=pixmap)
    pdf.new_page().insert_text((72, 80), "Second page", fontname="tiro", fontsize=14)
    path = tmp_path / "report.pdf"
    pdf.save(path)
    return path
