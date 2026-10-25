"""Keeping the DeepL key in the operating system's credential store, never in a plain file.

Windows Credential Manager, the macOS Keychain or the Secret Service on Linux, through
the ``keyring`` package. If no store is available the key simply isn't remembered.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SERVICE = "Cicero"
DEEPL_ACCOUNT = "deepl-auth-key"


def _keyring():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def load_deepl_key() -> str:
    keyring = _keyring()
    if keyring is None:
        return ""
    try:
        return keyring.get_password(SERVICE, DEEPL_ACCOUNT) or ""
    except Exception:  # keyring backends raise their own error types
        log.warning("Could not read the DeepL key from the credential store", exc_info=True)
        return ""


def save_deepl_key(key: str) -> bool:
    """Store the key, or delete it when ``key`` is empty. Returns False if there's no usable store."""
    keyring = _keyring()
    if keyring is None:
        return False
    try:
        if key:
            keyring.set_password(SERVICE, DEEPL_ACCOUNT, key)
        elif keyring.get_password(SERVICE, DEEPL_ACCOUNT) is not None:
            keyring.delete_password(SERVICE, DEEPL_ACCOUNT)
        return True
    except Exception:
        log.warning("Could not update the DeepL key in the credential store", exc_info=True)
        return False
