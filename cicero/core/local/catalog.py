"""The open-weight models Cicero offers, chosen to run on a graphics card with 8 or 16 GB of memory.

Adding a model is one entry here: its Ollama name (from the Ollama library, or
``hf.co/<user>/<repo>:<quant>`` for a GGUF on Hugging Face), how it wants to be
prompted, and the languages it knows.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from cicero.core.local import languages


class PromptStyle(enum.Enum):
    """How a model was trained to be asked for a translation (see prompts.py)."""

    TRANSLATEGEMMA = "translategemma"  # Google's fixed translator prompt, one segment, no context
    HY_MT = "hy-mt"  # Tencent's prompts, with background context and terminology
    GENERAL = "general"  # an instruction-following model: reads the whole document first, keeps a glossary


@dataclass(frozen=True, slots=True)
class LocalModel:
    key: str  # stable identifier stored in the settings
    name: str
    maker: str
    ollama_name: str
    download_gb: float
    gpu_gb: int  # graphics memory it runs well in (it still runs with less, more slowly)
    style: PromptStyle
    language_codes: list[str]
    license: str
    summary: str
    homepage: str
    options: dict = field(default_factory=dict)  # Ollama sampling options, as the model card recommends
    context_tokens: int = 4096

    @property
    def needs_source_language(self) -> bool:
        """TranslateGemma's prompt names the source language, so it must be known or detected."""
        return self.style is PromptStyle.TRANSLATEGEMMA

    @property
    def reads_whole_document(self) -> bool:
        return self.style is PromptStyle.GENERAL

    def label(self) -> str:
        return f"{self.name} · {self.download_gb:.1f} GB · {self.gpu_gb} GB GPU"


CATALOG: list[LocalModel] = [
    LocalModel(
        key="translategemma-4b",
        name="TranslateGemma 4B",
        maker="Google",
        ollama_name="translategemma:4b",
        download_gb=3.3,
        gpu_gb=8,
        style=PromptStyle.TRANSLATEGEMMA,
        language_codes=languages.TRANSLATEGEMMA,
        license="Gemma Terms of Use",
        summary="Fast, made only for translation. 55 languages.",
        homepage="https://ollama.com/library/translategemma",
        options={"temperature": 0},  # the model card decodes greedily
        context_tokens=2048,
    ),
    LocalModel(
        key="hy-mt2-7b",
        name="Hy-MT2 7B",
        maker="Tencent",
        ollama_name="hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
        download_gb=4.6,
        gpu_gb=8,
        style=PromptStyle.HY_MT,
        language_codes=languages.HY_MT2,
        license="Apache 2.0",
        summary="Made for translation; uses the surrounding text as context. 38 languages.",
        homepage="https://huggingface.co/tencent/Hy-MT2-7B",
        options={"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05},
    ),
    LocalModel(
        key="qwen3.5-9b",
        name="Qwen 3.5 9B",
        maker="Alibaba",
        ollama_name="qwen3.5:9b",
        download_gb=6.6,
        gpu_gb=8,  # 5.6 GB in memory: the download includes an image encoder that translation doesn't load
        style=PromptStyle.GENERAL,
        language_codes=languages.GENERAL,
        license="Apache 2.0",
        summary="General model: reads the whole document first and keeps a glossary. 200+ languages.",
        homepage="https://ollama.com/library/qwen3.5",
        options={"temperature": 0.2, "top_p": 0.9},
        context_tokens=8192,
    ),
    LocalModel(
        key="translategemma-12b",
        name="TranslateGemma 12B",
        maker="Google",
        ollama_name="translategemma:12b",
        download_gb=8.1,
        gpu_gb=16,
        style=PromptStyle.TRANSLATEGEMMA,
        language_codes=languages.TRANSLATEGEMMA,
        license="Gemma Terms of Use",
        summary="The best quality of these models, made only for translation. 55 languages.",
        homepage="https://ollama.com/library/translategemma",
        options={"temperature": 0},
        context_tokens=2048,
    ),
]

BY_KEY = {model.key: model for model in CATALOG}
DEFAULT_KEY = "translategemma-4b"


def get(key: str | None) -> LocalModel:
    return BY_KEY.get(key or "", BY_KEY[DEFAULT_KEY])
