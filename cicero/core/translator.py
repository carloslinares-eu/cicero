"""Talking to Google Cloud Translation (API v3)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import google.api_core.exceptions as api_exceptions
import google.auth.exceptions
from google.cloud import translate_v3

from cicero.core.credentials import CloudAccount
from cicero.core.errors import TranslationError

log = logging.getLogger(__name__)

# Google accepts up to 1024 strings and recommends under 30 000 characters per request.
# Smaller requests keep the progress bar moving and make Stop take effect sooner.
MAX_SEGMENTS_PER_REQUEST = 100
MAX_CHARACTERS_PER_REQUEST = 10_000
REQUEST_TIMEOUT = 120  # seconds


@dataclass(frozen=True, slots=True)
class Language:
    code: str  # BCP-47, e.g. "es", "zh-CN", "pt-PT"
    name: str  # e.g. "Spanish"
    source: bool = True  # can be translated from
    target: bool = True  # can be translated into

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code})"


@dataclass(frozen=True, slots=True)
class SegmentInfo:
    """A paragraph to translate and where it first appears, for translators that use the context."""

    html: str  # as sent to translate()
    page: int  # slide or page number (0 for masters, and for Word documents)
    location: str  # e.g. "Title 1", "Notes", "Body › Table"


@runtime_checkable
class ContextualTranslator(Protocol):
    """A translator that looks at the whole document first (local models). Google and DeepL aren't."""

    def prepare(self, segments: Sequence[SegmentInfo], target: str, source: str | None, *,
                cancel: threading.Event | None = None, unit: str | None = "slide") -> None: ...


class Translator(Protocol):
    """What the rest of Cicero needs from a translation service. Tests use a fake one."""

    name: str  # shown to the user: "Google Cloud Translation", "DeepL"
    max_segments: int  # per request
    max_characters: int  # per request

    @property
    def description(self) -> str:
        """One line about the connection, e.g. the project or the quota used."""

    def languages(self) -> list[Language]: ...

    def translate(self, html_segments: Sequence[str], target: str, source: str | None = None) -> list[str]: ...


class GoogleTranslator:
    """Cloud Translation v3 client for one Google Cloud project."""

    name = "Google Cloud Translation"
    max_segments = MAX_SEGMENTS_PER_REQUEST
    max_characters = MAX_CHARACTERS_PER_REQUEST

    def __init__(self, account: CloudAccount, location: str = "global",
                 client: translate_v3.TranslationServiceClient | None = None) -> None:
        self.account = account
        self.parent = f"projects/{account.project_id}/locations/{location}"
        self._client = client or translate_v3.TranslationServiceClient(credentials=account.credentials)

    @property
    def description(self) -> str:
        return f"project “{self.account.project_id}”"

    def languages(self, display_language: str = "en") -> list[Language]:
        """Every supported language, sorted by name. It is also a cheap way to check the credentials work."""
        with _friendly_errors(self.account.project_id):
            response = self._client.get_supported_languages(
                parent=self.parent, display_language_code=display_language, timeout=REQUEST_TIMEOUT)
        languages = [
            Language(item.language_code, item.display_name or item.language_code,
                     item.support_source, item.support_target)
            for item in response.languages
        ]
        return sorted(languages, key=lambda language: language.name.casefold())

    def translate(self, html_segments: Sequence[str], target: str, source: str | None = None) -> list[str]:
        """Translate one request's worth of HTML strings (see ``batches``)."""
        if not html_segments:
            return []
        with _friendly_errors(self.account.project_id):
            response = self._client.translate_text(
                parent=self.parent,
                contents=list(html_segments),
                mime_type="text/html",
                target_language_code=target,
                source_language_code=source or None,
                timeout=REQUEST_TIMEOUT,
            )
        translations = [item.translated_text for item in response.translations]
        if len(translations) != len(html_segments):
            raise TranslationError(
                f"Google returned {len(translations)} translations for {len(html_segments)} texts.")
        return translations


def batches(segments: Sequence[str], max_segments: int = MAX_SEGMENTS_PER_REQUEST,
            max_characters: int = MAX_CHARACTERS_PER_REQUEST) -> Iterator[range]:
    """Split ``segments`` into consecutive index ranges that each fit in one request.

    A single segment longer than ``max_characters`` gets a request of its own.
    """
    start, characters = 0, 0
    for index, segment in enumerate(segments):
        full = index - start >= max_segments or (characters + len(segment) > max_characters and index > start)
        if full:
            yield range(start, index)
            start, characters = index, 0
        characters += len(segment)
    if start < len(segments):
        yield range(start, len(segments))


@contextmanager
def _friendly_errors(project_id: str) -> Iterator[None]:
    """Turn Google client exceptions into a ``TranslationError`` with an actionable message."""
    try:
        yield
    except TranslationError:
        raise
    except Exception as exc:
        message = describe_error(exc, project_id)
        if message is None:
            raise
        log.warning("Translation request failed", exc_info=True)
        raise TranslationError(message) from exc


def describe_error(exc: BaseException, project_id: str) -> str | None:
    """A message for the user, or None if ``exc`` isn't a Google client error."""
    detail = getattr(exc, "message", None) or str(exc)
    if isinstance(exc, google.auth.exceptions.RefreshError):
        return ("Google rejected the key. It has probably been deleted or disabled, or the service "
                f"account no longer exists.\n\n{detail}")
    if isinstance(exc, google.auth.exceptions.TransportError):
        return f"Can't reach Google Cloud. Check your internet connection.\n\n{detail}"
    if isinstance(exc, google.auth.exceptions.GoogleAuthError):
        return f"Google Cloud sign-in failed.\n\n{detail}"
    if isinstance(exc, api_exceptions.PermissionDenied):
        if "SERVICE_DISABLED" in detail or "has not been used" in detail or "is disabled" in detail:
            return (f"The Cloud Translation API isn't enabled for project “{project_id}”.\n"
                    "Enable it in the Google Cloud console (APIs & Services → Library → Cloud Translation API), "
                    f"wait a minute and try again.\n\n{detail}")
        if "billing" in detail.lower():
            return f"Billing isn't enabled for project “{project_id}”.\n\n{detail}"
        return ("The service account isn't allowed to use Cloud Translation. Give it the "
                f"“Cloud Translation API User” role in project “{project_id}”.\n\n{detail}")
    if isinstance(exc, api_exceptions.Unauthenticated):
        return f"Google didn't accept the credentials.\n\n{detail}"
    if isinstance(exc, api_exceptions.ResourceExhausted):
        return f"The Cloud Translation quota for project “{project_id}” is used up. Try again later.\n\n{detail}"
    if isinstance(exc, api_exceptions.InvalidArgument):
        return f"Google refused the request.\n\n{detail}"
    if isinstance(exc, (api_exceptions.ServiceUnavailable, api_exceptions.DeadlineExceeded)):
        return f"Google Cloud Translation didn't answer in time. Check your connection and try again.\n\n{detail}"
    if isinstance(exc, api_exceptions.GoogleAPICallError):
        return f"Google Cloud Translation returned an error.\n\n{detail}"
    if isinstance(exc, api_exceptions.RetryError):
        return f"Google Cloud Translation kept failing; giving up.\n\n{detail}"
    return None
