from __future__ import annotations

import json

import pytest

from cicero.core.credentials import load_key_file
from cicero.core.errors import CredentialsError
from cicero.core.settings import Settings


@pytest.mark.parametrize("content, message", [
    ("not json", "isn't valid JSON"),
    (json.dumps({"installed": {"client_id": "x"}}), "OAuth client ID"),
    (json.dumps({"type": "authorized_user"}), "isn't a service account key"),
    (json.dumps({"type": "service_account", "client_email": "a@b"}), "incomplete or damaged"),
])
def test_bad_key_files_are_explained(tmp_path, content, message):
    path = tmp_path / "key.json"
    path.write_text(content)
    with pytest.raises(CredentialsError, match=message):
        load_key_file(path)


def test_missing_key_file(tmp_path):
    with pytest.raises(CredentialsError, match="not found"):
        load_key_file(tmp_path / "nope.json")


def test_settings_round_trip_and_ignore_junk(tmp_path):
    path = tmp_path / "settings.json"
    Settings(key_file="C:/keys/k.json", target_language="es", write_review=True).save(path)
    assert Settings.load(path) == Settings(key_file="C:/keys/k.json", target_language="es", write_review=True)

    path.write_text(json.dumps({"target_language": "fr", "unknown": 1}))
    assert Settings.load(path).target_language == "fr"
    path.write_text("{broken")
    assert Settings.load(path) == Settings()
