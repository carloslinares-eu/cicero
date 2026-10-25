"""Application entry point."""

from __future__ import annotations

import ctypes
import logging
import sys
import tkinter as tk

from cicero import __app_name__
from cicero.gui.icon import apply_window_icon
from cicero.gui.main_window import MainWindow

WINDOWS_APP_ID = "Cicero.PresentationTranslator"


def _prepare_windows() -> None:
    """Sharp text on high-DPI screens, and our own taskbar icon instead of Python's."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass


def create_root() -> tk.Tk:
    if sys.platform == "win32":
        _prepare_windows()
    root = tk.Tk(className=__app_name__)
    root.title(f"{__app_name__} - Document Translator")
    apply_window_icon(root)
    return root


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = create_root()
    MainWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
