"""One translation from start to finish, designed to run on a background thread."""

from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from cicero.core.errors import CiceroError, OperationCancelled
from cicero.core.blocks import apply
from cicero.core.documents import open_document
from cicero.core.review import review_path_for, write_review
from cicero.core.translator import Translator, batches

log = logging.getLogger(__name__)


class Phase(enum.Enum):
    IDLE = "Ready"
    READING = "Reading the presentation"
    TRANSLATING = "Translating"
    SAVING = "Saving"
    FINISHED = "Finished"


@dataclass(frozen=True, slots=True)
class JobOptions:
    input_path: Path
    output_path: Path
    target_language: str
    source_language: str | None = None  # None: let Google detect it
    write_review: bool = False
    include_masters: bool = False  # also translate slide masters and layouts


@dataclass(frozen=True, slots=True)
class Progress:
    phase: Phase
    characters_done: int = 0
    characters_total: int = 0
    paragraphs_done: int = 0
    paragraphs_total: int = 0
    page: int = 0  # slide or page the last translated paragraph is on (0: masters, or no pages)
    pages_total: int = 0
    unit: str | None = None  # what pages are called: "slide", "page", or None for Word documents
    elapsed: float = 0.0  # seconds since the job started
    translating_for: float = 0.0  # seconds spent in the translating phase so far

    @property
    def fraction(self) -> float:
        if self.phase is Phase.FINISHED:
            return 1.0
        if self.characters_total <= 0:
            return 0.0
        return min(self.characters_done / self.characters_total, 1.0)

    @property
    def remaining(self) -> float | None:
        """Estimated seconds left, from the speed so far. None until the first request has come back."""
        if self.phase is not Phase.TRANSLATING or self.characters_done <= 0 or self.translating_for <= 0:
            return None
        rate = self.characters_done / self.translating_for
        return max(self.characters_total - self.characters_done, 0) / rate


@dataclass(slots=True)
class JobResult:
    output_path: Path | None = None
    review_path: Path | None = None
    kind: str = "document"
    unit: str | None = None
    pages: int = 0  # slides in a presentation, pages in a PDF, 0 for Word documents
    paragraphs: int = 0
    characters: int = 0  # characters sent to Google, which is what it bills for
    elapsed: float = 0.0
    cancelled: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return not self.cancelled and self.error is None


class TranslationJob:
    """Read, translate, save. ``run()`` blocks; the GUI calls it on a thread and polls ``progress``."""

    def __init__(self, translator: Translator, options: JobOptions) -> None:
        self.translator = translator
        self.options = options
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._progress = Progress(Phase.IDLE)
        self._started = self._translating_since = time.monotonic()

    @property
    def progress(self) -> Progress:
        with self._lock:
            return self._progress

    def cancel(self) -> None:
        """Stop after the request in flight. Nothing is written once Stop is pressed."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _set_progress(self, phase: Phase, **counters) -> None:
        now = time.monotonic()
        with self._lock:
            previous = self._progress
            if phase is Phase.TRANSLATING and previous.phase is not Phase.TRANSLATING:
                self._translating_since = now
            values = {name: getattr(previous, name) for name in (
                "characters_done", "characters_total", "paragraphs_done", "paragraphs_total", "page", "pages_total", "unit")}
            values.update(counters)
            self._progress = Progress(
                phase, **values, elapsed=now - self._started,
                translating_for=now - self._translating_since if phase is Phase.TRANSLATING else 0.0)

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise OperationCancelled

    def run(self) -> JobResult:
        result = JobResult()
        started = self._started = time.monotonic()
        try:
            self._run(result)
        except OperationCancelled:
            result.cancelled = True
        except CiceroError as exc:
            result.error = str(exc)
        except Exception as exc:  # keep the GUI alive whatever happens; the log has the traceback
            log.exception("Translation failed")
            result.error = f"Unexpected error: {exc.__class__.__name__}: {exc}"
        result.elapsed = time.monotonic() - started
        self._set_progress(Phase.FINISHED if result.succeeded else Phase.IDLE)
        return result

    def _run(self, result: JobResult) -> None:
        options = self.options
        self._set_progress(Phase.READING)
        document = open_document(options.input_path, include_masters=options.include_masters)
        blocks = document.blocks
        result.kind, result.unit, result.pages = document.kind, document.unit, document.page_count
        result.paragraphs = len(blocks)

        # Identical paragraphs (a footer on every slide, SmartArt text that is also in its
        # cached drawing) are sent once and the translation is reused.
        owners: dict[str, list[int]] = {}
        for index, block in enumerate(blocks):
            owners.setdefault(block.source_html, []).append(index)
        segments = list(owners)
        total = sum(len(segment) for segment in segments)
        done = paragraphs_done = 0
        self._set_progress(Phase.TRANSLATING, characters_total=total, paragraphs_total=len(blocks),
                           pages_total=result.pages, unit=result.unit)
        for indexes in batches(segments):
            self._check_cancelled()
            chunk = [segments[index] for index in indexes]
            translations = self.translator.translate(chunk, options.target_language, options.source_language)
            for segment, translated in zip(chunk, translations):
                for index in owners[segment]:
                    apply(blocks[index], translated)
                paragraphs_done += len(owners[segment])
            done += sum(len(segment) for segment in chunk)
            result.characters = done
            self._set_progress(Phase.TRANSLATING, characters_done=done, paragraphs_done=paragraphs_done,
                               page=blocks[owners[chunk[-1]][0]].page)

        self._check_cancelled()
        self._set_progress(Phase.SAVING, characters_done=total)
        document.save(options.output_path)
        result.output_path = options.output_path
        if options.write_review:
            review = review_path_for(options.output_path)
            try:
                write_review(review, blocks, document.unit)
                result.review_path = review
            except CiceroError as exc:  # the presentation itself was saved; don't report failure
                result.warnings.append(str(exc))
