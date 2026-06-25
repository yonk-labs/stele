"""File watcher with CodeGraph's policy (design ported under MIT; see NOTICE).

Wraps ``watchfiles`` (Rust/notify: cross-platform recursive watching + debounce)
and adds the hard-won policy from CodeGraph's ``watcher.ts``: ignore scoping, a
WSL2-disable guard (recursive watch is too slow on drvfs ``/mnt``), and graceful
refusal so callers can fall back to git hooks. Change detection and hashing live
in :class:`FileManifest`; this module only turns OS events into ignore-filtered
paths and hands them to a callback.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Callable, Iterable
from pathlib import Path

from stele.codeintel.manifest import default_ignore


class WatchUnavailable(RuntimeError):
    """Live watching is not available here; the caller should fall back (e.g. git hooks)."""


def is_wsl() -> bool:
    if os.environ.get("STELE_FORCE_WATCH"):
        return False
    release = platform.uname().release.lower()
    return "microsoft" in release or "wsl" in release


def watching_disabled(root: str | Path) -> str | None:
    """Return a reason string if live watching should be skipped here, else None."""
    if os.environ.get("STELE_NO_WATCH"):
        return "STELE_NO_WATCH is set"
    if is_wsl() and str(root).startswith("/mnt/"):
        return "WSL2 /mnt (drvfs): recursive watch is too slow; use git hooks"
    return None


def watch(
    root: str | Path,
    on_change: Callable[[set[str]], None],
    *,
    ignore: Callable[[Path], bool] | None = None,
    debounce_ms: int = 2000,
    _source: Iterable[set[str]] | None = None,
) -> None:
    """Block, calling ``on_change(paths)`` for each debounced batch of changed files.

    Raises :class:`WatchUnavailable` if watching is disabled for ``root``.
    ``_source`` is a test seam (an iterable of path-sets); production uses
    ``watchfiles``.
    """
    reason = watching_disabled(root)
    if reason:
        raise WatchUnavailable(reason)
    ignore = ignore or default_ignore
    source = _source if _source is not None else _watchfiles_source(root, debounce_ms)
    for batch in source:
        changed = {p for p in batch if not ignore(Path(p))}
        if changed:
            on_change(changed)


def _watchfiles_source(root: str | Path, debounce_ms: int) -> Iterable[set[str]]:
    # ponytail: thin adapter over watchfiles; the testable logic lives in watch()
    # and FileManifest, so this loop is exercised manually, not in unit tests.
    from watchfiles import watch as _wf_watch

    for events in _wf_watch(str(root), debounce=debounce_ms):
        yield {path for _change, path in events}
