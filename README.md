<p align="center">
  <img src="cicero/assets/cicero-64.png" width="64" alt="Cicero icon: a wise Roman orator with a white beard and a laurel wreath">
</p>

<h1 align="center">Cicero</h1>

<p align="center">
  Translates PowerPoint presentations, Word documents and PDFs with Google Cloud Translation, DeepL or an open model running on your own computer, keeping their layout and formatting.
</p>

<p align="center">
  <img src="docs/images/screenshot.png" width="640" alt="The Cicero window while translating">
</p>

Pick a `.pptx` presentation, a `.docx` Word document or a `.pdf` and a language. Cicero
finds the text on every slide or page (titles, text boxes, shapes inside groups,
tables, SmartArt, speaker notes; in Word also headers, footers and footnotes),
sends it to Google Cloud Translation, DeepL or a model on your own computer, and
writes a translated copy next to the original. Fonts,
colours, bold words and links stay where they were. The original file is never
changed.

## Features

- **Whole sentences, kept formatting.** Each paragraph is translated as one piece,
  so the translator sees full sentences, and the translated words are put back
  into the original runs, so a bold word stays bold.
- **Everything on the slide.** Titles, placeholders, text boxes, shapes nested in
  groups, table cells, SmartArt and speaker notes, and optionally the slide
  masters and layouts.
- **Word documents too.** Body text, tables (including tables in tables), text
  boxes, headers, footers, footnotes, endnotes and comments.
- **PDFs too.** Text is replaced where it stands, in the same font size, weight
  and colour; pictures, drawings and backgrounds stay untouched.
- **Repeated text is translated once.** A footer on every slide is sent to Google
  (and billed) only once.
- **Three ways to translate.** Google Cloud Translation (about 190 languages),
  DeepL (Free or Pro), or an open translation model running on your own graphics
  card: nothing leaves your computer and there is nothing to pay per character.
- **Local models without the hassle.** Pick a model, click **Download**, wait for the
  green ✔ **Ready**. Cicero downloads and runs the model engine (Ollama) by itself,
  hidden, and stops it when you close Cicero. Models for 8 GB and 16 GB graphics
  cards: TranslateGemma 4B and 12B, Hy-MT2 7B and Qwen 3.5 9B.
- **Context-aware local translation.** Models trained for it get the surrounding
  text of each slide or page; a general model first reads the whole document and
  writes a glossary, so names and terms stay consistent.
  Type in the language box to filter the list.
- **Only pays for words.** Numbers, symbols and empty text aren't sent.
- **Review spreadsheet.** Optionally save a `.csv` with each original paragraph
  next to its translation, for proofreading.
- **Responsive.** Translation runs in the background with a progress bar and a
  **Stop** button. Nothing is written until the whole presentation is done.
- **Remembers your setup.** The key file and languages you used last are filled in
  next time (the key itself is never copied).

## Requirements

