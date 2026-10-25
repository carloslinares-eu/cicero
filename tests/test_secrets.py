from __future__ import annotations

import sys
from types import SimpleNamespace

from cicero.core import secrets


def test_key_round_trip_through_the_credential_store(monkeypatch):
    store = {}
    fake = SimpleNamespace(
        get_password=lambda service, account: store.get((service, account)),
        set_password=lambda service, account, value: store.__setitem__((service, account), value),
        delete_password=lambda service, account: store.pop((service, account)),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert secrets.load_deepl_key() == ""
    assert secrets.save_deepl_key("abc:fx")
    assert secrets.load_deepl_key() == "abc:fx"
    assert secrets.save_deepl_key("")  # forget it
    assert store == {}


def test_broken_store_is_not_fatal(monkeypatch):
    def fail(*_):
        raise RuntimeError("locked")

    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=fail, set_password=fail))
    assert secrets.load_deepl_key() == ""
    assert not secrets.save_deepl_key("abc")
