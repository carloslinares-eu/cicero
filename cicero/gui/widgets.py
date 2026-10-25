"""Reusable widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from cicero.core.translator import Language

_NAVIGATION_KEYS = {"Up", "Down", "Left", "Right", "Return", "Escape", "Tab", "Home", "End",
                    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}


class LanguageBox(ttk.Combobox):
    """A combobox of languages. Typing filters the list by name or code."""

    def __init__(self, master: tk.Misc, automatic_label: str | None = None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.automatic_label = automatic_label  # an extra first entry that means "no language" (None)
        self._languages: list[Language] = []
        self._labels: list[str] = []
        self.bind("<KeyRelease>", self._filter, add=True)
        self.bind("<FocusOut>", self._tidy, add=True)
        self.bind("<<ComboboxSelected>>", self._tidy, add=True)

    def set_languages(self, languages: list[Language]) -> None:
        selected = self.code
        self._languages = list(languages)
        self._labels = ([self.automatic_label] if self.automatic_label else []) + [lang.label for lang in languages]
        self.configure(values=self._labels)
        self.set_code(selected)

    @property
    def code(self) -> str | None:
        """The chosen language code, or None for the automatic entry, nothing chosen or unknown text."""
        language = self._resolve(self.get())
        return language.code if language else None

    @property
    def is_valid(self) -> bool:
        text = self.get().strip()
        return (bool(self.automatic_label) and (not text or text == self.automatic_label)) or self.code is not None

    def set_code(self, code: str | None) -> None:
        for language in self._languages:
            if language.code == code:
                self.set(language.label)
                return
        self.set(self.automatic_label or "")

    def _resolve(self, text: str) -> Language | None:
        wanted = text.strip().casefold()
        if not wanted:
            return None
        for test in (lambda lang: lang.label.casefold() == wanted,
                     lambda lang: lang.code.casefold() == wanted,
                     lambda lang: lang.name.casefold() == wanted):
            for language in self._languages:
                if test(language):
                    return language
        matches = [lang for lang in self._languages if wanted in lang.label.casefold()]
        return matches[0] if len(matches) == 1 else None

    def _filter(self, event: tk.Event) -> None:
        if event.keysym in _NAVIGATION_KEYS:
            return
        wanted = self.get().strip().casefold()
        values = [label for label in self._labels if wanted in label.casefold()] if wanted else self._labels
        self.configure(values=values or self._labels)

    def _tidy(self, _event: tk.Event | None = None) -> None:
        """Replace partial text such as ``span`` with the full label once it's unambiguous."""
        language = self._resolve(self.get())
        if language is not None:
            self.set(language.label)
        self.configure(values=self._labels)
