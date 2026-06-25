"""Stele.read_bounded — the facade verb that routes a read through codeview."""

from __future__ import annotations

import warnings

from stele.core.config import StashConfig
from stele.core.stash import Stele

SRC = "def helper(n):\n    return n + 1\n\n\ndef main(x):\n    return helper(x)\n"


def _stele() -> Stele:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Stele(StashConfig())


def test_read_bounded_from_raw_source() -> None:
    out = _stele().read_bounded(SRC, want="main")
    assert "def main(x):" in out  # requested symbol
    assert "def helper(n):" in out  # dependency resolved
    assert "expand" in out.lower()  # agency handle


def test_read_bounded_from_ref() -> None:
    s = _stele()
    stored = s.store(SRC, namespace="t")
    out = s.read_bounded(stored.reference, want="main")
    assert "def main(x):" in out
    assert "def helper(n):" in out


def test_read_bounded_from_path_infers_language(tmp_path) -> None:
    p = tmp_path / "mod.py"
    p.write_text(SRC)
    out = _stele().read_bounded(str(p), want="main")
    assert "def main(x):" in out


def test_read_bounded_line_range() -> None:
    out = _stele().read_bounded(SRC, want=(1, 2))
    assert "def helper(n):" in out


def test_read_bounded_staleness_banner(tmp_path) -> None:
    from stele.codeintel.manifest import FileManifest

    p = tmp_path / "mod.py"
    p.write_text(SRC)
    m = FileManifest()
    m.update(p)  # record current hash
    fresh = _stele().read_bounded(str(p), want="main", manifest=m)
    assert "stale" not in fresh.lower()
    p.write_text(SRC + "\n\ndef extra():\n    return 0\n")  # change on disk
    stale = _stele().read_bounded(str(p), want="main", manifest=m)
    assert "stale" in stale.lower()  # banner fires
