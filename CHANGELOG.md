# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-10-25

A rewrite on current libraries. The `cicero` package keeps its name but every module is new.

### Added

- One window instead of a login window followed by the main window. Connecting
  happens in the background and the last key file is reconnected at start-up.
- Application Default Credentials (`gcloud auth application-default login`) as an
  alternative to a key file.
- Clear messages for the common Google Cloud setup problems: API not enabled,
  missing IAM role, billing, deleted key, no connection.
- Progress bar and **Stop** button; translation runs on a background thread.
- Language boxes list every language by name and filter as you type. Regional
  variants such as `zh-TW` and `pt-PT` work.
- The output name is suggested as `<name> (<language>).pptx`.
- Optional review spreadsheet (`.csv`, opens in Excel) with each paragraph and its
  translation, replacing the working file that was always left next to the output.
- Remembered settings (key file location, languages, review option).
- Installable package (`pip install .`) with a `cicero` command, `python -m cicero`,
  and a PyInstaller recipe for a standalone executable.
- Documentation (README, user guide with Google Cloud setup, architecture notes)
  and a test suite.

### Changed

- **Google Cloud Translation API v3** (`translate_v3.TranslationServiceClient`)
  replaces the legacy v2 (Basic) client.
- Paragraphs are translated whole instead of run by run, so the translator sees
  complete sentences. Formatting inside a paragraph is kept by sending runs as
  HTML spans and putting each piece back into its run.
- Text without letters (numbers, symbols) isn't sent to Google.
- Credentials are scoped to Cloud Translation only, and checked by listing
  languages instead of translating a test string.
- Output is saved through a temporary file, and never over the original.
- Dependencies updated: google-cloud-translate 3.0.2 → 3.28.0, python-pptx
  0.6.18 → 1.0.2. Unused pins (pandas, PyPDF4, future, pinned transitive
  packages) removed. Python 3.10+.

### Removed

- The PDF option. It was listed in the file dialog but never implemented.
- `setup.py` (its `install_requires` named packages that don't exist on PyPI,
  so it couldn't be installed) in favour of `pyproject.toml`.

### Fixed

- Text inside grouped shapes was never translated, and every group made the
  slide's other text boxes be processed again.
- HTML entities returned by Google were written into slides (`l&#39;été`).
- Text that hit a Unicode error was written into the slides as a Python bytes
  literal (`b'\xc4\x85...'`).
- Language codes were cut to two letters, breaking `zh-CN`, `zh-TW`, `pt-PT`,
  `haw`, `ceb` and others; the source language choice was ignored.
- Batches could exceed Google's request limits on large presentations.
- Opening every slide's notes created empty notes pages in the output.
- Cancelling the file dialog crashed the app; the opened file handle was never closed.
- The icon was looked up relative to the current folder, so the app wouldn't
  start from anywhere else, and `.ico` icons failed on Linux and macOS.

### Security

- Service account keys that had been committed early in the project were removed
  from the entire Git history. `.gitignore` now ignores `*.json` so keys aren't
  committed again.
