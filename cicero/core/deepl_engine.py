"""Talking to DeepL, the alternative translation service."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import deepl

from cicero.core.errors import CredentialsError, TranslationError
from cicero.core.translator import Language

log = logging.getLogger(__name__)

# DeepL accepts up to 50 texts and 128 KiB per request.
MAX_SEGMENTS_PER_REQUEST = 50
MAX_CHARACTERS_PER_REQUEST = 30_000
REQUEST_TIMEOUT = 120


class DeepLTranslator:
    """DeepL API client. Works with both Free (keys ending in ``:fx``) and Pro keys."""

    name = "DeepL"
    max_segments = MAX_SEGMENTS_PER_REQUEST
    max_characters = MAX_CHARACTERS_PER_REQUEST

    def __init__(self, auth_key: str, client: deepl.DeepLClient | None = None) -> None:
        auth_key = auth_key.strip()
        if not auth_key and client is None:
            raise CredentialsError("Enter your DeepL authentication key. It is under Account → API Keys on deepl.com.")
        self.free = auth_key.endswith(":fx")
        self._client = client or deepl.DeepLClient(auth_key)

    @property
    def description(self) -> str:
        plan = "DeepL API Free" if self.free else "DeepL API Pro"
        try:
            with _friendly_errors():
                usage = self._client.get_usage().character
        except TranslationError:
            return plan
        if usage.valid and usage.limit:
            return f"{plan} · {usage.count:,} of {usage.limit:,} characters used this period"
        return plan

    def languages(self) -> list[Language]:
        """Source and target languages merged into one list. Targets include regional variants (EN-GB, PT-BR)."""
        with _friendly_errors():
            sources = {language.code.upper(): language.name for language in self._client.get_source_languages()}
            targets = {language.code.upper(): language.name for language in self._client.get_target_languages()}
        merged = {code: Language(code, name, source=True, target=code in targets) for code, name in sources.items()}
        for code, name in targets.items():
            if code not in merged:
                merged[code] = Language(code, name, source=False, target=True)
        return sorted(merged.values(), key=lambda language: language.name.casefold())

    def translate(self, html_segments: Sequence[str], target: str, source: str | None = None) -> list[str]:
        if not html_segments:
            return []
        with _friendly_errors():
            results = self._client.translate_text(
                list(html_segments),
                target_lang=target,
                source_lang=source or None,
                tag_handling="html",  # keeps our <span id="N"> run markers in place
                preserve_formatting=True,
            )
        results = results if isinstance(results, list) else [results]
        if len(results) != len(html_segments):
            raise TranslationError(f"DeepL returned {len(results)} translations for {len(html_segments)} texts.")
        return [result.text for result in results]


@contextmanager
def _friendly_errors() -> Iterator[None]:
    try:
        yield
    except deepl.AuthorizationException as exc:
        raise TranslationError(f"DeepL rejected the authentication key. Check it under Account → API Keys on "
                               f"deepl.com.\n\n{exc}") from exc
    except deepl.QuotaExceededException as exc:
        raise TranslationError(f"Your DeepL character quota for this period is used up.\n\n{exc}") from exc
    except deepl.TooManyRequestsException as exc:
        raise TranslationError(f"DeepL is receiving too many requests. Wait a minute and try again.\n\n{exc}") from exc
    except deepl.ConnectionException as exc:
        raise TranslationError(f"Can't reach DeepL. Check your internet connection.\n\n{exc}") from exc
    except deepl.DeepLException as exc:
        log.warning("DeepL request failed", exc_info=True)
        message = str(exc)
        if "target_lang" in message or "source_lang" in message:
            message = f"DeepL doesn't support this language combination.\n\n{message}"
        raise TranslationError(f"DeepL returned an error.\n\n{message}") from exc
