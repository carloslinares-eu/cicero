"""A small client for the Ollama HTTP API (https://docs.ollama.com/api), using only the standard library."""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from cicero.core.errors import OperationCancelled, TranslationError

log = logging.getLogger(__name__)

CHAT_TIMEOUT = 600  # seconds; a slow GPU, or a model partly on the CPU, can take minutes per paragraph
SHORT_TIMEOUT = 10


@dataclass(frozen=True, slots=True)
class PullProgress:
    status: str  # Ollama's own words: "pulling manifest", "pulling 3f2a…", "verifying sha256 digest"…
    completed: int  # bytes downloaded so far, over every file of the model
    total: int  # bytes to download in all (grows as Ollama discovers the files)

    @property
    def fraction(self) -> float:
        return self.completed / self.total if self.total else 0.0


class OllamaClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    # -- information ------------------------------------------------------------

    def version(self, timeout: float = SHORT_TIMEOUT) -> str:
        return self._request("GET", "/api/version", timeout=timeout)["version"]

    def is_up(self) -> bool:
        try:
            self.version(timeout=2)
            return True
        except (OSError, TranslationError, KeyError, ValueError):
            return False

    def installed_models(self) -> set[str]:
        """Names of the downloaded models, as Ollama spells them (``translategemma:4b``)."""
        models = self._request("GET", "/api/tags")["models"]
        return {model["name"] for model in models} | {model.get("model", "") for model in models}

    def has_model(self, name: str) -> bool:
        return _normalize(name) in {_normalize(installed) for installed in self.installed_models()}

    # -- downloads --------------------------------------------------------------

    def pull(self, name: str, on_progress: Callable[[PullProgress], None] | None = None,
             cancel: threading.Event | None = None) -> None:
        """Download a model. Ollama keeps partial downloads, so a stopped pull resumes next time."""
        files: dict[str, tuple[int, int]] = {}  # digest → (completed, total)
        response = self._open("POST", "/api/pull", {"model": name, "stream": True}, timeout=CHAT_TIMEOUT)
        with response:
            for event in _json_lines(response):
                if cancel is not None and cancel.is_set():
                    raise OperationCancelled
                if "error" in event:
                    raise TranslationError(_explain_pull_error(name, event["error"]))
                if "digest" in event and event.get("total"):
                    files[event["digest"]] = (event.get("completed", 0), event["total"])
                if on_progress is not None:
                    completed = sum(done for done, _ in files.values())
                    total = sum(size for _, size in files.values())
                    on_progress(PullProgress(event.get("status", ""), completed, total))
                if event.get("status") == "success":
                    return
        raise TranslationError(f"The download of {name} ended before it was complete. Try again to resume it.")

    def delete(self, name: str) -> None:
        self._request("DELETE", "/api/delete", {"model": name})

    # -- inference --------------------------------------------------------------

    def chat(self, model: str, messages: list[dict], options: dict | None = None, think: bool | None = None,
             response_format: str | dict | None = None, keep_alive: str = "15m") -> str:
        body: dict = {"model": model, "messages": messages, "stream": False, "keep_alive": keep_alive}
        if options:
            body["options"] = options
        if think is not None:
            body["think"] = think
        if response_format is not None:
            body["format"] = response_format
        reply = self._request("POST", "/api/chat", body, timeout=CHAT_TIMEOUT)
        return reply.get("message", {}).get("content", "")

    def load(self, model: str, keep_alive: str = "15m") -> None:
        """Load a model into memory now, so the first paragraph doesn't wait for it."""
        self._request("POST", "/api/generate", {"model": model, "keep_alive": keep_alive}, timeout=CHAT_TIMEOUT)

    def running_models(self) -> list[dict]:
        """Loaded models with ``size`` and ``size_vram`` (bytes), to tell how much sits on the GPU."""
        return self._request("GET", "/api/ps").get("models", [])

    # -- plumbing ---------------------------------------------------------------

    def _open(self, method: str, path: str, body: dict | None = None, timeout: float = SHORT_TIMEOUT):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = _error_text(exc)
            raise TranslationError(f"The local model server refused the request ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise TranslationError(f"Can't reach the local model server at {self.base_url}: {exc.reason}") from exc

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float = SHORT_TIMEOUT) -> dict:
        with self._open(method, path, body, timeout) as response:
            payload = response.read()
        return json.loads(payload) if payload.strip() else {}


def _json_lines(response) -> Iterator[dict]:
    for line in response:
        line = line.strip()
        if line:
            yield json.loads(line)


def _normalize(name: str) -> str:
    name = name.strip().lower()
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


def _error_text(exc: urllib.error.HTTPError) -> str:
    try:
        return json.loads(exc.read()).get("error", exc.reason)
    except (ValueError, OSError, AttributeError):
        return str(exc.reason)


def _explain_pull_error(name: str, error: str) -> str:
    lowered = error.lower()
    if "no space" in lowered or "disk" in lowered:
        return f"There isn't enough disk space to download {name}.\n\n{error}"
    if "not found" in lowered or "does not exist" in lowered:
        return f"{name} isn't available for download any more.\n\n{error}"
    if "dial tcp" in lowered or "timeout" in lowered or "connection" in lowered:
        return f"Can't reach the model library. Check your internet connection and try again.\n\n{error}"
    return f"Downloading {name} failed.\n\n{error}"
