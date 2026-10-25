# Architecture

Cicero is split into a GUI-free **core** that does the work and a Tkinter
**gui** that drives it. The core can be used from scripts or tests without a
display or a Google account.

```text
cicero/
├── app.py            main(): Windows DPI/taskbar setup, Tk root, icon, MainWindow
├── core/
│   ├── job.py           TranslationJob: read → translate in batches → save; Progress, JobResult
│   ├── presentation.py  open/save, collect_blocks(), apply()
│   ├── segments.py      encode_runs(), decode_runs(): runs ⇄ one HTML string
│   ├── translator.py    Translator protocol, GoogleTranslator (v3), batches(), describe_error()
│   ├── credentials.py   load_key_file(), load_default() → CloudAccount
│   ├── review.py        write_review(): the .csv review spreadsheet
│   ├── settings.py      Settings: remembered paths and languages (JSON in the user config folder)
│   └── errors.py        CiceroError and subclasses, with user-facing messages
└── gui/
    ├── main_window.py   layout, connecting, starting/stopping jobs, rendering progress
    ├── widgets.py       LanguageBox: combobox that filters as you type
    └── icon.py          window icon
```

## From slide to translation and back

```text
 Presentation ─► iter_text_frames()  every slide: shapes (recursing into groups), table cells, notes
             ─► collect_blocks()     one TextBlock per paragraph that has letters in it
                   runs:   ["Hello ", "bold", " world"]           (formatting lives on the runs)
                   edges:  [("", " "), ("", ""), (" ", "")]        (outer whitespace, restored later)
                   html:   <span id="0">Hello</span><span id="1">bold</span><span id="2">world</span>
             ─► batches()            ≤ 100 segments and ≤ 10 000 characters per request
             ─► translate_text(mime_type="text/html")
                   <span id="0">Hola</span> <span id="2">mundo</span> <span id="1">negrita</span>
             ─► decode_runs()        ["Hola", "negrita", "mundo"] → run.text = edge + text + edge
             ─► save_presentation()  temp file + os.replace
```

### Why HTML spans

The original version translated each *run* separately. Runs split wherever the
formatting changes, so a sentence with one bold word became three fragments, each
translated without context. Translating the paragraph's plain text instead would
give good sentences but lose every formatting change inside the paragraph.

Sending HTML gets both: Cloud Translation translates the sentence as a whole and
keeps the tags around the words they wrapped, even when it reorders them.
`decode_runs` parses the result with `html.parser`:

- Text inside `<span id="N">` goes to run *N*.
- Text the translator moved outside every span goes to the run before it, or the
  first run, so no words are ever lost.
- A run whose span disappeared gets empty text. Its formatting stays in the file.
- Entities (`&#39;`, `&amp;`) are decoded. (The old v2 code wrote the escaped form
  into the slides.)

HTML collapses whitespace, so each run's leading and trailing whitespace is cut
off before sending and put back afterwards (`split_edges`), and tabs travel as
`<span class="tab"></span>`.

Paragraphs with no letters (`needs_translation`) aren't sent at all: Google would
return them unchanged and still bill for them.

## Threads

```text
 GUI thread (Tk mainloop)                 background thread
 ────────────────────────                 ─────────────────
 Connect ─► Thread(work) ───────────────► load credentials, translator.languages()
                                          result ─► queue (a callback)
 Translate ─► TranslationJob(...)
            Thread(job.run) ────────────► open, collect, for each batch: translate, apply
 every 100 ms:                                      │
   run callbacks from the queue ◄───────────────────┘ (on finish)
   job.progress ◄── lock ──────────────── _set_progress(phase, done, total)
 Stop ─► job.cancel() ── Event ─────────► checked before every request and before saving
```

- **The GUI thread** never does network or file work. Tkinter isn't thread-safe,
  so background threads never touch widgets: they put a callback on a `queue.Queue`
  that `_poll` runs on the GUI thread.
- **The job** is a plain object with a blocking `run()` that returns a
  `JobResult`. It never raises: `CiceroError`s become `result.error` (their text is
  written for the user) and anything else is logged and summarised.
- **Stop** sets a `threading.Event`. The request already sent finishes (a gRPC call
  can't be withdrawn), then `OperationCancelled` unwinds the job before anything is
  saved.

## Google Cloud Translation

`GoogleTranslator` wraps `translate_v3.TranslationServiceClient`, calling it with
`parent=projects/<project>/locations/global`. The project comes from the key file
(`project_id`) or from Application Default Credentials.

- **Connecting** calls `get_supported_languages(display_language_code="en")`. It
  proves the credentials, the API and the IAM role all work, and fills the
  language boxes, without translating (and paying for) anything.
- **Credentials** are scoped to `cloud-translation` only.
- **Errors** from `google.api_core` and `google.auth` are turned into a
  `TranslationError` by `describe_error`, which recognises the common setup
  mistakes (API disabled, missing role, billing, revoked key, no network) and
  says how to fix each.
- **Limits**: Google accepts up to 1024 strings per request and recommends under
  30 000 characters. Cicero uses 100 strings / 10 000 characters, which keeps the
  progress bar moving and Stop quick.

The `Translator` protocol is what the job depends on; tests pass a fake.

## Saving

`save_presentation` writes to a `.<name>.<random>.cicero-partial` file in the
destination folder and `os.replace`s it onto the final name, so an existing file is
only ever replaced by a complete one. The partial file is removed on any error.

## Tests

`tests/` uses pytest. `conftest.py` builds a real presentation with python-pptx
(title and subtitle, a mixed-format paragraph, tabs, nested groups, a table, notes,
number-only text) and provides `FakeTranslator`, which upper-cases text between
tags like a translator that keeps markup. The job tests run complete
translations and reopen the result; the GUI smoke tests are skipped when no
display is available. No test contacts Google.