- Python **3.10 or newer** with Tkinter.
  - Windows and macOS: the installers from [python.org](https://www.python.org/downloads/) include Tkinter.
  - Linux: install it from your package manager, e.g. `sudo apt install python3-tk` (Debian/Ubuntu)
    or `sudo dnf install python3-tkinter` (Fedora). Everything, local models included, is tested
    on Debian and Fedora.
- An account with one of the translation services:
  - **Google Cloud Translation**: a Google Cloud project with the Cloud Translation
    API enabled and a service account key. The [user guide](docs/USER_GUIDE.md#setting-up-google-cloud)
    walks through it; it takes about five minutes.
  - **DeepL**: a [DeepL API](https://www.deepl.com/pro-api) account (the Free plan
    works) and its authentication key. See [Setting up DeepL](docs/USER_GUIDE.md#setting-up-deepl).
  - **A local model**: no account at all. A graphics card with 8 GB or more is
    recommended (NVIDIA, AMD or Apple Silicon); without one, models run on the
    processor, slowly. The first download is the model (3–8 GB) plus, once, the
    1.6 GB engine. See [Local models](docs/USER_GUIDE.md#local-models).

Both services charge by the character, with a monthly free allowance. See
[Cloud Translation pricing](https://cloud.google.com/translate/pricing) and
[DeepL API plans](https://www.deepl.com/pro-api).

## Installation

Clone or download the project, then create a virtual environment inside it.

**Windows (PowerShell)**

```powershell
cd cicero-translator
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install .
```

**macOS / Linux**

```bash
cd cicero-translator
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

`pip install .` adds a `cicero` command that opens the app. Use
`pip install -e ".[dev]"` instead if you plan to change the code.

## Running

Any of these opens the window:

```bash
cicero
```

```bash
python -m cicero
```

```bash
python main.py
```

The last two also work straight from a checkout after `pip install -r requirements.txt`.

## Quick start

1. Choose the **Service**. For Google Cloud Translation, click **Browse…** next to
   **Key file** and choose your service account key (a `.json` file); for DeepL,
   paste your **Auth key** and click **Connect**. For a **Local model**, choose a
   model and click **Download**; when the green ✔ **Ready** appears Cicero connects
   by itself. Cicero shows what it connected to.
2. Click **Browse…** next to **Translate** and choose a `.pptx`, `.docx` or `.pdf` file.
3. Choose the language in **Into**. Leave **From** on *Detect automatically* or pick it.
4. Check the **Save as** path (it defaults to `<name> (<language>).pptx` next to the original).
5. Click **Translate**.

The [user guide](docs/USER_GUIDE.md) covers Google Cloud setup, every option,
what is and isn't translated, and troubleshooting.

## How it works

| Step | What happens |
|------|--------------|
| 1. Reading | The file is searched for paragraphs with letters in them: on slides, shapes (including inside groups), table cells, SmartArt and notes; in Word, the body, tables, text boxes, headers, footers and notes; in a PDF, each block of text. |
| 2. Packing | Each paragraph's runs are wrapped in numbered `<span>` tags, so the translator sees one sentence but knows which words belonged to which run. |
| 3. Translating | Each distinct paragraph is sent once, in batches (Google Cloud Translation v3: up to 100 paragraphs; DeepL: up to 50), with HTML tag handling so the run markers survive. Local models get one paragraph at a time, with the context they were trained to use. |
| 4. Saving | Each translation is split back into its runs, keeping their formatting (in a PDF, the original text is removed and the translation laid out in its place), and the copy is saved through a temporary file. |

More detail is in [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Building a standalone executable

[PyInstaller](https://pyinstaller.org/) can bundle Cicero and Python into a single
program for people who don't have Python installed:

```bash
pip install -r requirements-dev.txt
pyinstaller packaging/cicero.spec
```

The result is `dist/Cicero.exe` on Windows (`dist/Cicero` on macOS/Linux).
Build on the operating system you are targeting.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use fake translators and a fake Ollama server; they never contact Google or DeepL, download models or need a graphics card.

The icon is drawn by `scripts/generate_icon.py`; run it again after changing the design. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the project layout and conventions.

## Project structure

```text
cicero-translator/
├── cicero/                  the application package
│   ├── app.py               entry point: creates the window
│   ├── core/                all the work, no GUI code
│   │   ├── job.py           read → translate → save, with progress and Stop
│   │   ├── documents.py     picking the reader for a file type
│   │   ├── blocks.py        TextBlock and what all document types share
│   │   ├── presentation.py  finding text in a .pptx (slides, SmartArt, masters)
│   │   ├── word.py          finding text in a .docx
│   │   ├── pdf.py           replacing text in a .pdf
│   │   ├── segments.py      packing runs into HTML and unpacking the translation
│   │   ├── translator.py    Google Cloud Translation v3 client, batching, error messages
│   │   ├── deepl_engine.py  DeepL client
│   │   ├── secrets.py       the DeepL key in the system credential store
│   │   ├── local/           open models on this computer, through a private Ollama
│   │   │   ├── catalog.py   the models offered, their prompt style and languages
│   │   │   ├── runtime.py   downloading and running Ollama, hidden
│   │   │   ├── ollama.py    Ollama's HTTP API: models, downloads, chat
│   │   │   ├── prompts.py   each model's prompt, run tags, cleaning answers
│   │   │   ├── translator.py  LocalTranslator and the context strategy
│   │   │   ├── languages.py the languages each model knows
│   │   │   └── hardware.py  graphics memory, to say which models fit
│   │   ├── credentials.py   service account keys and Application Default Credentials
│   │   ├── review.py        the optional .csv review spreadsheet
│   │   ├── settings.py      remembered choices
│   │   └── errors.py
│   ├── gui/                 Tkinter interface
│   │   ├── main_window.py   the main window
│   │   ├── widgets.py       filterable language box
│   │   └── icon.py          window icon and the logo in the header
│   └── assets/              icon files
├── tests/                   pytest suite
├── docs/                    user guide, architecture notes, screenshot
├── packaging/               PyInstaller recipe and hooks
├── scripts/                 icon generator
├── main.py                  launcher for `python main.py` and IDEs
├── pyproject.toml           package metadata
└── requirements*.txt        dependencies
```

## License

Cicero is released under the [GNU General Public License v3.0](LICENSE).
It uses [PyMuPDF](https://pymupdf.readthedocs.io/) for PDFs, which is licensed under the
GNU AGPL v3.0; GPL-3.0 allows the two to be combined.
