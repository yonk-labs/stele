"""Unit tests for lossless JSON minification in the summary-prep path."""

from __future__ import annotations

import json

from stele.summary.compact import compact_json, compact_or_digest


def test_minifies_pretty_json_losslessly() -> None:
    pretty = json.dumps({"b": 2, "a": [1, 2, 3], "nested": {"x": True}}, indent=4)
    out = compact_json(pretty)
    assert len(out) < len(pretty)  # whitespace stripped
    assert json.loads(out) == json.loads(pretty)  # data preserved exactly
    assert " " not in out.replace(": ", "")  # no structural whitespace left


def test_passes_through_prose_unchanged() -> None:
    prose = "This is a normal sentence, not JSON at all."
    assert compact_json(prose) == prose


def test_passes_through_malformed_json_unchanged() -> None:
    broken = '{"a": 1, "b":'  # truncated
    assert compact_json(broken) == broken


def test_leaves_top_level_scalars_alone() -> None:
    # A bare quoted string parses as JSON but is not a payload worth touching.
    assert compact_json('"hello"') == '"hello"'
    assert compact_json("123") == "123"


def test_minifies_top_level_array() -> None:
    pretty = json.dumps([{"id": 1}, {"id": 2}], indent=2)
    out = compact_json(pretty)
    assert out == '[{"id":1},{"id":2}]'


# --- tier 2: compact_or_digest (minified-if-fits, else bounded structural digest) ---


def test_or_digest_returns_minified_when_it_fits() -> None:
    pretty = json.dumps({"a": 1, "b": [1, 2, 3]}, indent=4)
    out = compact_or_digest(pretty, max_chars=1200)
    assert out == '{"a":1,"b":[1,2,3]}'
    assert json.loads(out) == json.loads(pretty)  # lossless when it fits


def test_or_digest_returns_none_for_non_json() -> None:
    assert compact_or_digest("just a sentence", max_chars=1200) is None
    assert compact_or_digest("123", max_chars=1200) is None  # scalar, not a container
    assert compact_or_digest('"hi"', max_chars=1200) is None
    assert compact_or_digest('{"a":', max_chars=1200) is None  # malformed


def test_or_digest_bounded_structural_digest_for_oversized_object() -> None:
    big = {"items": [{"id": i, "name": f"name-{i}"} for i in range(1000)], "total": 1000}
    out = compact_or_digest(json.dumps(big), max_chars=300)
    assert out is not None
    assert len(out) <= 300  # bounded
    assert "JSON object" in out
    assert "items: array[1000]" in out  # array length surfaced, not 1000 rows
    assert "total: int" in out
    assert "stele://" in out  # fetch-for-truth marker survives


def test_or_digest_array_top_level() -> None:
    arr = [{"id": i, "name": "x" * 50} for i in range(500)]
    out = compact_or_digest(json.dumps(arr), max_chars=200)
    assert out is not None
    assert len(out) <= 200
    assert "JSON array, 500 elements" in out
    assert "element keys: id, name" in out


def test_or_digest_caps_key_listing() -> None:
    obj = {f"k{i}": i for i in range(200)}
    out = compact_or_digest(json.dumps(obj), max_chars=600)
    assert out is not None
    assert len(out) <= 600
    assert "more keys)" in out  # capped, not all 200 listed
