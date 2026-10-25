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

    def __init__(self) -> None:
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
