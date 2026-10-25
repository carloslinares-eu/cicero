"""Loading the application icon and other bundled images."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

_window_icons: list[tk.PhotoImage] = []  # Tk drops images that Python no longer references


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
            _window_icons.append(image)
    except tk.TclError:
        log.warning("Could not load the application icon", exc_info=True)


def load_image(name: str, master: tk.Misc | None = None) -> tk.PhotoImage | None:
    """Load a PNG from the assets folder, or return None if it can't be read."""
    try:
        return tk.PhotoImage(master=master, file=str(asset_path(name)))
    except tk.TclError:
        log.warning("Could not load image %s", name, exc_info=True)
        return None
