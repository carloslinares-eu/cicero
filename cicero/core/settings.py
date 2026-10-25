"""Remembering the user's choices between runs. Only paths and language codes, never keys."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)


def settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "Cicero" / "settings.json"


@dataclass(slots=True)
class Settings:
    engine: str = "google"  # "google" or "deepl"
    key_file: str = ""  # path to the Google service account key; empty means Application Default Credentials
    source_language: str = ""  # Google language codes; empty means detect automatically
    target_language: str = ""
    deepl_source_language: str = ""  # DeepL uses its own codes (EN-GB, PT-BR…)
    deepl_target_language: str = ""
    remember_deepl_key: bool = True  # in the system credential store, see secrets.py
    write_review: bool = False
    include_masters: bool = False
    last_folder: str = ""

    def languages(self, engine: str) -> tuple[str, str]:
        """The (source, target) codes last used with ``engine``."""
        if engine == "deepl":
            return self.deepl_source_language, self.deepl_target_language
        return self.source_language, self.target_language

    def set_languages(self, engine: str, source: str, target: str) -> None:
        if engine == "deepl":
            self.deepl_source_language, self.deepl_target_language = source, target
        else:
            self.source_language, self.target_language = source, target

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.warning("Ignoring unreadable settings file %s", path, exc_info=True)
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known}) if isinstance(data, dict) else cls()

    def save(self, path: Path | None = None) -> None:
        path = path or settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            log.warning("Could not save settings to %s", path, exc_info=True)
