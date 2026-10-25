"""Smoke tests for the window. Skipped where no display is available."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from cicero.core.settings import Settings
from tests.conftest import LANGUAGES


@pytest.fixture(scope="module")
def tk_root():
    # One Tk interpreter per process: creating a second one can fail to find tk.tcl in some virtualenvs.
    try:
        interpreter = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    interpreter.withdraw()
    yield interpreter
    interpreter.destroy()


@pytest.fixture
def window(tk_root, tmp_path, monkeypatch, fake_translator):
    from cicero.gui.main_window import MainWindow

    monkeypatch.setattr("cicero.core.settings.settings_path", lambda: tmp_path / "settings.json")
    top = tk.Toplevel(tk_root)
    main = MainWindow(top, settings=Settings(target_language="es"), autoconnect=False)
    yield main
    top.destroy()


def test_suggests_an_output_name(window, fake_translator):
    window.translator = fake_translator
    window.target_box.set_languages(LANGUAGES)
    window.target_box.set_code("es")
    window.input_path.set(str(Path("C:/talks/Deck.pptx")))
    assert window.output_path.get() == str(Path("C:/talks/Deck (es).pptx"))

    window.target_box.set_code("pt-PT")
    window._suggest_output()
    assert window.output_path.get() == str(Path("C:/talks/Deck (pt-PT).pptx"))

    window.output_path.set("C:/elsewhere/mine.pptx")  # typed by the user: never overwritten
    window.input_path.set("C:/talks/Other.pptx")
    assert window.output_path.get() == "C:/elsewhere/mine.pptx"


def test_translate_button_needs_a_connection(window, fake_translator):
    window.input_path.set("C:/a.pptx")
    assert window.translate_button.instate(["disabled"])
    window.translator = fake_translator
    window._update_buttons()
    assert not window.translate_button.instate(["disabled"])


def test_language_box_resolves_typed_text(window):
    box = window.source_box
    box.set_languages(LANGUAGES)
    assert box.code is None and box.is_valid  # "Detect automatically"
    for typed, code in [("es", "es"), ("spanish", "es"), ("zh-cn", "zh-CN"), ("Portug", "pt-PT")]:
        box.set(typed)
        assert box.code == code
    box.set("Klingon")
    assert box.code is None and not box.is_valid


def test_status_bar_counters(window):
    from cicero.core.job import Phase, Progress
    from cicero.gui.main_window import format_duration

    window._render_counters(Progress(Phase.TRANSLATING, characters_done=1500, characters_total=6000,
                                     paragraphs_done=40, paragraphs_total=160, slide=3, slides_total=12,
                                     elapsed=75, translating_for=30))
    assert [v.get() for v in window.counters.values()] == [
        "Slide 3 of 12", "Paragraph 40 of 160", "1,500 of 6,000 characters", "1:15 elapsed · about 1:30 left"]
    assert format_duration(3725) == "1:02:05"
