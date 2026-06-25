"""Live file-watcher integration test (codeintel).

The unit tests mock the watch loop; this exercises the real ``watchfiles`` loop
against the filesystem and a clean ``stop_event`` shutdown. Skipped when the
``codeintel`` extra (watchfiles) is not installed.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("watchfiles")

from stele.codeintel import watch  # noqa: E402


def test_live_watcher_detects_real_edit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "j.js").write_text("noise\n")

    events: list[set[str]] = []
    stop = threading.Event()
    thread = threading.Thread(
        target=lambda: watch(tmp_path, events.append, debounce_ms=100, stop_event=stop),
        daemon=True,
    )
    thread.start()
    time.sleep(1.0)  # let watchfiles establish the OS-level watch

    (tmp_path / "a.py").write_text("x = 2\n")  # real edit
    (tmp_path / "b.py").write_text("y = 9\n")  # real add
    (tmp_path / "node_modules" / "j.js").write_text("more\n")  # must be ignored

    deadline = time.time() + 10
    while time.time() < deadline and not events:
        time.sleep(0.1)

    stop.set()  # clean shutdown — no abort at teardown
    thread.join(timeout=5)

    changed = set().union(*events) if events else set()
    assert str(tmp_path / "a.py") in changed
    assert str(tmp_path / "b.py") in changed
    assert all("node_modules" not in p for p in changed)
    assert not thread.is_alive()  # stop_event broke the loop cleanly
