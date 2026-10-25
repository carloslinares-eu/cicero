"""Loading the application icon."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def asset_path(name: str) -> Path:
    return ASSETS_DIR / name


def apply_window_icon(root: tk.Tk) -> None:
    """Set the icon used by the title bar, taskbar and every dialog of the app."""
    try:
        if sys.platform == "win32":
            root.iconbitmap(default=str(asset_path("cicero.ico")))
        else:  # .ico isn't supported by Tk outside Windows
            image = tk.PhotoImage(master=root, file=str(asset_path("cicero.png")))
            root.iconphoto(True, image)
            root._cicero_icon = image  # Tk only keeps a weak reference
    except tk.TclError:
        log.warning("Could not load the application icon", exc_info=True)
