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
from tkinter import filedialog, font, messagebox, ttk

from cicero import __app_name__, __version__
from cicero.core.credentials import CloudAccount, load_default, load_key_file
from cicero.core.deepl_engine import DeepLTranslator
from cicero.core.documents import SUPPORTED, is_supported
from cicero.core.errors import CiceroError, OperationCancelled
from cicero.core.job import JobOptions, JobResult, Phase, Progress, TranslationJob
from cicero.core.local import catalog
from cicero.core.local.hardware import detect_gpu, fit_note
from cicero.core.local.ollama import PullProgress
from cicero.core.local.runtime import DownloadProgress, EngineRuntime, OllamaRuntime
from cicero.core.local.translator import LocalTranslator
from cicero.core.secrets import load_deepl_key, save_deepl_key
from cicero.core.settings import Settings
from cicero.core.translator import GoogleTranslator, Language, Translator
from cicero.gui.icon import load_image
from cicero.gui.widgets import LanguageBox

log = logging.getLogger(__name__)

POLL_MS = 100
MUTED = "#5F5F5F"
TAGLINE = "Translates presentations, Word documents and PDFs, keeping their layout and formatting."
AUTOMATIC = "Detect automatically"
KEY_FILE_TYPES = [("Google Cloud key file", "*.json"), ("All files", "*.*")]
ENGINES = {"google": "Google Cloud Translation", "deepl": "DeepL", "local": "Local model (on this computer)"}
READY_GREEN = "dark green"
DOCUMENT_TYPES = [("Presentations, Word documents and PDFs", " ".join(f"*{ext}" for ext in SUPPORTED))]
DOCUMENT_TYPES += [(name, f"*{ext}") for ext, name in SUPPORTED.items()]


