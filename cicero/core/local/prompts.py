"""The prompts each kind of model was trained on, and turning their answers back into Cicero's run HTML.

Cicero sends a paragraph as ``<span id="0">Hello </span><span id="1">bold</span>`` so
each translated piece goes back into the run (and formatting) it came from. Local
models are given the same thing in a shape small models keep more reliably:
``Hello <s1>bold</s1>``-style numbered tags, only when a paragraph has more than one
run. Most paragraphs have a single run and are sent as plain text.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field

from cicero.core.local.catalog import LocalModel, PromptStyle
from cicero.core.local.languages import CHINESE_CODES, CHINESE_NAMES, name_of

_SPAN = re.compile(r'<span id="(\d+)">|</span>|<span class="tab"></span>|<br>')
_MARKER = re.compile(r"</?s(\d+)>", re.IGNORECASE)
_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_PREAMBLE = re.compile(
    r"^\s*(?:here(?:'s| is) the translation|translation|translated text|译文|翻译)\s*[^\n:：]{0,40}[:：]\s*",
    re.IGNORECASE)
_FENCE = re.compile(r"^```[\w-]*\n(.*?)\n?```$", re.DOTALL)
_WRAPPER = re.compile(r"^\s*<target>(.*)</target>\s*$", re.DOTALL | re.IGNORECASE)


# -- run markers ----------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Marked:
    text: str  # what the model sees
    runs: int  # how many runs the paragraph has

    @property
    def tagged(self) -> bool:
        return self.runs > 1


def to_markers(source_html: str) -> Marked:
    """``<span id="0">a</span><span id="1">b</span>`` → ``<s1>a</s1><s2>b</s2>`` (or just ``a`` for one run)."""
    pieces: list[str] = []
    runs = current = position = 0
    for match in _SPAN.finditer(source_html):
        pieces.append(html.unescape(source_html[position:match.start()]))
        position = match.end()
        if match.group(1) is not None:
            runs += 1
            current = int(match.group(1)) + 1
            pieces.append(f"<s{current}>")
        elif match.group(0) == "</span>":
            pieces.append(f"</s{current}>")
        elif "tab" in match.group(0):
            pieces.append("\t")
        else:
            pieces.append("\n")
    pieces.append(html.unescape(source_html[position:]))
    text = "".join(pieces)
    if runs <= 1:
        text = _MARKER.sub("", text)
    return Marked(text, max(runs, 1))


def from_markers(answer: str, marked: Marked) -> str:
    """The model's answer → Cicero's span HTML, ready for ``blocks.apply``.

    Tags the model lost or invented are tolerated: ``segments.decode_runs`` gives text
    outside any span to the run before it, so no words are dropped.
    """
    def escape(text: str) -> str:
        return html.escape(text, quote=False).replace("\t", '<span class="tab"></span>').replace("\n", "<br>")

    if not marked.tagged:
        return f'<span id="0">{escape(_MARKER.sub("", answer))}</span>'
    parts: list[str] = []
    for token in re.split(r"(</?s\d+>)", answer, flags=re.IGNORECASE):
        match = _MARKER.fullmatch(token)
        if match is None:
            parts.append(escape(token))
            continue
        number = int(match.group(1))
        if not 1 <= number <= marked.runs:
            continue  # a tag the model made up
        parts.append("</span>" if token.startswith("</") else f'<span id="{number - 1}">')
    return "".join(parts)


def clean_answer(answer: str, source: str) -> str:
    """Remove what models add around a translation: reasoning, a "Translation:" label, quotes, code fences."""
    text = _THINKING.sub("", answer).strip()
    match = _FENCE.match(text)
    if match and not source.lstrip().startswith("```"):
        text = match.group(1).strip()
    match = _WRAPPER.match(text)
    if match:
        text = match.group(1).strip()
    if not _PREAMBLE.match(source):
        text = _PREAMBLE.sub("", text, count=1)
    for left, right in (('"', '"'), ("“", "”"), ("«", "»"), ("'", "'")):
        if text.startswith(left) and text.endswith(right) and len(text) > 1 \
                and not (source.strip().startswith(left) and source.strip().endswith(right)):
            text = text[1:-1].strip()
    return text


# -- what the model is told about the document ------------------------------------------

@dataclass(slots=True)
class Brief:
    """What a general model learned by reading the whole document before translating it."""

    summary: str = ""
    glossary: dict[str, str] = field(default_factory=dict)  # source term → agreed translation

    def terms_in(self, text: str, limit: int = 12) -> dict[str, str]:
        lowered = text.casefold()
        found = {term: target for term, target in self.glossary.items() if term.casefold() in lowered}
        return dict(list(found.items())[:limit])


@dataclass(frozen=True, slots=True)
class Context:
    """Text around a paragraph, shown to the model but not translated."""

    earlier: list[tuple[str, str]] = field(default_factory=list)  # (original, translation) on the same page
    brief: Brief | None = None


BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "glossary": {"type": "array", "items": {
            "type": "object",
            "properties": {"term": {"type": "string"}, "translation": {"type": "string"}},
            "required": ["term", "translation"],
        }},
    },
    "required": ["summary", "glossary"],
}


def brief_messages(document_text: str, target: str, source: str | None) -> list[dict]:
    source_name = name_of(source) if source else "its original language"
    return [{"role": "user", "content": (
        f"This document will be translated from {source_name} into {name_of(target)}. Read it and reply with "
        "JSON only, in this shape:\n"
        '{"summary": "two or three sentences: what the document is about, who it is for, its tone",\n'
        ' "glossary": [{"term": "a name, product, technical term or acronym from the document", '
        f'"translation": "how to write it in {name_of(target)} (the same if it stays as it is)"}}]}}\n'
        "List at most 25 terms: the ones whose translation must stay consistent across the document.\n\n"
        f"Document:\n{document_text}")}]


def parse_brief(answer: str) -> Brief:
    try:
        data = json.loads(clean_answer(answer, ""))
    except ValueError:
        return Brief()
    if not isinstance(data, dict):
        return Brief()
    glossary = {}
    for item in data.get("glossary") or []:
        if isinstance(item, dict):
            term, translation = str(item.get("term", "")).strip(), str(item.get("translation", "")).strip()
            if term and translation and len(term) <= 80:
                glossary[term] = translation
    return Brief(str(data.get("summary", "")).strip(), glossary)


# -- translation prompts --------------------------------------------------------------

def translation_messages(model: LocalModel, marked: Marked, target: str, source: str | None,
                         context: Context | None = None) -> list[dict]:
    """The chat messages that ask ``model`` to translate one paragraph."""
    if model.style is PromptStyle.TRANSLATEGEMMA:
        return [{"role": "user", "content": _translategemma(marked, target, source)}]
    if model.style is PromptStyle.HY_MT:
        return [{"role": "user", "content": _hy_mt(marked, target, source, context)}]
    return _general(marked, target, source, context)


def _translategemma(marked: Marked, target: str, source: str | None) -> str:
    # Google's prompt, word for word: the model was trained on exactly this.
    source = source or "en"
    s_name, t_name = name_of(source), name_of(target)
    prompt = (f"You are a professional {s_name} ({source}) to {t_name} ({target}) translator. Your goal is to "
              f"accurately convey the meaning and nuances of the original {s_name} text while adhering to {t_name} "
              f"grammar, vocabulary, and cultural sensitivities.\n"
              f"Produce only the {t_name} translation, without any additional explanations or commentary.")
    if marked.tagged:
        prompt += " Keep the <s1>…</s1>-style tags around the corresponding words."
    return f"{prompt} Please translate the following {s_name} text into {t_name}:\n\n\n{marked.text}"


def _hy_mt(marked: Marked, target: str, source: str | None, context: Context | None) -> str:
    chinese = target in CHINESE_CODES or (source in CHINESE_CODES)
    t_name = CHINESE_NAMES.get(target, name_of(target)) if chinese else name_of(target)
    glossary = context.brief.terms_in(marked.text) if context and context.brief else {}
    background = "\n".join(original for original, _ in context.earlier) if context else ""

    lines: list[str] = []
    if glossary:
        lines.append("参考下面的翻译：" if chinese else "Reference the following translations:")
        lines += [f"{term} 翻译成 {translation}" if chinese else f"{term} translates to {translation}"
                  for term, translation in glossary.items()]
        lines.append("")
    if background:
        if chinese:
            instruction = f"参考上面的信息，把下面的文本翻译成{t_name}，注意不需要翻译上文，也不要额外解释："
            if marked.tagged:
                instruction += "原文中的<s1></s1>等标签需要在译文中相应的位置保留。"
            lines += [background, instruction]
        else:
            instruction = (f"Please translate the following text into {t_name}, taking the provided background "
                           "information into consideration. Only output the translated result without any "
                           "additional explanation.")
            if marked.tagged:
                instruction += " Keep the <s1>…</s1>-style tags around the corresponding words."
            lines += ["[Background Information]", background, "", instruction, "", "[Source Text]"]
        return "\n".join(lines + [marked.text])
    if marked.tagged and not chinese:
        lines += [f"Please accurately translate the following text into {t_name}.",
                  "You must retain the exact same number of tags in the translation. Strictly do not omit, escape, or "
                  "translate these tags, and pay close attention to their placement.", "", marked.text]
        return "\n".join(lines)
    if chinese:
        instruction = f"将以下文本翻译为{t_name}，注意只需要输出翻译后的结果，不要额外解释："
        if marked.tagged:
            instruction += "原文中的<s1></s1>等标签需要在译文中相应的位置保留。"
        return "\n".join(lines + [instruction, "", marked.text])
    return "\n".join(lines + [f"Translate the following text into {t_name}.",
                              "Note that you should only output the translated result without any additional "
                              "explanation:", "", marked.text])


def _general(marked: Marked, target: str, source: str | None, context: Context | None) -> list[dict]:
    t_name = name_of(target)
    from_text = f"from {name_of(source)} " if source else ""
    rules = [
        f"You are a professional translator. Translate the user's text {from_text}into {t_name}.",
        "Output only the translation: no notes, no explanations, no quotation marks around it.",
        "Keep numbers, URLs, e-mail addresses and code exactly as they are.",
        "Keep line breaks where they are.",
    ]
    if marked.tagged:
        rules.append("The text contains tags such as <s1>…</s1>. Keep every tag, exactly once, around the words "
                     "that correspond to the tagged words. Don't add or remove tags.")
    system = "\n".join(f"- {rule}" if index else rule for index, rule in enumerate(rules))
    if context and context.brief and context.brief.summary:
        system += f"\n\nAbout the document: {context.brief.summary}"
    glossary = context.brief.terms_in(marked.text) if context and context.brief else {}
    if glossary:
        system += "\n\nUse these translations for consistency:\n" + "\n".join(
            f"- {term} → {translation}" for term, translation in glossary.items())
    if context and context.earlier:
        system += "\n\nEarlier on the same page, already translated (for reference only, don't repeat it):\n" + \
            "\n".join(f"- {original} → {translation}" for original, translation in context.earlier)
    return [{"role": "system", "content": system}, {"role": "user", "content": marked.text}]
