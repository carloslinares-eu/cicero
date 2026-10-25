"""Exceptions with messages written for the person using the app."""


class CiceroError(Exception):
    """Base class. ``str(error)`` is meant to be shown to the user as is."""


class CredentialsError(CiceroError):
    """The Google Cloud key file is missing, unreadable or of the wrong kind."""


class TranslationError(CiceroError):
    """Google Cloud Translation refused or failed a request."""


class DocumentError(CiceroError):
    """The document can't be opened or saved."""


class OperationCancelled(CiceroError):
    """The user pressed Stop."""

    def __init__(self) -> None:
        super().__init__("Cancelled")
