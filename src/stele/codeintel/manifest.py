"""Content-hash file manifest: what changed since the last index.

Design ported from CodeGraph (github.com/colbymchenry/codegraph, MIT; see NOTICE)
-- its SQLite ``files`` table (path, content_hash, mtime, indexed_at) that gates
re-indexing and powers staleness reporting. Reimplemented here in Python over
stdlib ``sqlite3`` (no new dependency). This is the change-detection brain that
the watcher and the (future) incremental indexer consume.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_IGNORE_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "dist", "build",
        "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox", ".idea",
    }
)


def default_ignore(path: Path) -> bool:
    """True if any path component is a conventionally-ignored directory."""
    return any(part in _DEFAULT_IGNORE_DIRS for part in path.parts)


@dataclass
class Changes:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    @property
    def touched(self) -> list[str]:
        """Files that exist and need (re)indexing: added + modified."""
        return self.added + self.modified


def _hash_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class FileManifest:
    """Records (path, content_hash, mtime, indexed_at); answers what changed."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS files ("
            "path TEXT PRIMARY KEY, content_hash TEXT NOT NULL, "
            "mtime REAL, indexed_at REAL)"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> FileManifest:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def recorded_hash(self, path: str | Path) -> str | None:
        row = self._conn.execute(
            "SELECT content_hash FROM files WHERE path = ?", (str(path),)
        ).fetchone()
        return str(row[0]) if row else None

    def is_stale(self, path: str | Path) -> bool:
        """True if the file on disk differs from the recorded hash (or is unrecorded)."""
        return _hash_file(Path(path)) != self.recorded_hash(path)

    def update(self, path: str | Path) -> None:
        p = Path(path)
        digest = _hash_file(p)
        if digest is None:
            return
        try:
            mtime: float | None = p.stat().st_mtime
        except OSError:
            mtime = None
        self._conn.execute(
            "INSERT INTO files (path, content_hash, mtime, indexed_at) VALUES (?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET content_hash=excluded.content_hash, "
            "mtime=excluded.mtime, indexed_at=excluded.indexed_at",
            (str(p), digest, mtime, time.time()),
        )
        self._conn.commit()

    def remove(self, path: str | Path) -> None:
        self._conn.execute("DELETE FROM files WHERE path = ?", (str(path),))
        self._conn.commit()

    def mark_indexed(self, changes: Changes) -> None:
        """Commit a scan's result: record touched files, forget deleted ones."""
        for p in changes.touched:
            self.update(p)
        for p in changes.deleted:
            self.remove(p)

    def scan(
        self, root: str | Path, *, ignore: Callable[[Path], bool] | None = None
    ) -> Changes:
        """Compare the file tree under ``root`` against the manifest."""
        root = Path(root)
        ignore = ignore or default_ignore
        on_disk = {str(p) for p in _walk(root, ignore)}
        changes = Changes()
        for path in sorted(on_disk):
            recorded = self.recorded_hash(path)
            if recorded is None:
                changes.added.append(path)
            elif _hash_file(Path(path)) != recorded:
                changes.modified.append(path)
        for path in self._recorded_under(root):
            if path not in on_disk:
                changes.deleted.append(path)
        return changes

    def _recorded_under(self, root: Path) -> list[str]:
        prefix = str(root)
        rows = self._conn.execute("SELECT path FROM files").fetchall()
        return [str(r[0]) for r in rows if r[0] == prefix or str(r[0]).startswith(prefix + os.sep)]


def _walk(root: Path, ignore: Callable[[Path], bool]) -> Iterable[Path]:
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        # prune ignored directories in place so we never descend into them
        dirnames[:] = [d for d in dirnames if not ignore(base / d)]
        for name in filenames:
            candidate = base / name
            if not ignore(candidate):
                yield candidate
