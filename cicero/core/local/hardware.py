"""How much graphics and main memory this computer has, to tell the user which models will run well."""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cicero.core.local.catalog import LocalModel

log = logging.getLogger(__name__)

RESERVED_GB = 2.5  # main memory the system, the desktop and Cicero need besides a model


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


@lru_cache(maxsize=1)
def system_memory_gb() -> float | None:
    """The computer's main memory (RAM) in GB, or None if it can't be told."""
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):  # MEMORYSTATUSEX
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *((name, ctypes.c_ulonglong) for name in ("total", "available", "total_page_file",
                                                                  "available_page_file", "total_virtual",
                                                                  "available_virtual", "available_extended"))]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return None
        return round(status.total / 1024**3, 1)
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except (ValueError, OSError, AttributeError):
        return None


def fit_note(model: LocalModel, gpu: Gpu | None, ram_gb: float | None) -> str:
    """A short note on how ``model`` will run here: on the graphics card, partly or only on the processor.

    What doesn't fit on the graphics card goes into main memory, next to the system and the
    desktop, so a model can be too large for a computer with little memory.
    """
    nbsp = "\u00a0"  # keeps "8 GB" on one line when the note wraps
    if gpu is not None and gpu.memory_gb + 0.5 >= model.gpu_gb:
        name = gpu.name.removeprefix("NVIDIA ").removeprefix("GeForce ")
        return f"Fits your {name} ({gpu.memory_gb:g}{nbsp}GB)"
    in_main_memory = model.memory_gb - (gpu.memory_gb if gpu else 0)
    if ram_gb is not None and ram_gb < in_main_memory + RESERVED_GB:
        return (f"Too large for this computer's {ram_gb:g}{nbsp}GB of memory: it needs about "
                f"{model.memory_gb:g}{nbsp}GB besides what the system uses")
    if gpu is None:
        return f"Runs best with {model.gpu_gb}{nbsp}GB of graphics memory, or slowly on the processor"
    return f"Larger than your {gpu.memory_gb:g}{nbsp}GB card: it will run, partly on the processor, more slowly"
