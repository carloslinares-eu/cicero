# Local models: architecture

Cicero can translate with an open-weight model running on the user's own computer,
as an alternative to Google Cloud Translation and DeepL. This document compares the
ways to do that, explains the choice, and describes the design.

## Goals

- **Invisible.** The user picks a model and clicks **Download**. Cicero fetches
  everything it needs, shows a green mark when the model is ready, and from then on
  the normal workflow applies: choose a file and a language, click **Translate**.
- **8 to 16 GB of graphics memory.** Speed matters less than quality.
- **Better than paragraph-by-paragraph.** Use the context of the whole document
  where the model was trained to use it.
- **The same pipeline.** Reading, run markers, deduplication, saving, the review
  spreadsheet and the progress bar stay exactly as they are for Google and DeepL.

## Options considered

|                              | A. Managed Ollama (chosen)                                                               | B. Managed llama.cpp server                                        | C. Inference inside Cicero                                                      |
|------------------------------|------------------------------------------------------------------------------------------|--------------------------------------------------------------------|---------------------------------------------------------------------------------|
| What Cicero downloads once   | Ollama's standalone build, 1.6 GB on Windows (includes CUDA)                             | `llama-server`: 25 MB (CPU, Vulkan) to ~590 MB (CUDA 13 + runtime) | Python wheels: llama-cpp-python with CUDA, or CTranslate2 + PyTorch-free models |
| Graphics cards               | NVIDIA, AMD (ROCm/Vulkan), Apple, CPU fallback; detected by Ollama                       | One build per backend: Cicero must pick the right one              | CUDA wheels only for some Python/CUDA combinations on Windows                   |
| Fitting 8 GB                 | Ollama estimates memory and splits layers between GPU and CPU by itself                  | Cicero must choose `-ngl` and context size                         | Same as B                                                                       |
| Model files                  | `ollama pull`: resumable, verified, shared store; any GGUF on Hugging Face via `hf.co/…` | Cicero downloads GGUFs from Hugging Face itself                    | Cicero downloads model files itself                                             |
| Chat templates               | From the model's manifest                                                                | From the GGUF (`--jinja`)                                          | Must be reimplemented                                                           |
| Process                      | `ollama serve` on a private port, hidden                                                 | `llama-server`, one process per model                              | In-process: a crash takes Cicero down                                           |
| PyInstaller exe              | Unchanged                                                                                | Unchanged                                                          | Gigabytes bigger                                                                |
| Reuses the user's own Ollama | Yes, and its models                                                                      | No                                                                 | No                                                                              |
| Maintenance                  | Pin one Ollama release                                                                   | Pin a build per backend; releases several times a day              | Track wheel availability                                                        |

**Option C** is ruled out by packaging alone. Also, the best open translation
models are now LLMs, while CTranslate2's classic NMT models (NLLB, MADLAD) are
weaker and NLLB is non-commercial.

**Option B** is the leanest download, but it moves GPU detection, memory fitting
and model downloads into Cicero, which is exactly the work Ollama already does well.

**Option A** costs one larger download, but Ollama publishes a standalone build
meant for embedding in applications, and it brings model management, GPU and memory
handling, and a stable HTTP API. The code is behind an `OllamaRuntime` and an
`OllamaClient`, so switching to option B later only replaces those two modules.

## Models

Chosen for quality, for running on 8–16 GB, and for licenses that allow use in the
EU. They are listed in `cicero/core/local/catalog.py`; adding one is one entry.

| Model                       | Ollama name                           | Download                  | GPU   | License            | Prompt style     |
|-----------------------------|---------------------------------------|---------------------------|-------|--------------------|------------------|
| TranslateGemma 4B (Google)  | `translategemma:4b`                   | 3.3 GB                    | 8 GB  | Gemma Terms of Use | `TRANSLATEGEMMA` |
| Hy-MT2 7B (Tencent)         | `hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M` | 4.6 GB                    | 8 GB  | Apache 2.0         | `HY_MT`          |
| Qwen 3.5 9B (Alibaba)       | `qwen3.5:9b`                          | 6.6 GB (5.6 GB in memory) | 8 GB  | Apache 2.0         | `GENERAL`        |
| TranslateGemma 12B (Google) | `translategemma:12b`                  | 8.1 GB                    | 16 GB | Gemma Terms of Use | `TRANSLATEGEMMA` |

Left out:

- **HY-MT1.5** (Tencent, 1.8B and 7B): its license states that it *does not apply in
  the European Union, the United Kingdom and South Korea*.
- **Tower+, Aya Expanse, NLLB**: non-commercial licenses.
- **Seed-X 7B**: no official quantized build at the time of writing.

## The runtime

`OllamaRuntime` (`cicero/core/local/runtime.py`) decides which Ollama server to use:

1. An Ollama the user already runs on `127.0.0.1:11434`: used as is, never stopped.
2. An `ollama` program on the PATH, or Cicero's own copy in
   `%LOCALAPPDATA%\Cicero\ollama\<version>` (macOS: `~/Library/Application Support`,
   Linux: `~/.local/share/cicero`): started with `ollama serve` on a free port of
   127.0.0.1, with no window. On Windows the process is put in a job object with
   *kill on close*, so it ends with Cicero even if Cicero crashes; Cicero also stops
   it when the window closes.

Installing downloads the pinned release (`OLLAMA_RELEASE`) from GitHub, resumes
interrupted downloads with HTTP `Range`, checks the archive against the release's
`sha256sum.txt`, unpacks it into a temporary folder and renames it into place, then
deletes the archive.

On Linux the release is a `.tar.zst` (`bin/ollama`, `lib/ollama/…`), unpacked
with `compression.zstd` (Python 3.14+), the `zstandard` package or the system's
`tar --zstd`; the server gets `PR_SET_PDEATHSIG` so the kernel stops it with Cicero.
With an AMD card, Ollama's ROCm add-on is downloaded too and unpacked over the main
archive. An Ollama installed with the official Linux script runs as a systemd service
with its models in `/usr/share/ollama`; `model_ready()` asks a running server rather
than reading the user's folder, so the green mark is right in that case too.

Models go to Ollama's usual store (`OLLAMA_MODELS`, or `~/.ollama/models`), so they
are shared with any Ollama the user runs. `model_on_disk()` reads the store's
manifests to show the green mark at start-up without starting the server.

## The translator

`LocalTranslator` implements the same `Translator` protocol as Google and DeepL,
with `max_segments = 1`: one paragraph per request, so the progress bar moves and
Stop takes effect after each paragraph. The job calls one extra, optional method
first, `prepare(segments, target, source)`, with every distinct paragraph in reading
order and the slide or page it is on.

### Context strategy

Each model gets the context it was trained to use:

|                                     | TranslateGemma                                          | Hy-MT2                                  | General (Qwen 3.5)                                                                      |
|-------------------------------------|---------------------------------------------------------|-----------------------------------------|-----------------------------------------------------------------------------------------|
| Source language                     | Given, or detected from the whole document (langdetect) | Not needed                              | Not needed                                                                              |
| Reads the whole document first      | No                                                      | No                                      | Yes: a brief and a glossary                                                             |
| Glossary                            | No                                                      | Tencent's terminology prompt            | In the system prompt                                                                    |
| Earlier paragraphs on the same page | No (2K-token prompt, single message)                    | Tencent's background-information prompt | Originals and their translations                                                        |
| Where the paragraph is              | No                                                      | No                                      | "the title of slide 2", "a table cell", "the speaker notes (written for the presenter)" |
| Sampling                            | Greedy, as in the model card                            | Tencent's recommended settings          | Low temperature, thinking off                                                           |

**The brief.** Before translating, a general model reads up to 16 000 characters
of the document and answers, through Ollama's structured output (a JSON schema), with
a two-to-three-sentence summary (topic, audience, tone) and up to 25 glossary terms
with the translation to keep using: names, products, technical terms, acronyms. Each
paragraph's request then carries the summary and only the glossary terms that occur
in that paragraph, which keeps prompts short for small models.

**Neighboring text.** Up to three earlier paragraphs of the same slide or page
(300 characters each) go with each request: the original for Hy-MT2, and original
plus translation for general models, which keeps terms and register consistent
within a slide.

### Run markers

Cicero's `<span id="N">` run markup is rewritten as `<sN>…</sN>` tags, which small
models keep more reliably, and only when a paragraph has more than one run (most
have one and are sent as plain text). The answer is mapped back to spans; tags the
model lost or invented are tolerated by `segments.decode_runs`, which never drops
words. TranslateGemma keeps the tags in practice, although it isn't trained for them;
Hy-MT2 gets Tencent's "retain the delimiters" prompt.

### Cleaning and retrying

Answers are cleaned of what models add: reasoning blocks, "Here is the
translation:", code fences, `<target>` wrappers, quotes the source didn't have. An
answer far longer than the source (an explanation, or a loop) is retried once
greedily and without context. An empty answer leaves the paragraph in the original
language and is reported at the end.

## Results on an RTX 3070 Ti (8 GB)

A three-slide business review (16 paragraphs, bold text in the middle of a
sentence, a table and speaker notes), English to Spanish:

| Model             | First load                                         | 16 paragraphs                           | In GPU memory     |
|-------------------|----------------------------------------------------|-----------------------------------------|-------------------|
| TranslateGemma 4B | 41 s (engine start and model load, the first time) | 30 s                                    | 2.9 GB, all of it |
| Hy-MT2 7B         | 20 s                                               | 18 s                                    | 5.3 GB, all of it |
| Qwen 3.5 9B       | 11 s                                               | 18–24 s, including reading the document | 5.6 GB, all of it |

