"""Finding, downloading and running Ollama for Cicero, out of the user's sight.

In order of preference Cicero uses:

1. an Ollama the user already runs (on its usual port 11434): models are shared;
2. an ``ollama`` program already installed on the computer, started privately;
3. its own copy, downloaded once from Ollama's GitHub releases into Cicero's data
   folder and checked against the release's SHA-256 list.

Cases 2 and 3 run ``ollama serve`` hidden, on a free port of 127.0.0.1 only, and stop
it when Cicero closes. Models go to Ollama's usual folder (``~/.ollama/models``, or
``OLLAMA_MODELS``), so they are shared with any Ollama the user runs themselves.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import queue
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cicero.core.errors import CiceroError, OperationCancelled
from cicero.core.local.ollama import OllamaClient

log = logging.getLogger(__name__)

OLLAMA_RELEASE = "v0.40.12"  # tested with Cicero; bump after checking the new release with a real translation
RELEASES_URL = "https://github.com/ollama/ollama/releases/download"
DEFAULT_URL = "http://127.0.0.1:11434"
START_TIMEOUT = 60  # seconds for `ollama serve` to answer
CHUNK = 1024 * 1024
TAR_FILTERS = hasattr(tarfile, "data_filter")  # Python 3.12+, 3.11.4+; not Debian 12's 3.11.2


class EngineError(CiceroError):
    """The local model engine can't be downloaded or started."""


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    stage: str  # what is happening, for the status line
    done: int  # bytes
    total: int  # bytes, 0 if unknown

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0


def data_dir() -> Path:
    """Where Cicero keeps downloaded programs (not the models, which Ollama keeps)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Cicero"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Cicero"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "cicero"


def models_dir() -> Path:
    """Where Ollama keeps models: ``OLLAMA_MODELS``, or ``.ollama/models`` in the user's home folder."""
    configured = os.environ.get("OLLAMA_MODELS")
    return Path(configured) if configured else Path.home() / ".ollama" / "models"


def model_on_disk(name: str, folder: Path | None = None) -> bool:
    """Whether Ollama has ``name`` downloaded, read from its manifests without starting it.

    ``translategemma:4b`` is ``manifests/registry.ollama.ai/library/translategemma/4b``;
    ``hf.co/user/repo:tag`` is ``manifests/hf.co/user/repo/tag``.
    """
    base, _, tag = name.rpartition(":") if ":" in name.rsplit("/", 1)[-1] else (name, "", "latest")
    parts = base.split("/")
    if "." not in parts[0]:  # no host: the Ollama library
        parts = ["registry.ollama.ai"] + (["library"] if len(parts) == 1 else []) + parts
    manifest = (folder or models_dir()) / "manifests"
    for part in [*parts, tag]:
        if not manifest.is_dir():
            return False
        matches = [entry for entry in manifest.iterdir() if entry.name.lower() == part.lower()]
        if not matches:
            return False
        manifest = matches[0]
    return manifest.is_file()


def release_assets(amd_gpu: bool | None = None) -> list[str]:
    """The Ollama downloads for this computer, unpacked into one folder; empty if there are none.

    The main download covers NVIDIA cards and the processor. AMD cards need Ollama's ROCm
    add-on as well (and AMD's ROCm driver on Linux), which is fetched when one is found.
    """
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if amd_gpu is None:
        from cicero.core.local.hardware import has_amd_gpu

        amd_gpu = has_amd_gpu()
    if sys.platform == "win32":
        if arm:
            return ["ollama-windows-arm64.zip"]
        return ["ollama-windows-amd64.zip"] + (["ollama-windows-amd64-rocm.zip"] if amd_gpu else [])
    if sys.platform == "darwin":
        return ["ollama-darwin.tgz"]
    if sys.platform.startswith("linux"):
        if arm:
            return ["ollama-linux-arm64.tar.zst"]
        if machine in ("x86_64", "amd64"):
            return ["ollama-linux-amd64.tar.zst"] + (["ollama-linux-amd64-rocm.tar.zst"] if amd_gpu else [])
    return []


