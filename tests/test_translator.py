from __future__ import annotations

from types import SimpleNamespace

import google.api_core.exceptions as api_exceptions
import pytest

from cicero.core.credentials import CloudAccount
from cicero.core.errors import TranslationError
from cicero.core.translator import GoogleTranslator, batches, describe_error


class FakeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.error = error

    def translate_text(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(translations=[SimpleNamespace(translated_text=f"T:{text}")
                                             for text in request["contents"]])

    def get_supported_languages(self, **request):
        self.calls.append(request)
        return SimpleNamespace(languages=[
            SimpleNamespace(language_code="es", display_name="Spanish", support_source=True, support_target=True),
            SimpleNamespace(language_code="af", display_name="Afrikaans", support_source=True, support_target=True),
        ])


def make_translator(client: FakeClient) -> GoogleTranslator:
    return GoogleTranslator(CloudAccount(credentials=None, project_id="my-project", source="test"), client=client)


def test_translate_sends_html_to_the_project():
    client = FakeClient()
    assert make_translator(client).translate(["<span>a</span>"], "es") == ["T:<span>a</span>"]
    call = client.calls[0]
    assert call["parent"] == "projects/my-project/locations/global"
    assert call["mime_type"] == "text/html"
    assert call["target_language_code"] == "es"
    assert call["source_language_code"] is None


def test_languages_are_sorted_by_name():
    languages = make_translator(FakeClient()).languages()
    assert [language.code for language in languages] == ["af", "es"]
    assert languages[1].label == "Spanish (es)"


def test_disabled_api_gives_an_actionable_message():
    error = api_exceptions.PermissionDenied("Cloud Translation API has not been used in project 123 ... SERVICE_DISABLED")
    with pytest.raises(TranslationError, match="isn't enabled"):
        make_translator(FakeClient(error)).translate(["x"], "es")


def test_unrelated_exceptions_are_not_hidden():
    assert describe_error(ZeroDivisionError(), "p") is None
    with pytest.raises(ZeroDivisionError):
        make_translator(FakeClient(ZeroDivisionError())).translate(["x"], "es")


def test_batches_respect_both_limits():
    assert list(batches(["a"] * 5, max_segments=2)) == [range(0, 2), range(2, 4), range(4, 5)]
    assert list(batches(["aaaa", "aaaa", "aa"], max_characters=8)) == [range(0, 2), range(2, 3)]
    assert list(batches(["a" * 50, "b"], max_characters=8)) == [range(0, 1), range(1, 2)]  # oversized alone
    assert list(batches([])) == []
