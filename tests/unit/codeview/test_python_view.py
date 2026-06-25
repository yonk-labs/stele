"""Slice 0 of bounded code reads: span + signature outline + expansion handles."""

from __future__ import annotations

from stele.codeview import bounded_python

SRC = '''import os


def alpha(x):
    return x + 1


def beta(y, z=2):
    return y * z


class Widget:
    def __init__(self, n):
        self.n = n

    def render(self) -> str:
        return "w" * self.n
'''


def test_symbol_span_included_verbatim() -> None:
    out = bounded_python(SRC, want="beta")
    assert "def beta(y, z=2):" in out
    assert "return y * z" in out


def test_other_symbols_are_signatures_not_bodies() -> None:
    out = bounded_python(SRC, want="beta")
    assert "def alpha(x)" in out  # signature present
    assert "return x + 1" not in out  # alpha's BODY excluded
    assert "class Widget" in out


def test_requested_symbol_not_duplicated_in_outline() -> None:
    out = bounded_python(SRC, want="beta")
    # beta appears once (in the span), not also as an outline signature line
    assert out.count("def beta") == 1


def test_line_range_span() -> None:
    out = bounded_python(SRC, want=(4, 5))  # alpha's def + body
    assert "def alpha(x):" in out
    assert "return x + 1" in out


def test_class_methods_outlined() -> None:
    out = bounded_python(SRC, want="alpha")
    assert "def render(self) -> str" in out  # method signature surfaces in outline


def test_expansion_handles_present() -> None:
    out = bounded_python(SRC, want="beta")
    low = out.lower()
    assert "expand" in low and "full file" in low


def test_unknown_symbol_falls_back_to_head() -> None:
    out = bounded_python(SRC, want="does_not_exist")
    assert out  # no exception
    assert "expand" in out.lower()


def test_malformed_source_does_not_raise() -> None:
    out = bounded_python("def broken(:\n    pass\n", want="broken")
    assert out  # returns a degraded view, never raises


def test_bounded_to_max_chars() -> None:
    big = "\n\n".join(f"def f{i}(a, b, c):\n    return a" for i in range(500))
    out = bounded_python(big, want="f0", max_chars=600)
    assert len(out) <= 600
