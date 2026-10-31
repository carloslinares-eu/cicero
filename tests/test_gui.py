"""Smoke tests for the window. Skipped where no display is available."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from cicero.core.settings import Settings
from cicero.core.translator import Language
from tests.conftest import LANGUAGES


@pytest.fixture(scope="module")
def tk_root():
    # One Tk interpreter per process: creating a second one can fail to find tk.tcl in some virtualenvs.
    try:
        interpreter = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
        return
    interpreter.withdraw()
    yield interpreter
    interpreter.destroy()


@pytest.fixture
def window(tk_root, tmp_path, monkeypatch, fake_translator):
    from cicero.gui.main_window import MainWindow

    monkeypatch.setattr("cicero.core.settings.settings_path", lambda: tmp_path / "settings.json")
    saved_keys = []
    monkeypatch.setattr("cicero.gui.main_window.load_deepl_key", lambda: "")  # never touch the real keyring
    monkeypatch.setattr("cicero.gui.main_window.save_deepl_key", saved_keys.append)
    top = tk.Toplevel(tk_root)
    main = MainWindow(top, settings=Settings(target_language="es"), autoconnect=False, runtime=FakeRuntime(None))
    yield main
    if top.winfo_exists():
        top.destroy()


class FakeRuntime:
    """Stands in for OllamaRuntime: the engine is a FakeOllama server, installing just flips a flag."""

    owns_server = True

    def __init__(self, url: str | None, available: bool = True) -> None:
        self.url, self.available = url, available
        self.installs = 0
        self.stopped = False

    def is_available(self) -> bool:
        return self.available

    def model_ready(self, name: str) -> bool:
        return name in self.installed

    installed: set = set()

    def install(self, on_progress=None, _cancel=None) -> None:
        from cicero.core.local.runtime import DownloadProgress

        self.installs += 1
        if on_progress:
            on_progress(DownloadProgress("Downloading the local model engine", 5, 10))
        self.available = True

    def client(self):
        from cicero.core.local.ollama import OllamaClient

        return OllamaClient(self.url or "http://127.0.0.1:9")

    def stop(self) -> None:
        self.stopped = True


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
                                     paragraphs_done=40, paragraphs_total=160, page=3, pages_total=12, unit="slide",
                                     elapsed=75, translating_for=30))
    assert [v.get() for v in window.counters.values()] == [
        "Slide 3 of 12", "Paragraph 40 of 160", "1,500 of 6,000 characters", "1:15 elapsed · about 1:30 left"]
    assert format_duration(3725) == "1:02:05"


def test_word_documents_keep_their_extension_and_have_no_masters(window, fake_translator):
    window.translator = fake_translator
    window.target_box.set_languages(LANGUAGES)
    window.target_box.set_code("es")
    window.input_path.set(str(Path("C:/docs/Report.docx")))
    assert window.output_path.get() == str(Path("C:/docs/Report (es).docx"))
    assert window.masters_check.instate(["disabled"])
    window.input_path.set(str(Path("C:/docs/Deck.pptx")))
    assert not window.masters_check.instate(["disabled"])


def test_switching_service_swaps_the_credentials_row(window, fake_translator):
    window.translator = fake_translator
    assert window.key_entry.winfo_manager() == "grid" and not window.deepl_entry.winfo_manager()
    window.engine_name.set("DeepL")
    window._on_engine_changed()
    assert window.deepl_entry.winfo_manager() == "grid" and not window.key_entry.winfo_manager()
    assert window.translator is None and window.settings.engine == "deepl"
    assert window.translate_button.instate(["disabled"])


def test_languages_are_remembered_per_service(window, fake_translator):
    window.settings.set_languages("deepl", "", "EN-GB")
    window.engine = "deepl"
    window._on_connected("deepl", fake_translator, [*LANGUAGES, Language("EN-GB", "English (British)")], "test")
    assert window.target_box.code == "EN-GB"
    assert window.settings.languages("google") == ("", "es")


def test_header_shows_logo_name_and_version(window):
    from cicero import __version__

    assert window.version_label.cget("text") == f"v{__version__}"
    assert window._logo is not None and window._logo.width() in (48, 64)


@pytest.fixture
def local_window(window):
    from tests.fake_ollama import FakeOllama

    server = FakeOllama()
    window.runtime = FakeRuntime(server.url, available=False)
    window.runtime.installed = server.installed
    yield window, server
    server.close()


def wait_for(window, condition, seconds: float = 10) -> None:
    import time

    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        # noinspection PyProtectedMember
        window._poll()  # what the window's own timer calls
        time.sleep(0.02)
    assert condition()


def test_local_model_download_shows_progress_then_the_green_mark(local_window):
    from cicero.core.local.translator import LocalTranslator
    from cicero.gui.main_window import ENGINES, READY_GREEN

    window, server = local_window
    window.engine_name.set(ENGINES["local"])
    window._on_engine_changed()
    assert window.local_status.get() == "Not downloaded (3.3 GB + 1.6 GB engine, once)"
    assert window.download_button.cget("text") == "Download" and window.translator is None
    assert "License: Gemma Terms of Use" in window.local_note.get()

    window._download()
    assert window.download_button.cget("text") == "Cancel" and window.model_box.instate(["disabled"])
    wait_for(window, lambda: isinstance(window.translator, LocalTranslator))
    assert window.runtime.installs == 1 and server.pulls == ["translategemma:4b"]
    assert window.local_status.get() == "✔ Ready"
    assert str(window.local_status_label.cget("foreground")) == READY_GREEN
    assert window.download_button.cget("text") == "Remove…"
    assert window.connection_text.get().startswith("✔ Connected to TranslateGemma 4B, running on this computer")
    assert len(window.target_box.cget("values")) == 55


def test_choosing_a_downloaded_model_connects_and_remove_frees_it(local_window, monkeypatch):
    from cicero.core.local import catalog
    from cicero.gui.main_window import ENGINES

    window, server = local_window
    window.runtime.available = True
    hy_mt = catalog.get("hy-mt2-7b")
    server.installed.add(hy_mt.ollama_name)
    window.engine_name.set(ENGINES["local"])
    window._on_engine_changed()
    assert window.local_status.get().startswith("Not downloaded (3.3 GB)")  # TranslateGemma isn't there
    window.local_model_name.set(hy_mt.label())
    window._on_local_model_changed()
    wait_for(window, lambda: window.translator is not None)
    assert window.settings.local_model == "hy-mt2-7b" and window.local_status.get() == "✔ Ready"

    monkeypatch.setattr("cicero.gui.main_window.messagebox.askyesno", lambda *args, **kwargs: True)
    window._download_or_remove()
    assert hy_mt.ollama_name not in server.installed and window.translator is None
    assert window.download_button.cget("text") == "Download"


def test_closing_stops_the_model_server_cicero_started(window):
    runtime = window.runtime
    window._on_close()
    assert runtime.stopped
