"""The main window: translation service, file and language choices, progress."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cicero import __app_name__
from cicero.core.credentials import CloudAccount, load_default, load_key_file
from cicero.core.deepl_engine import DeepLTranslator
from cicero.core.documents import SUPPORTED, is_supported
from cicero.core.errors import CiceroError
from cicero.core.job import JobOptions, JobResult, Phase, Progress, TranslationJob
from cicero.core.secrets import load_deepl_key, save_deepl_key
from cicero.core.settings import Settings
from cicero.core.translator import GoogleTranslator, Language, Translator
from cicero.gui.widgets import LanguageBox

log = logging.getLogger(__name__)

POLL_MS = 100
AUTOMATIC = "Detect automatically"
KEY_FILE_TYPES = [("Google Cloud key file", "*.json"), ("All files", "*.*")]
ENGINES = {"google": "Google Cloud Translation", "deepl": "DeepL"}
DOCUMENT_TYPES = [("Presentations, Word documents and PDFs", " ".join(f"*{ext}" for ext in SUPPORTED))]
DOCUMENT_TYPES += [(name, f"*{ext}") for ext, name in SUPPORTED.items()]


class MainWindow:
    def __init__(self, root: tk.Tk | tk.Toplevel, settings: Settings | None = None, autoconnect: bool = True) -> None:
        self.root = root
        self.settings = settings or Settings.load()
        self.translator: Translator | None = None
        self.engine = self.settings.engine if self.settings.engine in ENGINES else "google"
        self.job: TranslationJob | None = None
        self._results: queue.Queue[Callable[[], None]] = queue.Queue()  # work handed back to the GUI thread
        self._auto_output = ""  # the output path we suggested, so we know when the user typed their own
        self._confirmed_output = ""  # chosen in the save dialog, which already asked about replacing it

        self.key_file = tk.StringVar(value=self.settings.key_file)
        self.engine_name = tk.StringVar(value=ENGINES[self.engine])
        self.deepl_key = tk.StringVar(value=load_deepl_key() if self.settings.remember_deepl_key else "")
        self.remember_deepl_key = tk.BooleanVar(value=self.settings.remember_deepl_key)
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.write_review = tk.BooleanVar(value=self.settings.write_review)
        self.include_masters = tk.BooleanVar(value=self.settings.include_masters)
        self.connection_text = tk.StringVar(value="Not connected")
        self.status_text = tk.StringVar(value="Choose a translation service and connect.")
        self.counters = {name: tk.StringVar() for name in ("pages", "paragraphs", "characters", "time")}

        self._build()
        self._update_buttons()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(POLL_MS, self._poll)
        if autoconnect and self._can_connect_unattended():
            self.connect()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        root = self.root
        root.minsize(560, 0)
        root.columnconfigure(0, weight=1)
        outer = ttk.Frame(root, padding=12)
        outer.grid(sticky="nsew")
        outer.columnconfigure(0, weight=1)

        service = ttk.LabelFrame(outer, text="Translation service", padding=10)
        service.grid(row=0, column=0, sticky="ew")
        service.columnconfigure(1, weight=1)
        ttk.Label(service, text="Service").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.engine_box = ttk.Combobox(service, textvariable=self.engine_name, values=list(ENGINES.values()),
                                       state="readonly", width=32)
        self.engine_box.grid(row=0, column=1, sticky="w")
        self.engine_box.bind("<<ComboboxSelected>>", lambda _e: self._on_engine_changed())

        # Google: a service account key file (or Application Default Credentials when empty).
        self.google_label = ttk.Label(service, text="Key file")
        self.key_entry = ttk.Entry(service, textvariable=self.key_file)
        self.key_browse = ttk.Button(service, text="Browse…", command=self._browse_key_file)
        # DeepL: an authentication key, optionally kept in the system credential store.
        self.deepl_label = ttk.Label(service, text="Auth key")
        self.deepl_entry = ttk.Entry(service, textvariable=self.deepl_key, show="•")
        self.remember_check = ttk.Checkbutton(service, text="Remember", variable=self.remember_deepl_key)
        self._service_rows = {
            "google": [(self.google_label, 0), (self.key_entry, 1), (self.key_browse, 2)],
            "deepl": [(self.deepl_label, 0), (self.deepl_entry, 1), (self.remember_check, 2)],
        }
        self._show_service_row()

        self.connection_label = ttk.Label(service, textvariable=self.connection_text, foreground="gray40")
        self.connection_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.connect_button = ttk.Button(service, text="Connect", command=self.connect)
        self.connect_button.grid(row=2, column=2, padx=(8, 0), pady=(8, 0), sticky="ew")

        job = ttk.LabelFrame(outer, text="Document", padding=10)
        job.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        job.columnconfigure(1, weight=1)
        ttk.Label(job, text="Translate").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.input_entry = ttk.Entry(job, textvariable=self.input_path)
        self.input_entry.grid(row=0, column=1, sticky="ew")
        self.input_browse = ttk.Button(job, text="Browse…", command=self._browse_input)
        self.input_browse.grid(row=0, column=2, padx=(8, 0))

        ttk.Label(job, text="From").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.source_box = LanguageBox(job, automatic_label=AUTOMATIC, width=34)
        self.source_box.set(AUTOMATIC)
        self.source_box.grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(job, text="Into").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.target_box = LanguageBox(job, width=34)
        self.target_box.grid(row=2, column=1, sticky="w", pady=(8, 0))
        self.target_box.bind("<<ComboboxSelected>>", lambda _e: self._suggest_output(), add=True)
        self.target_box.bind("<FocusOut>", lambda _e: self._suggest_output(), add=True)

        ttk.Label(job, text="Save as").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.output_entry = ttk.Entry(job, textvariable=self.output_path)
        self.output_entry.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        self.output_browse = ttk.Button(job, text="Browse…", command=self._browse_output)
        self.output_browse.grid(row=3, column=2, padx=(8, 0), pady=(8, 0))

        self.review_check = ttk.Checkbutton(
            job, text="Also save a review spreadsheet (.csv) with each original paragraph and its translation",
            variable=self.write_review)
        self.review_check.grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.masters_check = ttk.Checkbutton(
            job, text="Also translate slide masters and layouts (footers, labels and placeholder prompts)",
            variable=self.include_masters)
        self.masters_check.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self.progress = ttk.Progressbar(outer, maximum=1.0)
        self.progress.grid(row=2, column=0, sticky="ew", pady=(14, 4))
        bottom = ttk.Frame(outer)
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_text, wraplength=380).grid(row=0, column=0, sticky="w")
        self.stop_button = ttk.Button(bottom, text="Stop", command=self.stop)
        self.stop_button.grid(row=0, column=1, padx=(8, 0))
        self.translate_button = ttk.Button(bottom, text="Translate", command=self.start)
        self.translate_button.grid(row=0, column=2, padx=(8, 0))

        # Status bar: counters for the running job, or what the last one did.
        ttk.Separator(root, orient="horizontal").grid(row=1, column=0, sticky="ew")
        status_bar = ttk.Frame(root, padding=(12, 3))
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)
        for column, variable in enumerate(self.counters.values(), start=1):
            ttk.Label(status_bar, textvariable=variable, foreground="gray30").grid(
                row=0, column=column, padx=(14, 0), sticky="e")

        self.input_path.trace_add("write", lambda *_: self._suggest_output())
        self.input_path.trace_add("write", lambda *_: self._update_buttons())
        for variable in (self.input_path, self.output_path):
            variable.trace_add("write", lambda *_: self._update_buttons())

    def _update_buttons(self) -> None:
        running = self.job is not None
        connected = self.translator is not None
        ready = connected and bool(self.input_path.get().strip()) and bool(self.output_path.get().strip())
        self.translate_button.state(["!disabled"] if ready and not running else ["disabled"])
        self.stop_button.state(["!disabled"] if running else ["disabled"])
        for widget in (self.key_entry, self.key_browse, self.deepl_entry, self.remember_check, self.connect_button,
                       self.input_entry, self.input_browse, self.output_entry, self.output_browse, self.source_box,
                       self.target_box, self.review_check):
            widget.state(["disabled"] if running else ["!disabled"])
        self.engine_box.state(["disabled"] if running else ["!disabled", "readonly"])
        is_presentation = self._input_suffix() in ("", ".pptx")  # masters only exist in presentations
        self.masters_check.state(["!disabled"] if is_presentation and not running else ["disabled"])

    # ------------------------------------------------------------ connecting

    def _show_service_row(self) -> None:
        for engine, widgets in self._service_rows.items():
            for widget, column in widgets:
                if engine == self.engine:
                    widget.grid(row=1, column=column, sticky="ew" if column == 1 else "w",
                                padx=(0, 8) if column == 0 else (8, 0) if column == 2 else 0, pady=(8, 0))
                else:
                    widget.grid_remove()

    def _can_connect_unattended(self) -> bool:
        if self.engine == "deepl":
            return bool(self.deepl_key.get().strip())
        return bool(self.settings.key_file or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))

    def _on_engine_changed(self) -> None:
        engine = next(key for key, name in ENGINES.items() if name == self.engine_name.get())
        if engine == self.engine:
            return
        self.engine = engine
        self.settings.engine = engine
        self.settings.save()
        self.translator = None
        self.source_box.set_languages([])
        self.target_box.set_languages([])
        self.connection_text.set("Not connected")
        self.connection_label.configure(foreground="gray40")
        self._show_service_row()
        self._update_buttons()
        if self._can_connect_unattended():
            self.connect()

    def connect(self) -> None:
        """Load the credentials and list the languages on a background thread."""
        engine = self.engine
        key_file = self.key_file.get().strip()
        deepl_key = self.deepl_key.get().strip()
        self.translator = None
        self.connect_button.state(["disabled"])
        self.connection_text.set("Connecting…")
        self.connection_label.configure(foreground="gray40")
        self._update_buttons()

        def work() -> None:
            try:
                translator: Translator
                if engine == "deepl":
                    translator = DeepLTranslator(deepl_key)
                else:
                    account: CloudAccount = load_key_file(key_file) if key_file else load_default()
                    translator = GoogleTranslator(account)
                languages = translator.languages()
                description = translator.description
            except CiceroError as exc:
                message = str(exc)
                self._results.put(lambda: self._on_connect_failed(message))
            except Exception as exc:
                log.exception("Connecting failed")
                message = f"{exc.__class__.__name__}: {exc}"
                self._results.put(lambda: self._on_connect_failed(message))
            else:
                self._results.put(lambda: self._on_connected(engine, translator, languages, description))

        threading.Thread(target=work, name="connect", daemon=True).start()

    def _on_connected(self, engine: str, translator: Translator, languages: list[Language],
                      description: str) -> None:
        if engine != self.engine:  # the user switched service while this was connecting
            return
        self.translator = translator
        source, target = self.settings.languages(engine)
        self.source_box.set_languages([lang for lang in languages if lang.source])
        self.target_box.set_languages([lang for lang in languages if lang.target])
        self.source_box.set_code(source or None)
        self.target_box.set_code(target or None)
        self.connection_text.set(f"✔ Connected to {translator.name}, {description} · {len(languages)} languages")
        self.connection_label.configure(foreground="dark green")
        self.status_text.set("Choose a presentation, Word document or PDF and the language to translate it into.")
        self.connect_button.state(["!disabled"])
        if engine == "deepl":
            remember = self.remember_deepl_key.get()
            self.settings.remember_deepl_key = remember
            save_deepl_key(self.deepl_key.get().strip() if remember else "")
        else:
            self.settings.key_file = self.key_file.get().strip()
        self.settings.save()
        self._suggest_output()
        self._update_buttons()

    def _on_connect_failed(self, message: str) -> None:
        self.connection_text.set(f"✖ Not connected to {ENGINES[self.engine]}")
        self.connection_label.configure(foreground="firebrick")
        self.connect_button.state(["!disabled"])
        self._update_buttons()
        messagebox.showerror(f"{__app_name__} - can't connect", message, parent=self.root)

    # ----------------------------------------------------------- file fields

    def _initial_dir(self, current: str) -> str | None:
        if current and Path(current).parent.is_dir():
            return str(Path(current).parent)
        return self.settings.last_folder or None

    def _browse_key_file(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Google Cloud service account key",
                                          filetypes=KEY_FILE_TYPES, initialdir=self._initial_dir(self.key_file.get()))
        if path:
            self.key_file.set(os.path.normpath(path))
            self.connect()

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Presentation or document to translate",
                                          filetypes=DOCUMENT_TYPES,
                                          initialdir=self._initial_dir(self.input_path.get()))
        if path:
            self.input_path.set(os.path.normpath(path))
            self.settings.last_folder = str(Path(path).parent)

    def _browse_output(self) -> None:
        current = self.output_path.get().strip()
        suffix = self._input_suffix()
        types = [(SUPPORTED[suffix], f"*{suffix}")] if suffix in SUPPORTED else DOCUMENT_TYPES
        path = filedialog.asksaveasfilename(parent=self.root, title="Save the translation as",
                                            filetypes=types, defaultextension=suffix or ".pptx",
                                            initialdir=self._initial_dir(current or self.input_path.get()),
                                            initialfile=Path(current).name if current else "")
        if path:
            self.output_path.set(os.path.normpath(path))
            self._auto_output = ""
            self._confirmed_output = os.path.normpath(path)

    def _input_suffix(self) -> str:
        return Path(self.input_path.get().strip()).suffix.lower()

    def _suggest_output(self) -> None:
        """Fill in ``<input> (<language>).pptx`` until the user picks their own output path."""
        current = self.output_path.get().strip()
        source = self.input_path.get().strip()
        if not source or (current and current != self._auto_output):
            return
        code = self.target_box.code
        stem, suffix = Path(source).stem, self._input_suffix() or ".pptx"
        suggestion = str(Path(source).with_name(f"{stem} ({code or 'translated'}){suffix}"))
        self._auto_output = suggestion
        self.output_path.set(suggestion)

    # ------------------------------------------------------------- the job

    def _validate(self) -> JobOptions | None:
        def problem(message: str) -> None:
            messagebox.showwarning(__app_name__, message, parent=self.root)

        source = Path(self.input_path.get().strip())
        output_text = self.output_path.get().strip()
        if not source.is_file():
            return problem(f"The file to translate doesn't exist:\n{source}")
        if not is_supported(source):
            return problem("Cicero translates PowerPoint .pptx, Word .docx and PDF files. Open older .ppt or "
                           ".doc files in PowerPoint or Word and save them as .pptx or .docx first.")
        if self.target_box.code is None:
            return problem("Choose the language to translate into.")
        if not self.source_box.is_valid:
            return problem("The “From” language isn't in the list. Choose one, or “Detect automatically”.")
        if self.source_box.code and self.source_box.code == self.target_box.code:
            return problem("The “From” and “Into” languages are the same.")
        output = Path(output_text)
        if output.suffix.lower() != source.suffix.lower():
            output = output.with_name(output.name + source.suffix.lower())
            self.output_path.set(str(output))
        if not output.parent.is_dir():
            return problem(f"The folder to save into doesn't exist:\n{output.parent}")
        if output.resolve() == source.resolve():
            return problem("Choose a different file to save the translation to, so the original is kept.")
        confirmed = str(output) == self._confirmed_output  # the save dialog already asked
        if output.exists() and not confirmed and not messagebox.askyesno(
                __app_name__, f"{output.name} already exists. Replace it?", parent=self.root):
            return None
        return JobOptions(source, output, self.target_box.code, self.source_box.code, self.write_review.get(),
                          self.include_masters.get() and source.suffix.lower() == ".pptx")

    def start(self) -> None:
        if self.job is not None or self.translator is None:
            return
        options = self._validate()
        if options is None:
            return
        self.settings.set_languages(self.engine, options.source_language or "", options.target_language)
        self.settings.write_review = options.write_review
        self.settings.include_masters = options.include_masters
        self.settings.save()

        job = TranslationJob(self.translator, options)
        self.job = job
        self.progress.configure(value=0)
        self._clear_counters()
        self._update_buttons()

        def work() -> None:
            result = job.run()
            self._results.put(lambda: self._on_finished(result))

        threading.Thread(target=work, name="translate", daemon=True).start()

    def stop(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.status_text.set("Stopping after the current request…")

    def _on_finished(self, result: JobResult) -> None:
        self.job = None
        self._update_buttons()
        if result.cancelled:
            self.progress.configure(value=0)
            self.status_text.set("Stopped. Nothing was saved.")
            return
        if result.error:
            self.progress.configure(value=0)
            self.status_text.set("The translation failed.")
            messagebox.showerror(f"{__app_name__} - translation failed", result.error, parent=self.root)
            return

        self.progress.configure(value=1.0)
        assert result.output_path is not None
        self.status_text.set(f"Done in {format_duration(result.elapsed)}.")
        self.counters["pages"].set(f"{result.pages} {result.unit}s" if result.unit else "")
        self.counters["paragraphs"].set(f"{result.paragraphs:,} paragraphs")
        self.counters["characters"].set(f"{result.characters:,} characters")
        self.counters["time"].set(f"{format_duration(result.elapsed)} total")
        lines = [f"The translation was saved as:\n{result.output_path}"]
        if result.review_path:
            lines.append(f"Review spreadsheet:\n{result.review_path}")
        if result.paragraphs == 0:
            lines.append("No text was found to translate, so the copy is identical to the original.")
            if result.kind == "PDF":
                lines.append("If the PDF is a scan (pictures of pages), its text can't be read. Run it through "
                             "OCR first, for example with Adobe Acrobat or ocrmypdf.")
        lines.extend(result.warnings)
        if messagebox.askyesno(f"{__app_name__} - finished", "\n\n".join(lines) + "\n\nOpen it now?",
                               parent=self.root):
            _open_file(result.output_path)

    def _render_progress(self) -> None:
        if self.job is None:
            return
        if self.job.cancelled:
            return  # keep showing "Stopping…"
        progress = self.job.progress
        self.progress.configure(value=progress.fraction)
        if progress.phase is Phase.TRANSLATING and progress.characters_total:
            self.status_text.set(f"Translating… {progress.fraction:.0%}")
        else:
            self.status_text.set(f"{progress.phase.value}…")
        self._render_counters(progress)

    def _render_counters(self, progress: Progress) -> None:
        if progress.paragraphs_total:
            if not progress.unit:
                self.counters["pages"].set("")
            elif progress.page == 0 and progress.paragraphs_done:
                self.counters["pages"].set("Masters and layouts")
            else:
                self.counters["pages"].set(f"{progress.unit.capitalize()} {progress.page or 1} of {progress.pages_total}")
            self.counters["paragraphs"].set(f"Paragraph {progress.paragraphs_done:,} of {progress.paragraphs_total:,}")
            self.counters["characters"].set(f"{progress.characters_done:,} of {progress.characters_total:,} characters")
        remaining = progress.remaining
        left = f" · about {format_duration(remaining)} left" if remaining is not None else ""
        self.counters["time"].set(f"{format_duration(progress.elapsed)} elapsed{left}")

    def _clear_counters(self) -> None:
        for variable in self.counters.values():
            variable.set("")

    def _poll(self) -> None:
        while True:
            try:
                callback = self._results.get_nowait()
            except queue.Empty:
                break
            callback()
        self._render_progress()
        self.root.after(POLL_MS, self._poll)

    def _on_close(self) -> None:
        if self.job is not None:
            if not messagebox.askyesno(__app_name__, "A translation is running. Stop it and quit?", parent=self.root):
                return
            self.job.cancel()
        self.root.destroy()


def format_duration(seconds: float) -> str:
    """``75`` → ``1:15``, ``3725`` → ``1:02:05``."""
    seconds = max(int(round(seconds)), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _open_file(path: Path) -> None:
    """Open a file with the program the system associates with it."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        log.warning("Could not open %s", path, exc_info=True)
