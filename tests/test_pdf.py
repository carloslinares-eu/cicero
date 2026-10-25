from __future__ import annotations

import pymupdf

from cicero.core.documents import open_document
from cicero.core.job import JobOptions, TranslationJob


def translate(fake_translator, source):
    output = source.with_name("out.pdf")
    result = TranslationJob(fake_translator, JobOptions(source, output, "es")).run()
    assert result.succeeded, result.error
    return result, pymupdf.open(output)


def spans(page) -> list[dict]:
    return [span for block in page.get_text("dict")["blocks"] if block["type"] == 0
            for line in block["lines"] for span in line["spans"]]


def test_reads_paragraphs_and_rejoins_hyphenated_words(sample_pdf):
    document = open_document(sample_pdf)
    originals = [block.original for block in document.blocks]
    assert "Sales grew a lot in the northern region this year." in originals
    assert "2024 - 42 %" not in originals  # nothing to translate
    assert "Draft" not in originals  # rotated text is left alone
    assert document.page_count == 2 and document.unit == "page"
    assert {block.page for block in document.blocks} == {1, 2}


def test_replaces_text_and_keeps_style_images_and_drawings(fake_translator, sample_pdf):
    result, output = translate(fake_translator, sample_pdf)
    first = output[0].get_text()
    assert "SALES GREW A LOT IN THE NORTHERN REGION THIS YEAR." in " ".join(first.split())
    assert "Sales grew" not in first and "Annual report" not in first
    assert "2024 - 42 %" in first and "Draft" in first
    assert "SECOND PAGE" in output[1].get_text()

    warning = next(span for span in spans(output[0]) if span["text"].strip() == "WARNING")
    assert warning["color"] == 0xFF0000 and warning["flags"] & 16  # red and bold
    assert round(warning["size"]) == 12
    assert len(output[0].get_images()) == 1
    assert any(item["color"] == (0.0, 0.0, 1.0) for item in output[0].get_drawings())
    assert result.pages == 2


def test_scanned_or_empty_pdf_gives_nothing_to_translate(fake_translator, tmp_path):
    source = tmp_path / "scan.pdf"
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.save(source)
    result, _ = translate(fake_translator, source)
    assert result.paragraphs == 0 and fake_translator.requests == []


def test_password_protected_pdf_is_explained(fake_translator, tmp_path):
    source = tmp_path / "locked.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Secret")
    pdf.save(source, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    result = TranslationJob(fake_translator, JobOptions(source, tmp_path / "out.pdf", "es")).run()
    assert "password-protected" in result.error


def test_longer_translations_use_free_space_instead_of_shrinking(fake_translator, tmp_path):
    import html
    import re

    source = tmp_path / "framed.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=420, height=300)
    frame = pymupdf.Rect(30, 160, 390, 260)
    page.draw_rect(frame, color=(0.8, 0.8, 0.8), fill=(0.95, 0.95, 1))
    page.insert_text((40, 185), "Next steps", fontname="hebo", fontsize=12)
    page.insert_text((40, 205), "Hire two engineers", fontname="helv", fontsize=10)
    pdf.save(source)

    def longer(segments, target, source=None):
        return [re.sub(r">([^<]+)<", lambda m: ">" + html.escape(html.unescape(m.group(1)) + " (traducido)",
                                                                 quote=False) + "<", s) for s in segments]

    fake_translator.translate = longer
    result, output = translate(fake_translator, source)
    found = {span["text"].strip(): span for span in spans(output[0])}
    assert round(found["Next steps (traducido)"]["size"]) == 12
    assert round(found["Hire two engineers (traducido)"]["size"]) == 10
    assert all(frame.contains(pymupdf.Rect(span["bbox"])) for span in found.values())
    assert result.warnings == []
