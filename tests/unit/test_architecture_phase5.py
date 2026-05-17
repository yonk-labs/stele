"""DC-P5-1: no pg_raggraph in retrieval/ or recall/.
DC-P5-2: no asyncio/threading in retrieval/ or recall/ (the async bridge
lives only in src/stele/revisor/).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "stele"
RECALL_ARCH = (
    Path(__file__).resolve().parents[1]
    / "unit"
    / "recall"
    / "test_architecture.py"
)
SCANNED = sorted((SRC / "retrieval").rglob("*.py")) + sorted(
    (SRC / "recall").rglob("*.py")
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", SCANNED)
def test_dc_p5_1_no_pg_raggraph(path: Path) -> None:
    assert not any("pg_raggraph" in i for i in _imports(path)), (
        f"{path} imports pg_raggraph — DC-P5-1 violated"
    )


@pytest.mark.parametrize("path", SCANNED)
def test_dc_p5_2_no_concurrency(path: Path) -> None:
    bad = {
        i
        for i in _imports(path)
        if i in {"asyncio", "threading"}
        or i.startswith(("asyncio.", "threading."))
    }
    assert not bad, f"{path} imports {bad} — DC-P5-2 (concurrency leak)"


def test_dc_p5_1_recall_arch_test_still_lists_pg_raggraph() -> None:
    src = RECALL_ARCH.read_text(encoding="utf-8")
    assert "FORBIDDEN_PREFIXES" in src
    assert '"pg_raggraph"' in src, (
        "the recall architecture test must keep pg_raggraph in "
        "FORBIDDEN_PREFIXES (DC-P5-1)"
    )