class EngineRuntime(Protocol):
    """What the window needs from the engine; ``OllamaRuntime`` is the real one, tests pass a fake."""

    @property
    def owns_server(self) -> bool:
        """True while a server Cicero started is running."""

    def is_available(self) -> bool: ...

    def model_ready(self, name: str) -> bool: ...

    def install(self, on_progress: Callable[[DownloadProgress], None] | None = None,
                cancel: threading.Event | None = None) -> object: ...

    def client(self) -> OllamaClient: ...

    def stop(self) -> None: ...


class OllamaRuntime:
    """Owns the Ollama server Cicero talks to. Thread-safe; one per application."""

    def __init__(self, base_dir: Path | None = None, release: str = OLLAMA_RELEASE,
                 releases_url: str = RELEASES_URL, external_url: str | None = DEFAULT_URL) -> None:
        self.base_dir = base_dir or data_dir()
        self.release = release
        self.releases_url = releases_url.rstrip("/")
        self.external_url = external_url  # None: never use an Ollama the user runs (tests)
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._client: OllamaClient | None = None
        self._job_handle = None

    # -- where things are -------------------------------------------------------

    @property
    def install_dir(self) -> Path:
        return self.base_dir / "ollama" / self.release

    def managed_executable(self) -> Path | None:
        name = "ollama.exe" if sys.platform == "win32" else "ollama"
        if not self.install_dir.is_dir():
            return None
        direct = self.install_dir / name
        if direct.is_file():
            return direct
        return next((path for path in self.install_dir.rglob(name) if path.is_file()), None)

    def executable(self) -> Path | None:
        """Cicero's own copy, else an Ollama installed on the computer."""
        managed = self.managed_executable()
        if managed is not None:
            return managed
        installed = shutil.which("ollama")
        return Path(installed) if installed else None

    def is_available(self) -> bool:
        """True if translating can start without downloading the engine first."""
        return self._external_client() is not None or self.executable() is not None

    def model_ready(self, name: str) -> bool:
        """Whether ``name`` is downloaded, without starting a server.

        An Ollama the user runs is asked directly: on Linux it is often a system service
        that keeps models in its own folder (``/usr/share/ollama``), not the user's.
        """
        external = self._external_client()
        if external is not None:
            try:
                return external.has_model(name)
            except CiceroError:
                pass
        return model_on_disk(name)

    # -- starting and stopping ----------------------------------------------------

    def client(self) -> OllamaClient:
        """A client for a running server, starting one if needed. Raises EngineError if there's none."""
        with self._lock:
            current = self._client
            if current is not None and current.is_up():
                return current
            external = self._external_client()
            if external is not None:
                log.info("Using the Ollama already running at %s", external.base_url)
                self._client = external
                return external
            executable = self.executable()
            if executable is None:
                raise EngineError("The local model engine (Ollama) isn't installed yet.")
            started = self._start(executable)
            self._client = started
            return started

    @property
    def owns_server(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop(self) -> None:
        """Stop the server Cicero started (never one the user runs)."""
        with self._lock:
            process, self._process, self._client = self._process, None, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    def _external_client(self) -> OllamaClient | None:
        if self.external_url is None:
            return None
        client = OllamaClient(self.external_url)
        return client if client.is_up() else None

    def _start(self, executable: Path) -> OllamaClient:
        port = _free_port()
        url = f"http://127.0.0.1:{port}"
        env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{port}", OLLAMA_KEEP_ALIVE="15m")
        log_path = self.base_dir / "ollama-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "ab")  # noqa: SIM115 - stays open for the server's lifetime
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
        log.info("Starting %s serve on %s", executable, url)
        try:
            process = _start_in_own_thread(
                [str(executable), "serve"], env=env, stdout=log_file, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=flags, cwd=str(executable.parent),
                preexec_fn=_die_with_parent if sys.platform.startswith("linux") else None)
        except OSError as exc:
            log_file.close()
            raise EngineError(f"Can't start the local model engine:\n{executable}\n\n{exc}") from exc
        self._process = process
        self._job_handle = _kill_with_parent(process)
        client = OllamaClient(url)
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise EngineError(f"The local model engine stopped while starting (exit code {process.returncode}). "
                                    f"Details are in {log_path}.")
            if client.is_up():
                return client
            time.sleep(0.25)
        process.kill()
        raise EngineError(f"The local model engine didn't start within {START_TIMEOUT} s. Details are in {log_path}.")

    # -- installing ---------------------------------------------------------------

    def install(self, on_progress: Callable[[DownloadProgress], None] | None = None,
                cancel: threading.Event | None = None) -> Path:
        """Download and unpack Ollama into Cicero's data folder. A stopped download resumes next time."""
        assets = release_assets()
        if not assets:
            raise EngineError(
                "Cicero can't install the local model engine on this system by itself. Install Ollama from "
                "https://ollama.com/download, then try again: Cicero will use it.")
        downloads = self.base_dir / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        listing = self._checksums()
        archives = []
        for number, asset in enumerate(assets, start=1):
            if asset not in listing:
                raise EngineError(f"Ollama {self.release} has no download for this system ({asset}).")
            stage = "Downloading the local model engine" + (f" ({number} of {len(assets)})" if len(assets) > 1 else "")
            archives.append(self._fetch(asset, listing[asset], downloads, stage, on_progress, cancel))

        if on_progress:
            on_progress(DownloadProgress("Unpacking the local model engine", 0, 0))
        staging = Path(tempfile.mkdtemp(prefix="ollama-", dir=self.base_dir))
        try:
            for archive in archives:  # add-ons unpack over the main download, into the same folders
                _extract(archive, staging)
            if self.install_dir.exists():
                shutil.rmtree(self.install_dir)
            self.install_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, self.install_dir)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        for archive in archives:
            archive.unlink(missing_ok=True)  # 1.6 GB that is no longer needed
        executable = self.managed_executable()
        if executable is None:
            raise EngineError(f"The downloaded engine doesn't contain the ollama program ({assets[0]}).")
        if sys.platform != "win32":
            executable.chmod(executable.stat().st_mode | 0o111)
        return executable

    def _fetch(self, asset: str, expected: str, downloads: Path, stage: str,
               on_progress: Callable[[DownloadProgress], None] | None, cancel: threading.Event | None) -> Path:
        """One archive, downloaded (or resumed) and checked against the release's SHA-256 list."""
        archive = downloads / f"{self.release}-{asset}"
        if archive.is_file() and _sha256(archive) == expected:
            return archive
        partial = archive.with_name(archive.name + ".partial")

        def report(done: int, total: int) -> None:
            if on_progress:
                on_progress(DownloadProgress(stage, done, total))

        _download(f"{self.releases_url}/{self.release}/{asset}", partial, report, cancel)
        if on_progress:
            on_progress(DownloadProgress("Checking the download", 0, 0))
        if _sha256(partial) != expected:
            partial.unlink(missing_ok=True)
            raise EngineError("The downloaded engine is damaged (its checksum doesn't match). Try again.")
        os.replace(partial, archive)
        return archive

    def _checksums(self) -> dict[str, str]:
        """The release's sha256sum.txt as {file name: hash}."""
        url = f"{self.releases_url}/{self.release}/sha256sum.txt"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                listing = response.read().decode()
        except (urllib.error.URLError, OSError) as exc:
            raise EngineError(f"Can't reach GitHub to download the local model engine.\n\n{exc}") from exc
        checksums = {}
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) == 2:
                checksums[parts[1].lstrip("*").removeprefix("./")] = parts[0].lower()
        return checksums


