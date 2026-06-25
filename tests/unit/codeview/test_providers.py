"""Slice 2: the resolver provider seam (stdlib for Python, codeparse for others)."""

from __future__ import annotations

import pytest

from stele.codeview import (
    CodeparseResolver,
    StdlibResolver,
    _select_resolver,
    bounded_view,
)

PY = "HELPER = 1\n\n\ndef a(x):\n    return a_dep(x)\n\n\ndef a_dep(y):\n    return y + HELPER\n"


def test_python_selects_stdlib() -> None:
    assert isinstance(_select_resolver("python"), StdlibResolver)


def test_stdlib_resolver_extracts_symbols_with_bodies() -> None:
    syms = {s.name: s for s in StdlibResolver().symbols(PY)}
    assert syms["a"].kind == "function"
    assert syms["a"].line_end > syms["a"].line_start  # full body span, not just the def line
    assert syms["HELPER"].kind == "assign"


def test_stdlib_resolver_finds_referenced_names() -> None:
    # span of `a` (lines 4-5) references a_dep
    refs = StdlibResolver().referenced(PY, (4, 5))
    assert "a_dep" in refs


def test_non_python_selects_codeparse() -> None:
    pytest.importorskip("chunkshop.codeparse")
    assert isinstance(_select_resolver("javascript"), CodeparseResolver)


def test_bounded_view_handles_javascript() -> None:
    pytest.importorskip("chunkshop.codeparse")
    js = "function a(x){ return b(x); }\nfunction b(y){ return y + 1; }\n"
    out = bounded_view(js, want="b", language="javascript")
    assert "function b" in out  # requested symbol present
    assert "expand" in out.lower()  # agency handle present


def test_unknown_language_falls_back_to_stdlib_without_crashing() -> None:
    # An unsupported language with Python-ish source still yields a view, no raise.
    out = bounded_view(PY, want="a", language="python")
    assert "def a(x):" in out
