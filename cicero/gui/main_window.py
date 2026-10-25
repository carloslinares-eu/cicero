"""The main window: credentials, file and language choices, progress."""

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
from cicero.core.errors import CiceroError
from cicero.core.job import JobOptions, JobResult, Phase, TranslationJob
from cicero.core.settings import Settings
from cicero.core.translator import GoogleTranslator, Language
from cicero.gui.widgets import LanguageBox

log = logging.getLogger(__name__)

POLL_MS = 100
AUTOMATIC = "Detect automatically"
KEY_FILE_TYPES = [("Google Cloud key file", "*.json"), ("All files", "*.*")]
PRESENTATION_TYPES = [("PowerPoint presentation", "*.pptx")]


class MainWindow:
    def __init__(self, root: tk.Tk | tk.Toplevel, settings: Settings | None = None, autoconnect: bool = True) -> None:
        self.root = root
        self.settings = settings or Settings.load()
        self.translator: GoogleTranslator | None = None
        self.job: TranslationJob | None = None
        self._results: queue.Queue[Callable[[], None]] = queue.Queue()  # work handed back to the GUI thread
        self._auto_output = ""  # the output path we suggested, so we know when the user typed their own
        self._confirmed_output = ""  # chosen in the save dialog, which already asked about replacing it

        self.key_file = tk.StringVar(value=self.settings.key_file)
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.write_review = tk.BooleanVar(value=self.settings.write_review)
        self.connection_text = tk.StringVar(value="Not connected")
        self.status_text = tk.StringVar(value="Choose your Google Cloud key file and connect.")

        self._build()
        self._update_buttons()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(POLL_MS, self._poll)
        if autoconnect and (self.settings.key_file or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")):
            self.connect()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        root = self.root
        root.minsize(560, 0)
        root.columnconfigure(0, weight=1)
        outer = ttk.Frame(root, padding=12)
        outer.grid(sticky="nsew")
        outer.columnconfigure(0, weight=1)

        cloud = ttk.LabelFrame(outer, text="Google Cloud", padding=10)
        cloud.grid(row=0, column=0, sticky="ew")
        cloud.columnconfigure(1, weight=1)
        ttk.Label(cloud, text="Key file").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.key_entry = ttk.Entry(cloud, textvariable=self.key_file)
        self.key_entry.grid(row=0, column=1, sticky="ew")
        self.key_browse = ttk.Button(cloud, text="Browse…", command=self._browse_key_file)
        self.key_browse.grid(row=0, column=2, padx=(8, 0))
        self.connection_label = ttk.Label(cloud, textvariable=self.connection_text, foreground="gray40")
        self.connection_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.connect_button = ttk.Button(cloud, text="Connect", command=self.connect)
        self.connect_button.grid(row=1, column=2, padx=(8, 0), pady=(8, 0), sticky="ew")

        job = ttk.LabelFrame(outer, text="Presentation", padding=10)
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

        self.input_path.trace_add("write", lambda *_: self._suggest_output())
        for variable in (self.input_path, self.output_path):
            variable.trace_add("write", lambda *_: self._update_buttons())

    def _update_buttons(self) -> None:
        running = self.job is not None
        connected = self.translator is not None
        ready = connected and bool(self.input_path.get().strip()) and bool(self.output_path.get().strip())
        self.translate_button.state(["!disabled"] if ready and not running else ["disabled"])
        self.stop_button.state(["!disabled"] if running else ["disabled"])
        for widget in (self.key_entry, self.key_browse, self.connect_button, self.input_entry, self.input_browse,
                       self.output_entry, self.output_browse, self.source_box, self.target_box, self.review_check):
            widget.state(["disabled"] if running else ["!disabled"])

    # ------------------------------------------------------------ connecting

    def connect(self) -> None:
        """Load the credentials and list the languages on a background thread."""
        key_file = self.key_file.get().strip()
        self.translator = None
        self.connect_button.state(["disabled"])
        self.connection_text.set("Connecting…")
        self.connection_label.configure(foreground="gray40")
        self._update_buttons()

        def work() -> None:
            try:
                account: CloudAccount = load_key_file(key_file) if key_file else load_default()
                translator = GoogleTranslator(account)
                languages = translator.languages()
            except CiceroError as exc:
                message = str(exc)
                self._results.put(lambda: self._on_connect_failed(message))
            except Exception as exc:
                log.exception("Connecting failed")
                message = f"{exc.__class__.__name__}: {exc}"
                self._results.put(lambda: self._on_connect_failed(message))
            else:
                self._results.put(lambda: self._on_connected(translator, languages, key_file))

        threading.Thread(target=work, name="connect", daemon=True).start()

    def _on_connected(self, translator: GoogleTranslator, languages: list[Language], key_file: str) -> None:
        self.translator = translator
        self.source_box.set_languages([lang for lang in languages if lang.source])
        self.target_box.set_languages([lang for lang in languages if lang.target])
        self.source_box.set_code(self.settings.source_language or None)
        self.target_box.set_code(self.settings.target_language or None)
        self.connection_text.set(f"✔ Connected to project “{translator.account.project_id}” · "
                                 f"{len(languages)} languages")
        self.connection_label.configure(foreground="dark green")
        self.status_text.set("Choose a presentation and the language to translate it into.")
        self.connect_button.state(["!disabled"])
        self.settings.key_file = key_file
        self.settings.save()
        self._suggest_output()
        self._update_buttons()

    def _on_connect_failed(self, message: str) -> None:
        self.connection_text.set("✖ Not connected")
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
        path = filedialog.askopenfilename(parent=self.root, title="Presentation to translate",
                                          filetypes=PRESENTATION_TYPES,
                                          initialdir=self._initial_dir(self.input_path.get()))
        if path:
            self.input_path.set(os.path.normpath(path))
            self.settings.last_folder = str(Path(path).parent)

    def _browse_output(self) -> None:
        current = self.output_path.get().strip()
        path = filedialog.asksaveasfilename(parent=self.root, title="Save the translation as",
                                            filetypes=PRESENTATION_TYPES, defaultextension=".pptx",
                                            initialdir=self._initial_dir(current or self.input_path.get()),
                                            initialfile=Path(current).name if current else "")
        if path:
            self.output_path.set(os.path.normpath(path))
            self._auto_output = ""
            self._confirmed_output = os.path.normpath(path)

    def _suggest_output(self) -> None:
        """Fill in ``<input> (<language>).pptx`` until the user picks their own output path."""
        current = self.output_path.get().strip()
        source = self.input_path.get().strip()
        if not source or (current and current != self._auto_output):
            return
        code = self.target_box.code
        stem = Path(source).stem
        suggestion = str(Path(source).with_name(f"{stem} ({code}).pptx" if code else f"{stem} (translated).pptx"))
        self._auto_output = suggestion
        self.output_path.set(suggestion)

    # ------------------------------------------------------------- the job

    def _validate(self) -> JobOptions | None:
        def problem(message: str) -> None:
            messagebox.showwarning(__app_name__, message, parent=self.root)

        source = Path(self.input_path.get().strip())
        output_text = self.output_path.get().strip()
        if not source.is_file():
            return problem(f"The presentation to translate doesn't exist:\n{source}")
        if source.suffix.lower() != ".pptx":
            return problem("Cicero translates PowerPoint .pptx files. Open older .ppt files in PowerPoint "
                           "and save them as .pptx first.")
        if self.target_box.code is None:
            return problem("Choose the language to translate into.")
        if not self.source_box.is_valid:
            return problem("The “From” language isn't in the list. Choose one, or “Detect automatically”.")
        if self.source_box.code and self.source_box.code == self.target_box.code:
            return problem("The “From” and “Into” languages are the same.")
        output = Path(output_text)
        if output.suffix.lower() != ".pptx":
            output = output.with_name(output.name + ".pptx")
            self.output_path.set(str(output))
        if not output.parent.is_dir():
            return problem(f"The folder to save into doesn't exist:\n{output.parent}")
        if output.resolve() == source.resolve():
            return problem("Choose a different file to save the translation to, so the original is kept.")
        confirmed = str(output) == self._confirmed_output  # the save dialog already asked
        if output.exists() and not confirmed and not messagebox.askyesno(
                __app_name__, f"{output.name} already exists. Replace it?", parent=self.root):
            return None
        return JobOptions(source, output, self.target_box.code, self.source_box.code, self.write_review.get())

    def start(self) -> None:
        if self.job is not None or self.translator is None:
            return
        options = self._validate()
        if options is None:
            return
        self.settings.source_language = options.source_language or ""
        self.settings.target_language = options.target_language
        self.settings.write_review = options.write_review
        self.settings.save()

        job = TranslationJob(self.translator, options)
        self.job = job
        self.progress.configure(value=0)
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
        self.status_text.set(f"Done in {result.elapsed:.0f} s: {result.paragraphs} paragraphs on "
                             f"{result.slides} slides ({result.characters:,} characters).")
        lines = [f"The translation was saved as:\n{result.output_path}"]
        if result.review_path:
            lines.append(f"Review spreadsheet:\n{result.review_path}")
        if result.paragraphs == 0:
            lines.append("No text was found to translate, so the copy is identical to the original.")
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
            self.status_text.set(f"Translating… {progress.characters_done:,} of "
                                 f"{progress.characters_total:,} characters ({progress.fraction:.0%})")
        else:
            self.status_text.set(f"{progress.phase.value}…")

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
