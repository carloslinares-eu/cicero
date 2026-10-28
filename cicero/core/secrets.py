"""Keeping the DeepL key in the operating system's credential store, never in a plain file.

Windows Credential Manager, the macOS Keychain or the Secret Service on Linux, through
the ``keyring`` package. If no store is available the key simply isn't remembered.
"""

from __future__ import annotations

import logging
from types import ModuleType

log = logging.getLogger(__name__)

SERVICE = "Cicero"
DEEPL_ACCOUNT = "deepl-auth-key"


def _store() -> ModuleType | None:
    """The ``keyring`` module, or None if it isn't installed."""
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def load_deepl_key() -> str:
    store = _store()
    if store is None:
        return ""
    # noinspection PyBroadException
    try:
        return store.get_password(SERVICE, DEEPL_ACCOUNT) or ""
    except Exception:  # each backend (Windows, macOS, D-Bus Secret Service…) raises its own error types
        log.warning("Could not read the DeepL key from the credential store", exc_info=True)
        return ""


def save_deepl_key(key: str) -> bool:
    """Store the key, or delete it when ``key`` is empty. Returns False if there's no usable store."""
    store = _store()
    if store is None:
        return False
    # noinspection PyBroadException
    try:
        if key:
            store.set_password(SERVICE, DEEPL_ACCOUNT, key)
        elif store.get_password(SERVICE, DEEPL_ACCOUNT) is not None:
            store.delete_password(SERVICE, DEEPL_ACCOUNT)
        return True
    except Exception:  # as above: there is no common base class for the backends' errors
        log.warning("Could not update the DeepL key in the credential store", exc_info=True)
        return False
