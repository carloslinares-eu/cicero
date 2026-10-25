from __future__ import annotations

from cicero.core.segments import decode_runs, encode_runs, needs_translation, split_edges


def test_encode_wraps_and_escapes_each_run():
    assert encode_runs(["R&D", "<b>"]) == '<span id="0">R&amp;D</span><span id="1">&lt;b&gt;</span>'


def test_round_trip():
    texts = ["Hello", "bold", "world & co"]
    assert decode_runs(encode_runs(texts), 3) == texts


def test_tabs_survive():
    encoded = encode_runs(["Name:\t\tCarlos"])
    assert "\t" not in encoded
    assert decode_runs(encoded, 1) == ["Name:\t\tCarlos"]


def test_reordered_spans_go_back_to_their_runs():
    # Translators move words around; the span ids say where each piece belongs.
    assert decode_runs('<span id="1">rojo</span> <span id="0">coche</span>', 2) == ["coche", "rojo"]


def test_text_outside_spans_is_kept():
    assert decode_runs('Hola <span id="0">mundo</span> y más', 2) == ["Hola mundo y más", ""]
    assert decode_runs('<span id="0">uno</span> dos <span id="1">tres</span>', 2) == ["uno dos", "tres"]


def test_missing_span_gives_empty_run_and_unknown_ids_are_ignored():
    assert decode_runs('<span id="0">todo junto</span>', 2) == ["todo junto", ""]
    assert decode_runs('<span id="7">x</span>', 1) == ["x"]


def test_entities_are_decoded():
    assert decode_runs('<span id="0">l&#39;été &amp; co</span>', 1) == ["l'été & co"]


def test_split_edges():
    assert split_edges("  Hello world \n") == ("  ", "Hello world", " \n")
    assert split_edges("   ") == ("   ", "", "")


def test_needs_translation():
    assert needs_translation("Revenue 2024")
    assert needs_translation("日本語")
    assert not needs_translation("2024 – 42 %")
    assert not needs_translation("•")


def test_line_breaks_survive_and_source_newlines_are_whitespace():
    encoded = encode_runs(["Carlos\nMadrid"])
    assert encoded == '<span id="0">Carlos<br>Madrid</span>'
    assert decode_runs('<span id="0">Carlos <br> Madrid</span>', 1) == ["Carlos\nMadrid"]
    assert decode_runs('<span id="0">one\n  two</span>', 1) == ["one two"]
