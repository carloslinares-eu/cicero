"""One translation from start to finish, designed to run on a background thread."""

from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from cicero.core.errors import CiceroError, OperationCancelled
from cicero.core.presentation import apply, collect_blocks, open_presentation, save_presentation
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


@dataclass(frozen=True, slots=True)
class Progress:
    phase: Phase
    characters_done: int = 0
    characters_total: int = 0

    @property
    def fraction(self) -> float:
        if self.phase is Phase.FINISHED:
            return 1.0
        if self.characters_total <= 0:
            return 0.0
        return min(self.characters_done / self.characters_total, 1.0)


@dataclass(slots=True)
class JobResult:
    output_path: Path | None = None
    review_path: Path | None = None
    slides: int = 0
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

    def _set_progress(self, phase: Phase, done: int = 0, total: int = 0) -> None:
        with self._lock:
            self._progress = Progress(phase, done, total)

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise OperationCancelled

    def run(self) -> JobResult:
        result = JobResult()
        started = time.monotonic()
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
        presentation = open_presentation(options.input_path)
        blocks = collect_blocks(presentation)
        result.slides = len(presentation.slides)
        result.paragraphs = len(blocks)

        segments = [block.source_html for block in blocks]
        total = sum(len(segment) for segment in segments)
        done = 0
        self._set_progress(Phase.TRANSLATING, done, total)
        for indexes in batches(segments):
            self._check_cancelled()
            chunk = [segments[index] for index in indexes]
            translations = self.translator.translate(chunk, options.target_language, options.source_language)
            for index, translated in zip(indexes, translations):
                apply(blocks[index], translated)
            done += sum(len(segment) for segment in chunk)
            result.characters = done
            self._set_progress(Phase.TRANSLATING, done, total)

        self._check_cancelled()
        self._set_progress(Phase.SAVING, total, total)
        save_presentation(presentation, options.output_path)
        result.output_path = options.output_path
        if options.write_review:
            review = review_path_for(options.output_path)
            try:
                write_review(review, blocks)
                result.review_path = review
            except CiceroError as exc:  # the presentation itself was saved; don't report failure
                result.warnings.append(str(exc))
