from __future__ import annotations

from types import SimpleNamespace

import deepl
import pytest

from cicero.core.deepl_engine import DeepLTranslator
from cicero.core.errors import CredentialsError, TranslationError


class FakeDeepLClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.error = error

    def get_source_languages(self):
        return [SimpleNamespace(code="EN", name="English"), SimpleNamespace(code="de", name="German")]

    def get_target_languages(self):
        return [SimpleNamespace(code="EN-GB", name="English (British)"), SimpleNamespace(code="DE", name="German")]

    def translate_text(self, texts, **options):
        self.calls.append((texts, options))
        if self.error:
            raise self.error
        return [SimpleNamespace(text=f"T:{text}") for text in texts]

    def get_usage(self):
        return SimpleNamespace(character=SimpleNamespace(valid=True, count=1200, limit=500_000))


def test_translates_html_keeping_tags():
    client = FakeDeepLClient()
    translator = DeepLTranslator("abc:fx", client=client)
    assert translator.translate(['<span id="0">Hi</span>'], "DE") == ['T:<span id="0">Hi</span>']
    texts, options = client.calls[0]
    assert options["tag_handling"] == "html" and options["target_lang"] == "DE" and options["source_lang"] is None


def test_languages_merge_sources_and_regional_targets():
    languages = {language.code: language for language in DeepLTranslator("k", client=FakeDeepLClient()).languages()}
    assert languages["DE"].source and languages["DE"].target
    assert languages["EN"].source and not languages["EN"].target  # DeepL wants EN-GB or EN-US as a target
    assert languages["EN-GB"].target and not languages["EN-GB"].source


def test_description_shows_plan_and_usage():
    assert DeepLTranslator("abc:fx", client=FakeDeepLClient()).description == \
        "DeepL API Free · 1,200 of 500,000 characters used this period"
    assert DeepLTranslator("abc", client=FakeDeepLClient()).description.startswith("DeepL API Pro")


@pytest.mark.parametrize("error, message", [
    (deepl.AuthorizationException("bad key"), "rejected the authentication key"),
    (deepl.QuotaExceededException("quota"), "quota for this period is used up"),
    (deepl.ConnectionException("offline"), "Can't reach DeepL"),
])
def test_errors_are_explained(error, message):
    with pytest.raises(TranslationError, match=message):
        DeepLTranslator("k", client=FakeDeepLClient(error)).translate(["x"], "DE")


def test_empty_key_is_explained():
    with pytest.raises(CredentialsError, match="authentication key"):
        DeepLTranslator("  ")


def test_job_respects_deepl_request_size(sample_deck):
    from cicero.core.job import JobOptions, TranslationJob

    client = FakeDeepLClient()
    translator = DeepLTranslator("k", client=client)
    translator.max_segments = 4
    result = TranslationJob(translator, JobOptions(sample_deck, sample_deck.with_name("out.pptx"), "DE")).run()
    assert result.succeeded, result.error
    assert [len(texts) for texts, _ in client.calls] == [4, 4, 2]
