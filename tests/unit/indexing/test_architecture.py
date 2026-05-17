"""Architecture import-layer guards (codifies DC-001 + DC-002).

chunkshop must live only in indexing/ + storage/chunk_store/.
Concurrency primitives must live only in indexing/task_backend/.
Neither may leak into retrieval/ or recall/.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[3]
_GUARDED = ["src/stele/retrieval", "src/stele/recall"]

_CHUNKSHOP = re.compile(r"^\s*(?:import\s+chunkshop|from\s+chunkshop[\s.])", re.M)
_CONCURRENCY = re.compile(
    r"^\s*(?:import\s+(?:threading|asyncio|queue)\b"
    r"|from\s+(?:threading|asyncio|queue)\s+import)"
    r"|queue\.Queue|asyncio\.|threading\.",
    re.M,
)


def _py_files() -> list[Path]:
    files: list[Path] = []
    for rel in _GUARDED:
        files.extend((_ROOT / rel).rglob("*.py"))
    assert files, "no source files found — path resolution broke"
    return files


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: str(p.relative_to(_ROOT)))
def test_no_chunkshop_in_retrieval_or_recall(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert not _CHUNKSHOP.search(src), f"DC-001 violation: chunkshop imported in {path}"


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: str(p.relative_to(_ROOT)))
def test_no_concurrency_in_retrieval_or_recall(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert not _CONCURRENCY.search(src), f"DC-002 violation: concurrency primitive in {path}"