# -- helpers ----------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _download(url: str, target: Path, on_progress: Callable[[int, int], None] | None,
              cancel: threading.Event | None) -> None:
    """Download ``url`` into ``target``, continuing a previous partial download when the server allows it."""
    done = target.stat().st_size if target.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={done}-"} if done else {})
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and done:  # already complete
            return
        raise EngineError(f"Downloading the local model engine failed ({exc.code}).") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise EngineError(f"Can't download the local model engine. Check your internet connection.\n\n{exc}") from exc
    with response:
        resumed = response.status == 206
        if not resumed:
            done = 0
        length = int(response.headers.get("Content-Length") or 0)
        total = done + length if length else 0
        with open(target, "ab" if resumed else "wb") as file:
            while True:
                if cancel is not None and cancel.is_set():
                    raise OperationCancelled
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                file.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    if total and done < total:
        raise EngineError("The download of the local model engine was interrupted. Try again to resume it.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract(archive: Path, target: Path) -> None:
    name = archive.name
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
    elif name.endswith((".tgz", ".tar.gz")):
        with tarfile.open(archive, "r:gz") as bundle:
            _extract_tar(bundle, target)
    elif name.endswith(".tar.zst"):
        _extract_zst(archive, target)
    else:
        raise EngineError(f"Don't know how to unpack {name}.")


def _extract_tar(bundle: tarfile.TarFile, target: Path) -> None:
    """Unpack a tar archive, refusing anything that would land outside ``target``.

    Python 3.12 and 3.11.4+ do this with ``filter="data"``. Debian 12 ships 3.11.2, which
    has no filters, so the same checks are done here, one member at a time (which also
    works on compressed streams).
    """
    if TAR_FILTERS:
        bundle.extractall(target, filter="data")
        return
    root = target.resolve()
    for member in bundle:
        destination = (target / member.name).resolve()
        unsafe = not destination.is_relative_to(root) or member.isdev()
        if member.issym():
            unsafe = unsafe or not (destination.parent / member.linkname).resolve().is_relative_to(root)
        elif member.islnk():
            unsafe = unsafe or not (target / member.linkname).resolve().is_relative_to(root)
        if unsafe:
            raise EngineError(f"The engine download contains an unsafe path ({member.name}); it wasn't unpacked.")
        member.mode &= 0o755  # no setuid/setgid bits, nothing writable by others
        bundle.extract(member, target)


def _extract_zst(archive: Path, target: Path) -> None:
    """Ollama's Linux downloads are zstd-compressed tarballs. Python 3.14 reads them itself; before that,
    the ``zstandard`` package (installed with Cicero on Linux) or the system's ``tar`` does."""
    try:
        from compression import zstd  # Python 3.14+
    except ImportError:
        zstd = None
    if zstd is not None:
        with zstd.open(archive, "rb") as stream, tarfile.open(fileobj=stream, mode="r|") as bundle:
            _extract_tar(bundle, target)
        return
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard is not None:
        with open(archive, "rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as stream, \
                tarfile.open(fileobj=stream, mode="r|") as bundle:
            _extract_tar(bundle, target)
        return
    tar = shutil.which("tar")
    if tar is None or subprocess.run([tar, "--zstd", "-xf", str(archive), "-C", str(target)],
                                     capture_output=True).returncode != 0:
        raise EngineError("Unpacking the engine needs zstd. Install it (Debian/Ubuntu: sudo apt install zstd, "
                          "Fedora: sudo dnf install zstd) and try again.")


def _start_in_own_thread(args: list[str], **options) -> subprocess.Popen:
    """Start a process from a thread of its own, which lives exactly as long as the process does.

    On Linux the server is told to stop when its parent dies (``_die_with_parent``), and for the
    kernel the parent is the *thread* that started it, not Cicero as a whole. Started from the
    window's Connect or Download thread, the server was stopped as soon as that thread finished,
    and the next request found nothing listening.
    """
    started: queue.Queue[subprocess.Popen | OSError] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            process = subprocess.Popen(args, **options)
        except OSError as exc:
            started.put(exc)
            return
        started.put(process)
        process.wait()

    threading.Thread(target=run, name="ollama-server", daemon=True).start()
    result = started.get()
    if isinstance(result, OSError):
        raise result
    return result


def _die_with_parent() -> None:
    """Linux: ask the kernel to stop the server if Cicero ends, even by a crash (runs in the child)."""
    try:
        import ctypes
        import signal

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass


def _kill_with_parent(process: subprocess.Popen):
    """On Windows, put the server in a job object that is closed (killing it) when Cicero exits, even by a crash."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE

        class _BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes",
                                                             "WriteBytes", "OtherBytes")]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = kernel32.CreateJobObjectW(None, None)
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))  # extended limits
        handle = kernel32.OpenProcess(0x0001 | 0x0100, False, process.pid)  # PROCESS_TERMINATE | SET_QUOTA
        kernel32.AssignProcessToJobObject(job, handle)
        kernel32.CloseHandle(handle)
        return job  # keep the handle open: closing it (at exit) ends the server
    except (OSError, AttributeError):
        log.warning("Couldn't tie the model server to Cicero's lifetime", exc_info=True)
        return None
