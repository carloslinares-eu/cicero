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
    assert result.error is not None and "password-protected" in result.error


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

    def longer(segments, _target, _source=None):
        return [re.sub(r">([^<]+)<", lambda m: ">" + html.escape(html.unescape(m.group(1)) + " (traducido)",
                                                                 quote=False) + "<", s) for s in segments]

    fake_translator.translate = longer
    result, output = translate(fake_translator, source)
    found = {span["text"].strip(): span for span in spans(output[0])}
    assert round(found["Next steps (traducido)"]["size"]) == 12
    assert round(found["Hire two engineers (traducido)"]["size"]) == 10
    assert all(frame.contains(pymupdf.Rect(span["bbox"])) for span in found.values())
    assert result.warnings == []


def test_form_rows_dates_and_addresses_stay_apart(fake_translator, tmp_path):
    source = tmp_path / "invoice.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((60, 120), "Acme GmbH - Hauptstr. 5 - 50968 Köln", fontsize=6)
    for row, text in enumerate(("Erika Mustermann", "Musterweg 12", "DE-80331 München")):
        page.insert_text((60, 134 + 13 * row), text, fontsize=11)
    page.insert_text((420, 200), "29 February 2024", fontsize=9)
    page.insert_text((60, 212), "Premium invoice", fontname="hebo", fontsize=12)
    rows = (("Contract type", "company car"), ("Risk", "see attachment"), ("Policy number", "see attachment"),
            ("Policyholder", "Erika Mustermann"), ("Contact", "service@example.com"))
    for row, (label, value) in enumerate(rows):
        page.insert_text((70, 260 + 17 * row), label, fontsize=10)
        page.insert_text((180, 260 + 17 * row), value, fontsize=10)
    pdf.save(source)

    originals = [block.original for block in open_document(source).blocks]
    assert originals == ["29 February 2024", "Premium invoice", "Contract type", "company car", "Risk",
                         "see attachment", "Policy number", "see attachment", "Policyholder", "Contact"]

    _, output = translate(fake_translator, source)
    found = {span["text"].strip(): span for span in spans(output[0])}
    for kept in ("Acme GmbH - Hauptstr. 5 - 50968 Köln", "Erika Mustermann", "Musterweg 12", "DE-80331 München",
                 "service@example.com"):
        assert kept in found, kept
    assert abs(found["COMPANY CAR"]["bbox"][0] - 180) < 2  # still in the value column
    assert abs(found["29 FEBRUARY 2024"]["bbox"][0] - 420) < 2 and round(found["CONTRACT TYPE"]["size"]) == 10


def test_wrapped_paragraphs_and_list_items_are_whole(sample_pdf, tmp_path):
    source = tmp_path / "prose.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_htmlbox(pymupdf.Rect(50, 50, 300, 800), """
        <p style="line-height:1.6">A paragraph with wide line spacing, as Word sets it with 1.5 lines, which runs
        over several lines of this narrow column.</p>
        <ul><li>Revenue grew eighteen percent year over year, driven by the new subscriptions.</li>
        <li>Churn fell.</li></ul>""", css="* {font-family: sans-serif; font-size: 10pt}")
    pdf.save(source)
    originals = [" ".join(block.original.split()) for block in open_document(source).blocks]
    assert originals == [
        "A paragraph with wide line spacing, as Word sets it with 1.5 lines, which runs over several lines of this "
        "narrow column.",
        "• Revenue grew eighteen percent year over year, driven by the new subscriptions.",
        "• Churn fell.",
    ]


def test_text_traced_from_a_scan_is_left_alone_beside_ordinary_text(fake_translator, tmp_path):
    source = tmp_path / "letterhead.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Letterhead Company", fontname="cour")  # the scanned stationery
    pdf[0].insert_text((72, 120), "Invoice for March", fontname="helv")
    pdf.new_page().insert_text((72, 72), "A scanned page", fontname="cour")  # nothing else: translated
    traced = next(font[0] for font in pdf[0].get_fonts() if font[3] == "Courier")
    pdf.xref_set_key(traced, "BaseFont", "/*Courier-1970")  # how Acrobat's ClearScan names its fonts
    pdf.save(source)

    _, output = translate(fake_translator, source)
    assert "Letterhead Company" in output[0].get_text() and "INVOICE FOR MARCH" in output[0].get_text()
    assert "A SCANNED PAGE" in output[1].get_text()


def test_right_aligned_lines_grow_to_the_left(fake_translator, tmp_path):
    source = tmp_path / "header.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    for y, text in ((60, "Appendix to the invoice"), (72, "Page 2 of 2")):
        page.insert_text((540 - pymupdf.get_text_length(text, fontsize=10), y), text, fontsize=10)
    pdf.save(source)

    fake_translator.translate = lambda segments, _target, _source=None: [
        segment.replace("Appendix to the invoice", "Anexo a la factura correspondiente").replace("Page", "Página")
        for segment in segments]
    _, output = translate(fake_translator, source)
    for text in ("Anexo a la factura correspondiente", "Página 2 of 2"):
        span = next(span for span in spans(output[0]) if span["text"].strip() == text)
        assert abs(span["bbox"][2] - 540) < 2 and round(span["size"]) == 10, text
