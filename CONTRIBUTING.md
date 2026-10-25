# Contributing

Thanks for helping improve Cicero!

## Setting up

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Then run the app with `cicero` (or `python -m cicero`) and the tests with `pytest`.
The tests don't need a Google account.

## Guidelines

- **Keep the core free of GUI code.** Anything under `cicero/core/` must work
  without Tkinter, so it can be tested and reused from scripts.
- **Only the GUI thread touches Tk.** Background work hands results back through
  the window's queue or the job's `progress`.
- **Errors are for people.** Raise a `CiceroError` subclass whose message says what
  went wrong and what to do about it; the GUI shows it as is.
- **Never commit credentials.** Keys stay outside the repository; `*.json` is
  ignored for that reason. Tests use `FakeTranslator`, never a real key.
- **Never risk the user's files.** The input presentation is read-only; output goes
  through `save_presentation` (temporary file plus atomic rename).
- Add or update tests in `tests/` for behaviour changes, and run `pytest` before
  sending a change.
- Follow the style of the surrounding code: type hints, short docstrings,
  4-space indentation, lines up to about 120 characters.
- Note user-visible changes in `CHANGELOG.md` under an "Unreleased" heading.
- The icon is drawn in code by `scripts/generate_icon.py`. Change the design there
  and run it to regenerate `cicero/assets/` (the `.ico`, and the 256, 64 and 48 px
  PNGs); don't edit the image files by hand.

## Updating dependencies

`requirements.txt` pins the versions the release was tested with;
`pyproject.toml` gives the compatible ranges. After upgrading, run `pytest`,
translate a real presentation, and build the executable once (the PyInstaller
hooks in `packaging/hooks/` depend on how the Google libraries load their data).

## Releasing

1. Bump `__version__` in `cicero/__init__.py` and move the changelog entries
   under the new version.
2. Build the executable with `pyinstaller packaging/cicero.spec` and try it.
3. Tag the release, e.g. `git tag v2.1.0`.
