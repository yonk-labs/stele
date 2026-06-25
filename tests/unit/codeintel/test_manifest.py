"""FileManifest: content-hash change detection (codeintel slice A)."""

from __future__ import annotations

from pathlib import Path

from stele.codeintel.manifest import Changes, FileManifest, default_ignore


def test_scan_detects_added(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    with FileManifest() as m:
        ch = m.scan(tmp_path)
        assert str(tmp_path / "a.py") in ch.added
        assert not ch.modified and not ch.deleted


def test_mark_indexed_then_clean(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    with FileManifest() as m:
        m.mark_indexed(m.scan(tmp_path))
        assert not m.scan(tmp_path)  # nothing changed since indexed


def test_scan_detects_modified(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    with FileManifest() as m:
        m.mark_indexed(m.scan(tmp_path))
        f.write_text("x = 2\n")
        assert str(f) in m.scan(tmp_path).modified


def test_scan_detects_deleted(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    with FileManifest() as m:
        m.mark_indexed(m.scan(tmp_path))
        f.unlink()
        assert str(f) in m.scan(tmp_path).deleted


def test_is_stale(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    with FileManifest() as m:
        assert m.is_stale(f)  # unrecorded
        m.update(f)
        assert not m.is_stale(f)
        f.write_text("x = 9\n")
        assert m.is_stale(f)  # content changed


def test_default_ignore() -> None:
    assert default_ignore(Path("/r/node_modules/x.js"))
    assert default_ignore(Path("/r/.git/config"))
    assert not default_ignore(Path("/r/src/a.py"))


def test_scan_prunes_ignored_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "b.js").write_text("b\n")
    with FileManifest() as m:
        ch = m.scan(tmp_path)
        assert str(tmp_path / "src" / "a.py") in ch.added
        assert all("node_modules" not in p for p in ch.added)


def test_changes_truthiness() -> None:
    assert not Changes()
    assert Changes(added=["x"])
    assert Changes(added=["a"], modified=["b"]).touched == ["a", "b"]
