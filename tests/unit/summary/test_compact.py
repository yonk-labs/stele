"""Unit tests for lossless JSON minification in the summary-prep path."""

from __future__ import annotations

import json

from stele.summary.compact import compact_json


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