class MainWindow:
    def __init__(self, root: tk.Tk | tk.Toplevel, settings: Settings | None = None, autoconnect: bool = True,
                 runtime: EngineRuntime | None = None) -> None:
        self.root = root
        self.settings = settings or Settings.load()
        self.runtime: EngineRuntime = runtime or OllamaRuntime()
        self.local_model = catalog.get(self.settings.local_model)
        self._download_cancel: threading.Event | None = None
        self._download_progress: PullProgress | DownloadProgress | None = None  # written by the download thread
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
        self.local_model_name = tk.StringVar(value=self.local_model.label())
        self.local_status = tk.StringVar()
        self.local_note = tk.StringVar()
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
        self._build_header(outer, row=0)

        service = ttk.LabelFrame(outer, text="Translation service", padding=10)
        service.grid(row=1, column=0, sticky="ew")
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
        # Local: an open-weight model, downloaded once and run by Cicero's private Ollama server.
        self.local_label = ttk.Label(service, text="Model")
        self.local_frame = ttk.Frame(service)
        self.local_frame.columnconfigure(1, weight=1)
        self.model_box = ttk.Combobox(self.local_frame, textvariable=self.local_model_name, state="readonly", width=40,
                                      values=[model.label() for model in catalog.CATALOG])
        self.model_box.grid(row=0, column=0, sticky="w")
        self.model_box.bind("<<ComboboxSelected>>", lambda _e: self._on_local_model_changed())
        self.local_status_label = ttk.Label(self.local_frame, textvariable=self.local_status)
        self.local_status_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.download_button = ttk.Button(service, text="Download", command=self._download_or_remove)
        ttk.Label(self.local_frame, textvariable=self.local_note, foreground=MUTED, wraplength=520).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._service_rows = {
            "google": [(self.google_label, 0), (self.key_entry, 1), (self.key_browse, 2)],
            "deepl": [(self.deepl_label, 0), (self.deepl_entry, 1), (self.remember_check, 2)],
            "local": [(self.local_label, 0), (self.local_frame, 1), (self.download_button, 2)],
        }
        self._show_service_row()

        self.connection_label = ttk.Label(service, textvariable=self.connection_text, foreground="gray40")
        self.connection_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.connect_button = ttk.Button(service, text="Connect", command=self.connect)
        self.connect_button.grid(row=2, column=2, padx=(8, 0), pady=(8, 0), sticky="ew")

        job = ttk.LabelFrame(outer, text="Document", padding=10)
        job.grid(row=2, column=0, sticky="ew", pady=(10, 0))
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
        self.progress.grid(row=3, column=0, sticky="ew", pady=(14, 4))
        bottom = ttk.Frame(outer)
        bottom.grid(row=4, column=0, sticky="ew")
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

    def _build_header(self, parent: ttk.Frame, row: int) -> None:
        """Logo, name, version and a one-line description at the top of the window."""
        header = ttk.Frame(parent)
        header.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(1, weight=1)
        title_font = font.nametofont("TkDefaultFont").copy()
        title_font.configure(size=title_font.cget("size") + 6, weight="bold")
        self._title_font = title_font  # Tk forgets fonts Python no longer references

        large = self.root.winfo_fpixels("1i") >= 120  # pick the sharper logo on high-DPI screens
        self._logo = load_image("cicero-64.png" if large else "cicero-48.png", master=self.root)
        if self._logo is not None:
            ttk.Label(header, image=self._logo).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ttk.Label(header, text=__app_name__, font=title_font).grid(row=0, column=1, sticky="sw")
        self.version_label = ttk.Label(header, text=f"v{__version__}", foreground=MUTED)
        self.version_label.grid(row=0, column=2, sticky="ne")
        ttk.Label(header, text=TAGLINE, foreground=MUTED).grid(row=1, column=1, columnspan=2, sticky="nw")

    def _update_buttons(self) -> None:
        running = self.job is not None
        connected = self.translator is not None
        ready = connected and bool(self.input_path.get().strip()) and bool(self.output_path.get().strip())
        self.translate_button.state(["!disabled"] if ready and not running else ["disabled"])
        self.stop_button.state(["!disabled"] if running else ["disabled"])
        downloading = self._download_cancel is not None
        for widget in (self.key_entry, self.key_browse, self.deepl_entry, self.remember_check,
                       self.input_entry, self.input_browse, self.output_entry, self.output_browse, self.source_box,
                       self.target_box, self.review_check):
            widget.state(["disabled"] if running else ["!disabled"])
        busy = running or downloading
        self.connect_button.state(["disabled"] if busy else ["!disabled"])
        self.engine_box.state(["disabled"] if busy else ["!disabled", "readonly"])
        self.model_box.state(["disabled"] if busy else ["!disabled", "readonly"])
        self.download_button.state(["disabled"] if running else ["!disabled"])
        is_presentation = self._input_suffix() in ("", ".pptx")  # masters only exist in presentations
        self.masters_check.state(["!disabled"] if is_presentation and not running else ["disabled"])

    # ------------------------------------------------------------ connecting

    def _show_service_row(self) -> None:
        for engine, widgets in self._service_rows.items():
            for widget, column in widgets:
                if engine == self.engine:
                    widget.grid(row=1, column=column, sticky=("ew" if column == 1 else "w") + "n",
                                padx=(0, 8) if column == 0 else (8, 0) if column == 2 else 0, pady=(8, 0))
                else:
                    widget.grid_remove()

    def _can_connect_unattended(self) -> bool:
        if self.engine == "local":
            ready = self.runtime.model_ready(self.local_model.ollama_name)
            self._refresh_local_status(ready)
            return ready
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

    # ------------------------------------------------------------ local models

    def _refresh_local_status(self, installed: bool | None = None) -> None:
        """The green mark (or not) next to the model, and the note under it."""
        model = self.local_model
        if installed is None:
            installed = self.runtime.model_ready(model.ollama_name)
        if installed:
            self.local_status.set("✔ Ready")
            self.local_status_label.configure(foreground=READY_GREEN)
            self.download_button.configure(text="Remove…")
        else:
            engine_too = "" if self.runtime.is_available() else " + 1.6 GB engine, once"
            self.local_status.set(f"Not downloaded ({model.download_gb:.1f} GB{engine_too})")
            self.local_status_label.configure(foreground=MUTED)
            self.download_button.configure(text="Download")
        self.local_note.set(f"{model.maker} · {model.summary} · License: {model.license} · "
                            f"{fit_note(model.gpu_gb, detect_gpu())}")

    def _on_local_model_changed(self) -> None:
        model = next(model for model in catalog.CATALOG if model.label() == self.local_model_name.get())
        if model.key == self.local_model.key:
            return
        self.local_model = model
        self.settings.local_model = model.key
        self.settings.save()
        self.translator = None
        self.source_box.set_languages([])
        self.target_box.set_languages([])
        self.connection_text.set("Not connected")
        self.connection_label.configure(foreground="gray40")
        self._update_buttons()
        if self._can_connect_unattended():
            self.connect()

    def _download_or_remove(self) -> None:
        if self._download_cancel is not None:
            self._download_cancel.set()  # the button says "Cancel" while downloading
            self.local_status.set("Stopping the download…")
            return
        if self.runtime.model_ready(self.local_model.ollama_name):
            self._remove_model()
        else:
            self._download()

    def _download(self) -> None:
        """Download the engine if needed, then the model, on a background thread.

        Both continue where they stopped if the download is canceled or interrupted.
        """
        model, runtime = self.local_model, self.runtime
        cancel = threading.Event()
        self._download_cancel = cancel
        self._download_progress = None
        self.translator = None
        self.download_button.configure(text="Cancel")
        self.connection_text.set("Not connected")
        self.connection_label.configure(foreground="gray40")
        self._update_buttons()

        def report(progress: PullProgress | DownloadProgress) -> None:
            self._download_progress = progress

        def work() -> None:
            try:
                if not runtime.is_available():
                    runtime.install(report, cancel)
                runtime.client().pull(model.ollama_name, report, cancel)
            except OperationCancelled:
                self._results.put(lambda: self._on_download_finished("Download paused: click Download to resume."))
            except CiceroError as exc:
                message = str(exc)
                self._results.put(lambda: self._on_download_finished(message, error=True))
            except Exception as exc:
                log.exception("Downloading %s failed", model.name)
                message = f"{exc.__class__.__name__}: {exc}"
                self._results.put(lambda: self._on_download_finished(message, error=True))
            else:
                self._results.put(lambda: self._on_download_finished(None))

        threading.Thread(target=work, name="download", daemon=True).start()

    def _on_download_finished(self, message: str | None, error: bool = False) -> None:
        self._download_cancel = None
        self._download_progress = None
        self.progress.configure(value=0)
        self._refresh_local_status()
        self._update_buttons()
        if message is None:
            self.status_text.set(f"{self.local_model.name} is ready.")
            self.connect()
            return
        self.status_text.set(message if not error else "The download failed.")
        if error:
            messagebox.showerror(f"{__app_name__} - download failed", message, parent=self.root)

    def _render_download(self) -> None:
        progress = self._download_progress
        if self._download_cancel is None or progress is None or self._download_cancel.is_set():
            return
        if isinstance(progress, DownloadProgress):
            what = progress.stage
            done, total = progress.done, progress.total
        else:
            what = f"Downloading {self.local_model.name}"
            done, total = progress.completed, progress.total
        self.progress.configure(value=done / total if total else 0)
        amount = f" {done / 1e9:.2f} of {total / 1e9:.2f} GB" if total else ""
        self.status_text.set(f"{what}…{amount}")
        self.local_status.set(f"{done / total:.0%}" if total else "…")

    def _remove_model(self) -> None:
        model = self.local_model
        if not messagebox.askyesno(__app_name__, f"Remove {model.name} from this computer?\n\nThis frees "
                                   f"{model.download_gb:.1f} GB. You can download it again at any time.",
                                   parent=self.root):
            return
        self.translator = None
        self.connection_text.set("Not connected")
        self.connection_label.configure(foreground="gray40")
        try:
            self.runtime.client().delete(model.ollama_name)
        except CiceroError as exc:
            messagebox.showerror(__app_name__, f"Couldn't remove {model.name}.\n\n{exc}", parent=self.root)
        self._refresh_local_status()
        self._update_buttons()

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

        local_model, runtime = self.local_model, self.runtime
        if engine == "local":
            self.connection_text.set(f"Starting {local_model.name}…")

        def work() -> None:
            try:
                translator: Translator
                if engine == "local":
                    client = runtime.client()
                    if not client.has_model(local_model.ollama_name):
                        raise CiceroError(f"{local_model.name} isn't downloaded yet. Click Download, and Cicero "
                                          "connects by itself when it's ready.")
                    client.load(local_model.ollama_name)  # into GPU memory now, not at the first paragraph
                    translator = LocalTranslator(local_model, client, shared_server=not runtime.owns_server)
                elif engine == "deepl":
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
        if engine == "local":
            self.settings.local_model = self.local_model.key
            self._refresh_local_status(installed=True)
        elif engine == "deepl":
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
        """The job's options, or None after telling the user what to fix."""
        source = Path(self.input_path.get().strip())
        output = Path(self.output_path.get().strip())
        if output.suffix.lower() != source.suffix.lower():
            output = output.with_name(output.name + source.suffix.lower())
            self.output_path.set(str(output))
        target = self.target_box.code
        problem = self._problem_with(source, output, target)
        if problem is not None:
            messagebox.showwarning(__app_name__, problem, parent=self.root)
            return None
        assert target is not None  # _problem_with checked it
        confirmed = str(output) == self._confirmed_output  # the save dialog already asked
        if output.exists() and not confirmed and not messagebox.askyesno(
                __app_name__, f"{output.name} already exists. Replace it?", parent=self.root):
            return None
        return JobOptions(source, output, target, self.source_box.code, self.write_review.get(),
                          self.include_masters.get() and source.suffix.lower() == ".pptx")

    def _problem_with(self, source: Path, output: Path, target: str | None) -> str | None:
        """What is wrong with the files and languages chosen, or None if nothing is."""
        if not source.is_file():
            return f"The file to translate doesn't exist:\n{source}"
        if not is_supported(source):
            return ("Cicero translates PowerPoint .pptx, Word .docx and PDF files. Open older .ppt or .doc files in "
                    "PowerPoint or Word and save them as .pptx or .docx first.")
        if target is None:
            return "Choose the language to translate into."
        if not self.source_box.is_valid:
            return "The “From” language isn't in the list. Choose one, or “Detect automatically”."
        if self.source_box.code and self.source_box.code == target:
            return "The “From” and “Into” languages are the same."
        if not output.parent.is_dir():
            return f"The folder to save into doesn't exist:\n{output.parent}"
        if output.resolve() == source.resolve():
            return "Choose a different file to save the translation to, so the original is kept."
        return None

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
            self.status_text.set(f"{progress.phase.text}…")
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
        self._render_download()
        self.root.after(POLL_MS, self._poll)

    def _on_close(self) -> None:
        if self.job is not None:
            if not messagebox.askyesno(__app_name__, "A translation is running. Stop it and quit?", parent=self.root):
                return
            self.job.cancel()
        if self._download_cancel is not None:
            self._download_cancel.set()
        self.runtime.stop()  # Cicero's own model server; one the user runs themselves is left alone
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
