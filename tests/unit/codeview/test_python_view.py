"""Slice 0 of bounded code reads: span + signature outline + expansion handles."""

from __future__ import annotations

from stele.codeview import bounded_python, bounded_view, budget_for_lines

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


# --- adaptive output budget (slice B) ---


def test_budget_for_lines_tiers() -> None:
    assert budget_for_lines(10) == 1200
    assert budget_for_lines(100) == 2000
    assert budget_for_lines(500) == 3500
    assert budget_for_lines(2000) == 6000
    assert budget_for_lines(10000) == 9000


def test_adaptive_budget_scales_with_file_size() -> None:
    tiny = "def a():\n    return 1\n"
    large = "\n".join(f"def f{i}(a, b, c):\n    return a" for i in range(2000))
    out_tiny = bounded_view(tiny, want="a", max_chars=None)
    out_large = bounded_view(large, want="f0", max_chars=None)
    assert len(out_tiny) <= 1200  # tiny tier
    assert len(out_large) <= 9000  # large tier cap
    assert len(out_large) > 1200  # big file earns a bigger view than the tiny tier


# --- staleness banner (slice C) ---


def test_stale_banner_prepended() -> None:
    out = bounded_view("def a():\n    return 1\n", want="a", stale=True)
    assert "stale" in out.lower()[:60]  # banner up top
    assert "def a():" in out  # content still present


def test_no_banner_when_fresh() -> None:
    out = bounded_view("def a():\n    return 1\n", want="a", stale=False)
    assert "stale" not in out.lower()


# --- slice 1: in-file dependency resolution ---

DEPS_SRC = '''import os

HELPER_CONST = 42


def _helper(n):
    return n * HELPER_CONST


def target(x):
    return _helper(x) + 1


def unrelated(y):
    return y - 1
'''


def test_referenced_def_pulled_in_with_body() -> None:
    out = bounded_python(DEPS_SRC, want="target")
    assert "def _helper(n):" in out
    assert "return n * HELPER_CONST" in out  # the BODY, not just a signature


def test_unreferenced_def_stays_signature_only() -> None:
    out = bounded_python(DEPS_SRC, want="target")
    assert "def unrelated(y)" in out  # signature in the outline
    assert "return y - 1" not in out  # body excluded (not referenced)


def test_referenced_module_constant_pulled_in() -> None:
    out = bounded_python(DEPS_SRC, want="_helper")
    assert "HELPER_CONST = 42" in out  # referenced module-level assignment resolved


def test_dependency_section_labeled() -> None:
    out = bounded_python(DEPS_SRC, want="target")
    assert "dependencies" in out.lower()


def test_dep_not_duplicated_in_outline() -> None:
    out = bounded_python(DEPS_SRC, want="target")
    assert out.count("def _helper") == 1  # shown as a dep, not also outlined
