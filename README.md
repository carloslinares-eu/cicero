<p align="center">
  <img src="cicero/assets/cicero.png" width="64" alt="Cicero icon">
</p>

<h1 align="center">Cicero</h1>

<p align="center">
  Translates PowerPoint presentations with Google Cloud Translation, keeping every slide's layout and formatting.
</p>

<p align="center">
  <img src="docs/images/screenshot.png" width="640" alt="The Cicero window while translating">
</p>

Pick a `.pptx` file and a language. Cicero finds the text on every slide (titles,
text boxes, shapes inside groups, tables and speaker notes), sends it to Google
Cloud Translation and writes a translated copy next to the original. Fonts,
colours, bold words and links stay where they were. The original file is never
changed.

## Features

- **Whole sentences, kept formatting.** Each paragraph is translated as one piece,
  so the translator sees full sentences, and the translated words are put back
  into the original runs, so a bold word stays bold.
- **Everything on the slide.** Titles, placeholders, text boxes, shapes nested in
  groups, table cells and speaker notes.
- **Any language Google supports** (about 190), with automatic detection of the
  source language. Type in the language box to filter the list.
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
    or `sudo dnf install python3-tkinter` (Fedora).
- A **Google Cloud project** with the Cloud Translation API enabled, and a
  service account key for it. The [user guide](docs/USER_GUIDE.md#setting-up-google-cloud)
  walks through it step by step; it takes about five minutes.

Google charges for Cloud Translation by the character, with a monthly free
allowance. See [Cloud Translation pricing](https://cloud.google.com/translate/pricing).

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

1. Click **Browse…** next to **Key file** and choose your Google Cloud service
   account key (a `.json` file). Cicero connects and shows the project name.
2. Click **Browse…** next to **Translate** and choose a `.pptx` file.
3. Choose the language in **Into**. Leave **From** on *Detect automatically* or pick it.
4. Check the **Save as** path (it defaults to `<name> (<language>).pptx` next to the original).
5. Click **Translate**.

The [user guide](docs/USER_GUIDE.md) covers Google Cloud setup, every option,
what is and isn't translated, and troubleshooting.

## How it works

| Step | What happens |
|------|--------------|
| 1. Reading | Every slide is searched for paragraphs with letters in them: shapes (including inside groups), table cells and speaker notes. |
| 2. Packing | Each paragraph's runs are wrapped in numbered `<span>` tags, so the translator sees one sentence but knows which words belonged to which run. |
| 3. Translating | Paragraphs are sent to Cloud Translation v3 in batches of up to 100 (10 000 characters). |
| 4. Saving | Each translation is split back into its runs, keeping their formatting, and the copy is saved through a temporary file. |

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

The tests use a fake translator and never contact Google. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the project layout and conventions.

## Project structure

```text
cicero-translator/
├── cicero/                  the application package
│   ├── app.py               entry point: creates the window
│   ├── core/                all the work, no GUI code
│   │   ├── job.py           read → translate → save, with progress and Stop
│   │   ├── presentation.py  finding text in a .pptx and writing translations back
│   │   ├── segments.py      packing runs into HTML and unpacking the translation
│   │   ├── translator.py    Google Cloud Translation v3 client, batching, error messages
│   │   ├── credentials.py   service account keys and Application Default Credentials
│   │   ├── review.py        the optional .csv review spreadsheet
│   │   ├── settings.py      remembered choices
│   │   └── errors.py
│   ├── gui/                 Tkinter interface
│   │   ├── main_window.py   the main window
│   │   ├── widgets.py       filterable language box
│   │   └── icon.py
│   └── assets/              icon files
├── tests/                   pytest suite
├── docs/                    user guide, architecture notes, screenshot
├── packaging/               PyInstaller recipe and hooks
├── main.py                  launcher for `python main.py` and IDEs
├── pyproject.toml           package metadata
└── requirements*.txt        dependencies
```

## License

Cicero is released under the [GNU General Public License v3.0](LICENSE).