In the window itself, with Hy-MT2 already downloaded: Cicero showed the green mark on
opening, started its engine and loaded the model by itself in 8 s, translated the
presentation in 4 s, and stopped the engine when the window closed.

All three kept the bold phrase bold and moved it to its place in the Spanish sentence.
The differences are the ones the context strategy is about:

- **TranslateGemma** (no context) translated the company name: "Northwind Analytics:
  Q3 Business Review" became `Análisis de Northwind: Resumen del tercer trimestre`.
- **Hy-MT2** (earlier paragraphs as background) kept the name, and wrote `Fráncfort` and `T3`.
- **Qwen 3.5** first wrote an accurate summary and an eight-term glossary (keep
  *Northwind Analytics* and *Insight Cloud*, *Frankfurt* → `Fráncfort`, *customer churn*
  → `tasa de abandono de clientes`), then followed it in every paragraph; the table
  header "Mitigation" matched the slide title's `medidas de mitigación`.

All three put the speaker note "Thank everyone for coming and mention that…" in the first
person, as if it were the presenter's script; telling Qwen the text is a speaker note
didn't change that. It is a defensible reading, so it was left alone.

A two-page German insurance invoice (a PDF: a form of labels and values, a table, an
address, a scanned letterhead), German to Bulgarian. Hy-MT2 has no Bulgarian.

| Model             | 54 paragraphs and cells                 |
|-------------------|-----------------------------------------|
| TranslateGemma 4B | 10 s                                    |
| Qwen 3.5 9B       | 36 s, including reading the document    |

Terse labels are where context matters most. Seen on its own, *Prämienrechnung*
(premium invoice) became `Фактура за награди` ("invoice for awards") with TranslateGemma,
*Versicherungsnehmer* (policyholder) became `Застраховател` ("insurer") and *Nettobetrag*
`Сума след данъци` ("amount after tax"). Qwen, with its summary and glossary, got most labels
right (`Нетна сума`, `Премия`, `Валута`, `Референция на мандата`), but still read the table
heading *Art* (type) as `Изкуство` ("art") and *Vers.St.* (insurance tax) as `Версия Ст.`.
For forms and invoices, prefer a model that reads the whole document, or DeepL.

### On the processor only

For computers without a usable graphics card, such as an old laptop with 8 GB of
memory: the same documents with the graphics card switched off for Ollama
(`num_gpu: 0`) and 4 threads of an Intel Core i7-10700K. An older laptop's processor is
slower still, perhaps two to four times.

| Model             | 16 slide paragraphs | 54 invoice cells (to Bulgarian) | In main memory |
|-------------------|---------------------|---------------------------------|----------------|
| TranslateGemma 4B | 60 s                | 108 s                           | 2.9 GB         |
| Qwen 3.5 4B       | 118 s               | 375 s, including reading it     | 3.4 GB         |

Qwen 3.5 4B was tried as a small model that reads the whole document first, and left
out. Its long prompts (summary, glossary, earlier paragraphs) are slow to read on a
processor. Its Spanish was about as good as TranslateGemma's, and it kept the company
name. But its Bulgarian had invented words (`Страхувател`, `Грувна сума`), and it
repeated TranslateGemma's worst mistake (*Art* as `Изкуство`). TranslateGemma 4B
remains the model for computers with 8 GB of memory, and the window now says when a
model is too large for the computer's main memory.

The same check on GitHub Actions' Debian 12 and Fedora containers (no graphics card):
Cicero downloads its own Ollama, TranslateGemma 4B, and translates the presentation on
the processor.

## Testing

- `tests/test_local.py` and the window tests use a fake Ollama server (`tests/fake_ollama.py`):
  prompts, the brief, context, retries, downloads with progress and cancel, the engine
  installer (resume, checksum, add-ons, `.tar.zst`), and the window's
  download → ✔ Ready → connected flow. No GPU or downloads needed.
- `scripts/check_local_model.py` runs the real thing on the computer it is started on:
  engine, model download, translation of a generated presentation, and checks.
- GitHub Actions runs the tests on Windows, Ubuntu, Debian 12 and Fedora
  (`tests.yml`), and `scripts/check_local_model.py` on Debian 12 and Fedora containers
  whenever the local-model code changes (`local-models-linux.yml`): Cicero's own
  Ollama, downloaded and started inside the container, translating on the processor.

## Possible next steps

- Let a general model write the brief for a specialist model too (two models, more memory).
- Batch very short paragraphs (table cells) into one request, numbered, to save time.
- Option B as a lighter runtime for AMD/Intel GPUs (Vulkan build, 25 MB).
- A "quality check" pass: back-translate a sample and flag paragraphs that drifted.
