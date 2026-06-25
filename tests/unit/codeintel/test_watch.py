"""Watcher policy + dispatch (codeintel slice A). The live loop is a test seam."""

from __future__ import annotations

import pytest

from stele.codeintel.watcher import (
    WatchUnavailable,
    is_wsl,
    watch,
    watching_disabled,
)


def test_watch_filters_ignored_and_dispatches() -> None:
    batches = [{"/r/src/a.py", "/r/node_modules/x.js"}, {"/r/src/b.py"}]
    seen: list[set[str]] = []
    watch("/r", seen.append, _source=batches)
    assert seen == [{"/r/src/a.py"}, {"/r/src/b.py"}]  # node_modules filtered out


def test_watch_skips_empty_batches() -> None:
    seen: list[set[str]] = []
    watch("/r", seen.append, _source=[{"/r/node_modules/only.js"}])
    assert seen == []  # batch fully ignored -> no callback


def test_watch_refuses_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STELE_NO_WATCH", "1")
    with pytest.raises(WatchUnavailable):
        watch("/r", lambda _p: None, _source=[])


def test_watching_disabled_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STELE_NO_WATCH", raising=False)
    monkeypatch.setattr("stele.codeintel.watcher.is_wsl", lambda: True)
    assert watching_disabled("/mnt/c/proj")  # drvfs -> disabled
    assert watching_disabled("/home/u/proj") is None  # native fs -> fine


def test_force_watch_overrides_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STELE_FORCE_WATCH", "1")
    assert is_wsl() is False
