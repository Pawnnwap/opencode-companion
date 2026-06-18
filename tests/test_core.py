"""Unit tests for Core's pure parsing helpers (no opencode calls)."""

from companion.core import Core


def test_parse_targets_lists_ranges_all_and_dedup():
    assert Core._parse_targets("1,3", 5) == [1, 3]
    assert Core._parse_targets("1-3", 5) == [1, 2, 3]
    assert Core._parse_targets("all", 3) == [1, 2, 3]
    assert Core._parse_targets("*", 2) == [1, 2]
    assert Core._parse_targets("2 4", 5) == [2, 4]      # space-separated
    assert Core._parse_targets("2,2,2", 3) == [2]       # deduped, order preserved
    assert Core._parse_targets("9", 3) == []            # out of range dropped
    assert Core._parse_targets("", 3) == []


def test_parse_consolidation_extracts_embedded_json():
    out = Core._parse_consolidation('noise {"facts":["a","b"],"reflection":["x"]} tail')
    assert out == (["a", "b"], ["x"])


def test_parse_consolidation_accepts_reflections_alias_and_filters_blanks():
    assert Core._parse_consolidation('{"facts":["a"," "],"reflections":["y"]}') == (["a"], ["y"])


def test_parse_consolidation_rejects_invalid():
    assert Core._parse_consolidation("no json here") is None
    assert Core._parse_consolidation('{"facts":"notalist"}') is None
    assert Core._parse_consolidation("") is None


def test_short_truncates_with_ellipsis():
    from companion.core import _short
    assert _short("hello world", 5) == "hell…"
    assert _short("hi", 5) == "hi"
