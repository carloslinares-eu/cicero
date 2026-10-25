# Architecture

Cicero is split into a GUI-free **core** that does the work and a Tkinter
**gui** that drives it. The core can be used from scripts or tests without a
display or a Google account.

```text
cicero/
├── app.py            main(): Windows DPI/taskbar setup, Tk root, icon, MainWindow
├── core/
│   ├── job.py           TranslationJob: read → translate in batches → save; Progress, JobResult
│   ├── documents.py     open_document(): picks the reader for .pptx / .docx / .pdf
│   ├── blocks.py        TextBlock, Document protocol, make_block(), apply(), save_atomically()
│   ├── presentation.py  PptxDocument: slides, SmartArt, notes, masters
│   ├── word.py          DocxDocument: body, tables, text boxes, headers/footers, notes, comments
│   ├── pdf.py           PdfDocument: text blocks replaced in place with PyMuPDF
│   ├── segments.py      encode_runs(), decode_runs(): runs ⇄ one HTML string
│   ├── translator.py    Translator protocol, GoogleTranslator (v3), batches(), describe_error()
│   ├── deepl_engine.py  DeepLTranslator: the same protocol on the DeepL API
│   ├── secrets.py       DeepL key in the OS credential store (keyring)
│   ├── credentials.py   load_key_file(), load_default() → CloudAccount
│   ├── review.py        write_review(): the .csv review spreadsheet
│   ├── settings.py      Settings: remembered paths and languages (JSON in the user config folder)
│   └── errors.py        CiceroError and subclasses, with user-facing messages
└── gui/
    ├── main_window.py   layout, connecting, starting/stopping jobs, rendering progress
    ├── widgets.py       LanguageBox: combobox that filters as you type
    └── icon.py          window icon and the header logo (load_image)
```

## Documents

Every file type is read by a class that satisfies the `Document` protocol in
`blocks.py`: `kind`, `unit` ("slide", or None for Word), `page_count`, `blocks` and
`save(path)`. A `TextBlock` holds one paragraph's *runs*, and the only thing it
needs from a run is a `text` attribute it can read and assign, which python-pptx
and python-docx runs both have. Everything after reading (batching, translating,
`apply`, the review spreadsheet) is the same for every type. `open_document`
chooses the class from the file extension.

### Word

`DocxDocument` walks every `<w:p>` in the body and in each header, footer,
footnotes, endnotes and comments part (found through the document part's
relationships; parts python-docx keeps as bytes are parsed and written back like
SmartArt). Walking the XML rather than python-docx's `document.paragraphs` also
reaches tables inside tables and text boxes. Runs are taken from the paragraph,
links (`w:hyperlink`), tracked insertions (`w:ins`), smart tags and content
controls; `docx.text.run.Run` provides the text API, turning `w:tab` and `w:br`
into `\t` and `\n` (which travel as `<span class="tab">` and `<br>`).

python-docx's `Run.text` setter replaces everything in the run, so runs that also
contain a picture, an embedded object, a field marker or a note reference are left
out of the block and never written to. A text box is often stored twice (DrawingML
and a VML fallback); deduplication sends its text once.

### PDF

`PdfDocument` uses [PyMuPDF](https://pymupdf.readthedocs.io/). For each page,
`get_text("dict")` gives blocks → lines → spans with their font, size, flags and
colour. A block is one paragraph; adjacent spans with the same style are merged
into one `PdfSpan` (a plain object with a `text` attribute, so it works as a run),
and lines are joined with a space, rejoining words hyphenated at a line end.
Rotated blocks are skipped.

Saving, page by page:

1. A redaction annotation covers each translated block, and `apply_redactions`
   removes the text under them while keeping images and line art
   (`PDF_REDACT_IMAGE_NONE`, `PDF_REDACT_LINE_ART_NONE`).
2. `insert_htmlbox` lays out the translation as HTML, one `<span>` per run with
   its size, weight, style and colour, CSS generic family, the measured line
   spacing, and centring when the original lines were centred. It shrinks the text
   only if it can't fit (`scale_low=0`).
3. `_layout_rect` first gives the text more room. It was measured before anything
   was removed: every text block and image is an obstacle and every drawn rectangle
   a possible frame. The box grows down, and right for a single left-aligned line,
   up to the nearest obstacle, the frame it sits in or the page margin.

Blocks that didn't fit even when shrunk are counted into `JobResult.warnings`.

## From slide to translation and back

```text
 PptxDocument ─► iter_text_frames()  every slide: shapes (recursing into groups), table cells
             ─► _smartart_parts()   SmartArt data model and cached drawing; then notes
                                     (+ slide masters and their layouts, as slide 0, when asked)
             ─► make_block()         one TextBlock per paragraph that has letters in it
                   runs:   ["Hello ", "bold", " world"]           (formatting lives on the runs)
                   edges:  [("", " "), ("", ""), (" ", "")]        (outer whitespace, restored later)
                   html:   <span id="0">Hello</span><span id="1">bold</span><span id="2">world</span>
             ─► owners               identical HTML is sent once and applied to every copy
             ─► batches()            ≤ 100 segments and ≤ 10 000 characters per request
             ─► translate_text(mime_type="text/html")
                   <span id="0">Hola</span> <span id="2">mundo</span> <span id="1">negrita</span>
             ─► decode_runs()        ["Hola", "negrita", "mundo"] → run.text = edge + text + edge
             ─► PptxDocument.save()  SmartArt XML written back, temp file + os.replace
```

### SmartArt

python-pptx has no SmartArt API and loads its parts as raw bytes. A SmartArt graphic
keeps its text in a *data model* part (`/ppt/diagrams/dataN.xml`, related from the
slide with `…/relationships/diagramData`) and PowerPoint also caches the rendered
graphic, text included, in a *drawing* part (`…/2007/relationships/diagramDrawing`).
Both are found through the slide's relationships, parsed with python-pptx's own
`parse_xml` (so every `<a:p>` is a `CT_TextParagraph` and the normal `_Paragraph` /
`_Run` text API works on them), translated like any other paragraph, and serialised
back into the part before saving (`_XmlBlob`). Translating the cached drawing too
means the graphic shows the translation even before PowerPoint redraws it; since the
two parts hold the same paragraphs, deduplication sends each one only once.

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

## DeepL

`DeepLTranslator` implements the same protocol with the official `deepl` client
(`DeepLClient`), which picks the Free or Pro server from the key. It sends the
same `<span id="N">` HTML with `tag_handling="html"`, so runs are recovered exactly
as with Google. Differences the rest of the code relies on:

- **Request size**: DeepL takes at most 50 texts per request, so each translator
  exposes `max_segments` / `max_characters` and the job batches with them.
- **Languages**: DeepL lists source and target languages separately, and targets
  include regional variants (`EN-GB`, `PT-BR`) that aren't valid sources.
  `languages()` merges them with `source` / `target` flags, which is what the two
  language boxes filter on.
- **Description**: the connection line shows the plan and the character usage from
  `get_usage()`.

The key is a secret string rather than a file, so it isn't stored in
`settings.json`. `secrets.py` keeps it in the system credential store through
`keyring` and treats any failure there as "not remembered". The settings file
stores the chosen engine and, per engine, the last languages, because the two
services use different codes.

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
