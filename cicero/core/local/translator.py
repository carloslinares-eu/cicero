"""LocalTranslator: translating with a model on this computer, through Ollama.

It works like the Google and DeepL translators, with one extra step the job calls
first, ``prepare``, which is where the context strategy lives:

1. If the source language isn't given and the model's prompt needs it
   (TranslateGemma), it is detected from the whole document.
2. A general model reads the whole document once and writes a brief: what it is
   about, for whom, its tone, and a glossary of names and terms with the
   translation to keep using. Specialist models skip this step.
3. Paragraphs are then translated one at a time, in reading order. Each one is
   sent with the brief, the glossary terms it contains, and the paragraphs before
   it on the same slide or page (with their translations), as far as the model
   was trained to use them.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Sequence

from cicero.core.errors import OperationCancelled, TranslationError
from cicero.core.local import languages
from cicero.core.local.catalog import LocalModel, PromptStyle
from cicero.core.local.ollama import OllamaClient
from cicero.core.local.prompts import (
    BRIEF_SCHEMA,
    Brief,
    Context,
    brief_messages,
    clean_answer,
    from_markers,
    parse_brief,
    to_markers,
    translation_messages,
)
from cicero.core.translator import Language, SegmentInfo

log = logging.getLogger(__name__)

BRIEF_CHARACTERS = 16_000  # about 4 000 tokens of the document, read before translating
BRIEF_CONTEXT_TOKENS = 8192
EARLIER_PARAGRAPHS = 3  # how many earlier paragraphs of the same page go with each request
EARLIER_CHARACTERS = 300  # each, at most


class LocalTranslator:
    max_segments = 1  # one paragraph per request: progress moves and Stop works after each one
    max_characters = 100_000

    def __init__(self, model: LocalModel, client: OllamaClient, shared_server: bool = False) -> None:
        self.model = model
        self.client = client
        self.shared_server = shared_server  # True when it's an Ollama the user runs themselves
        self.name = model.name
        self.warnings: list[str] = []
        self.brief: Brief | None = None
        self.detected_source: str | None = None
        self._infos: list[SegmentInfo] = []
        self._positions: dict[str, int] = {}
        self._done: dict[int, tuple[str, str]] = {}  # position → (original, translation), as plain text
        self._untranslated = 0

    @property
    def description(self) -> str:
        where = "through your own Ollama" if self.shared_server else "on this computer"
        return f"running {where}"

    def languages(self) -> list[Language]:
        return languages.language_list(self.model.language_codes)

    # -- before translating ---------------------------------------------------------

    def prepare(self, segments: Sequence[SegmentInfo], target: str, source: str | None,
                on_status: Callable[[str], None] | None = None, cancel: threading.Event | None = None) -> None:
        self._infos = list(segments)
        self._positions = {info.html: position for position, info in enumerate(self._infos)}
        self._done.clear()
        self.warnings.clear()
        self._untranslated = 0
        texts = [to_markers(info.html).text for info in self._infos]
        document = "\n".join(_strip_markers(text) for text in texts)

        if source is None and self.model.needs_source_language and document.strip():
            self.detected_source = detect_language(document, self.model.language_codes)
            if self.detected_source is None:
                raise TranslationError(
                    f"Cicero couldn't tell which language the document is written in, and {self.model.name} "
                    "needs to know. Choose it in “From”.")
            log.info("Detected source language: %s", self.detected_source)

        self.brief = None
        if self.model.reads_whole_document and document.strip():
            if cancel is not None and cancel.is_set():
                raise OperationCancelled
            if on_status:
                on_status("Reading the whole document to understand it")
            self.brief = self._write_brief(document, target, source)

    def _write_brief(self, document: str, target: str, source: str | None) -> Brief:
        excerpt = document[:BRIEF_CHARACTERS]
        options = dict(self.model.options, num_ctx=BRIEF_CONTEXT_TOKENS, temperature=0)
        try:
            answer = self.client.chat(self.model.ollama_name, brief_messages(excerpt, target, source), options,
                                      think=False, response_format=BRIEF_SCHEMA)
        except TranslationError:
            log.warning("Couldn't write the document brief; translating without it", exc_info=True)
            return Brief()
        brief = parse_brief(answer)
        log.info("Brief: %s; %d glossary terms", brief.summary[:200], len(brief.glossary))
        return brief

    # -- translating ----------------------------------------------------------------

    def translate(self, html_segments: Sequence[str], target: str, source: str | None = None) -> list[str]:
        return [self._translate_one(segment, target, source or self.detected_source) for segment in html_segments]

    def _translate_one(self, segment: str, target: str, source: str | None) -> str:
        marked = to_markers(segment)
        position = self._positions.get(segment)
        context = self._context(position)
        answer = self._ask(marked, target, source, context)
        if _suspicious(answer, marked.text):
            # Small models sometimes ramble or answer about the context; once more, plainly and greedily.
            log.info("Retrying a suspicious answer: %r", answer[:200])
            answer = self._ask(marked, target, source, None, retry=True)
        if not answer.strip():
            self._untranslated += 1
            self._update_warning()
            answer = marked.text
        if position is not None:
            self._done[position] = (_strip_markers(marked.text), _strip_markers(answer))
        return from_markers(answer, marked)

    def _ask(self, marked, target: str, source: str | None, context: Context | None, retry: bool = False) -> str:
        options = dict(self.model.options, num_ctx=self.model.context_tokens)
        if retry:
            options["temperature"] = 0
        messages = translation_messages(self.model, marked, target, source, context)
        think = False if self.model.style is PromptStyle.GENERAL else None
        try:
            answer = self.client.chat(self.model.ollama_name, messages, options, think=think)
        except TranslationError as exc:
            raise TranslationError(_explain(self.model, str(exc))) from exc
        return clean_answer(answer, marked.text)

    def _context(self, position: int | None) -> Context | None:
        if position is None:
            return Context(brief=self.brief) if self.brief else None
        page = self._infos[position].page
        earlier = []
        for previous in range(position - 1, -1, -1):
            if self._infos[previous].page != page or len(earlier) == EARLIER_PARAGRAPHS:
                break
            if previous in self._done:
                original, translation = self._done[previous]
                earlier.append((original[:EARLIER_CHARACTERS], translation[:EARLIER_CHARACTERS]))
        return Context(list(reversed(earlier)), self.brief)

    def _update_warning(self) -> None:
        message = (f"{self._untranslated} paragraph(s) came back empty from {self.model.name} and were left in the "
                   "original language.")
        self.warnings[:] = [warning for warning in self.warnings if "came back empty" not in warning] + [message]


def detect_language(text: str, known: list[str]) -> str | None:
    """The language of ``text`` among ``known`` codes, or None if it can't be told."""
    try:
        from langdetect import DetectorFactory, LangDetectException, detect_langs
    except ImportError:
        log.warning("langdetect isn't installed; can't detect the source language")
        return None
    DetectorFactory.seed = 0  # the same answer every time
    try:
        guesses = detect_langs(text[:20_000])
    except LangDetectException:
        return None
    for guess in guesses:
        if guess.prob >= 0.5:
            return languages.from_detected(guess.lang, known)
    return None


def _strip_markers(text: str) -> str:
    return re.sub(r"</?s\d+>", "", text)


def _suspicious(answer: str, source: str) -> bool:
    if not answer.strip():
        return True
    return len(answer) > 3 * len(source) + 120  # far longer than any translation: an explanation or a loop


def _explain(model: LocalModel, error: str) -> str:
    lowered = error.lower()
    if "not found" in lowered:
        return f"{model.name} isn't downloaded. Click Download, wait for the green mark, and try again."
    if "memory" in lowered:
        return (f"{model.name} doesn't fit in this computer's memory. Close other programs, or choose a smaller "
                f"model.\n\n{error}")
    return f"{model.name} couldn't translate a paragraph.\n\n{error}"
