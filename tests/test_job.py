from __future__ import annotations

import csv
from pathlib import Path

from pptx import Presentation

from cicero.core.job import JobOptions, Phase, TranslationJob


def all_text(path: Path) -> list[str]:
    deck = Presentation(str(path))
    texts = []
    for slide in deck.slides:
        for shape in slide.shapes:
            texts.extend(_shape_text(shape))
        if slide.has_notes_slide:
            texts.append(slide.notes_slide.notes_text_frame.text)
    return texts


def _shape_text(shape) -> list[str]:
    if shape.shape_type == 6:  # group
        return [text for child in shape.shapes for text in _shape_text(child)]
    if shape.has_text_frame:
        return [paragraph.text for paragraph in shape.text_frame.paragraphs]
    if getattr(shape, "has_table", False):
        return [cell.text for cell in shape.table.iter_cells()]
    return []


def run_job(translator, source: Path, **options):
    output = source.with_name("out.pptx")
    job = TranslationJob(translator, JobOptions(source, output, "es", **options))
    return job, job.run(), output


def test_translates_every_kind_of_text(fake_translator, sample_deck):
    job, result, output = run_job(fake_translator, sample_deck)
    assert result.succeeded, result.error
    assert job.progress.phase is Phase.FINISHED
    texts = all_text(output)
    for expected in ["QUARTERLY RESULTS", "R&D <DRAFT>", "HELLO BOLD WORLD", "NAME:\t\tCARLOS", "INSIDE GROUP",
                     "NESTED GROUP", "PRODUCT", "PRICE", "APPLE", "SPEAK SLOWLY"]:
        assert expected in texts
    assert "2024 – 42 %" in texts and "3.50" in texts  # nothing to translate, left alone and not sent
    sent = [segment for request in fake_translator.requests for segment in request[0]]
    assert not any("2024" in segment or "3.50" in segment for segment in sent)
    assert result.slides == 3 and result.paragraphs == 10


def test_keeps_run_formatting(fake_translator, sample_deck):
    _, _, output = run_job(fake_translator, sample_deck)
    box = Presentation(str(output)).slides[1].shapes[0]
    runs = box.text_frame.paragraphs[0].runs
    assert [(run.text, run.font.bold) for run in runs] == [("HELLO ", False), ("BOLD", True), (" WORLD", False)]
    assert runs[1].font.size.pt == 18


def test_does_not_add_notes_to_slides_without_them(fake_translator, sample_deck):
    _, _, output = run_job(fake_translator, sample_deck)
    assert [slide.has_notes_slide for slide in Presentation(str(output)).slides] == [True, False, False]


def test_source_language_is_passed_on(fake_translator, sample_deck):
    run_job(fake_translator, sample_deck, source_language="en")
    assert {request[1:] for request in fake_translator.requests} == {("es", "en")}


def test_review_spreadsheet(fake_translator, sample_deck):
    _, result, output = run_job(fake_translator, sample_deck, write_review=True)
    assert result.review_path == output.with_suffix(".csv")
    with open(result.review_path, encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0] == {"Slide": "1", "Location": "Title 1", "Original": "Quarterly results",
                       "Translation": "QUARTERLY RESULTS"}
    assert {"Slide": "1", "Location": "Notes", "Original": "Speak slowly", "Translation": "SPEAK SLOWLY"} in rows


def test_stop_saves_nothing(fake_translator, sample_deck, monkeypatch):
    monkeypatch.setattr("cicero.core.job.batches", lambda segments: ([index] for index in range(len(segments))))
    job = TranslationJob(fake_translator, JobOptions(sample_deck, sample_deck.with_name("out.pptx"), "es"))
    fake_translator.on_request = lambda number: job.cancel() if number == 1 else None
    result = job.run()
    assert result.cancelled and not result.succeeded
    assert len(fake_translator.requests) == 2
    assert not sample_deck.with_name("out.pptx").exists()


def test_errors_are_reported_not_raised(fake_translator, tmp_path):
    bad = tmp_path / "bad.pptx"
    bad.write_text("not a presentation")
    _, result, output = run_job(fake_translator, bad)
    assert "isn't a PowerPoint" in result.error
    assert not output.exists()
    assert list(tmp_path.glob("*.cicero-partial")) == []


def test_progress_counts_paragraphs_slides_and_time(fake_translator, sample_deck, monkeypatch):
    monkeypatch.setattr("cicero.core.job.batches", lambda segments: ([index] for index in range(len(segments))))
    seen = []
    job = TranslationJob(fake_translator, JobOptions(sample_deck, sample_deck.with_name("out.pptx"), "es"))
    fake_translator.on_request = lambda number: seen.append(job.progress)
    job.run()
    assert [p.paragraphs_done for p in seen] == list(range(10))
    assert all(p.paragraphs_total == 10 and p.slides_total == 3 for p in seen)
    assert [p.slide for p in seen[1:]] == [1, 1, 1, 2, 2, 2, 2, 3, 3]  # slide of the paragraph just translated


def test_remaining_time_follows_the_speed_so_far():
    from cicero.core.job import Progress

    progress = Progress(Phase.TRANSLATING, characters_done=250, characters_total=1000, translating_for=10)
    assert progress.remaining == 30
    assert Progress(Phase.SAVING, characters_done=1000, characters_total=1000, translating_for=10).remaining is None
