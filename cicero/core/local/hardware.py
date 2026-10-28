"""How much graphics memory this computer has, to tell the user which models will run well."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Gpu:
    name: str
    memory_gb: float


@lru_cache(maxsize=1)
def detect_gpu() -> Gpu | None:
    """The card with the most memory: NVIDIA via nvidia-smi, AMD on Linux via /sys; None if unknown.

    Other cards (Intel, Apple, AMD on Windows) still work through Ollama; Cicero just can't say in
    advance how much memory they have.
    """
    command = shutil.which("nvidia-smi")
    if command is None:
        return max(_amd_cards(), key=lambda card: card.memory_gb, default=None)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
    try:
        output = subprocess.run([command, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10, creationflags=flags).stdout
    except (OSError, subprocess.SubprocessError):
        log.info("nvidia-smi didn't answer", exc_info=True)
        return None
    cards = []
    for line in output.splitlines():
        name, _, memory = line.rpartition(",")
        try:
            cards.append(Gpu(name.strip(), round(float(memory) / 1024, 1)))
        except ValueError:
            continue
    return max(cards, key=lambda card: card.memory_gb, default=None)


def has_amd_gpu() -> bool:
    """Whether an AMD graphics card is present (it needs Ollama's ROCm add-on)."""
    return _amd_cards() != [] or _windows_amd()


def _amd_cards(drm: Path = Path("/sys/class/drm")) -> list[Gpu]:
    """AMD cards on Linux, from the amdgpu driver's files in /sys (no tools needed)."""
    cards = []
    for device in sorted(drm.glob("card*/device")) if drm.is_dir() else []:
        try:
            if (device / "vendor").read_text().strip() != "0x1002":
                continue
            memory = int((device / "mem_info_vram_total").read_text())
        except (OSError, ValueError):
            continue
        cards.append(Gpu("AMD Radeon", round(memory / 1024**3, 1)))
    return cards


def _windows_amd() -> bool:
    if sys.platform != "win32":
        return False
    flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        output = subprocess.run(["powershell", "-NoProfile", "-Command",
                                 "(Get-CimInstance Win32_VideoController).Name"],
                                capture_output=True, text=True, timeout=15, creationflags=flags).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(word in output for word in ("AMD", "Radeon"))


def fit_note(gpu_gb: int, gpu: Gpu | None) -> str:
    """A short note on how a model needing ``gpu_gb`` will run here."""
    nbsp = "\u00a0"  # keeps "8 GB" on one line when the note wraps
    if gpu is None:
        return f"Runs best with {gpu_gb}{nbsp}GB of graphics memory"
    name = gpu.name.removeprefix("NVIDIA ").removeprefix("GeForce ")
    if gpu.memory_gb + 0.5 >= gpu_gb:
        return f"Fits your {name} ({gpu.memory_gb:g}{nbsp}GB)"
    return f"Larger than your {gpu.memory_gb:g}{nbsp}GB card: it will run, partly on the processor, more slowly"
