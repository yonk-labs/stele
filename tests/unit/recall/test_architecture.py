"""Architectural import-layer checks for the recall package."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RECALL_ROOT = Path(__file__).resolve().parents[3] / "src" / "stele" / "recall"

FORBIDDEN_PREFIXES = (
    "pg_raggraph",
    "chunkshop",
    "openai",
    "anthropic",
    "lede",  # Phase 2's territory
)

FORBIDDEN_EXACT = {
    "stele.storage.memory_store.base",
    "stele.storage.memory_store.memory",
    "stele.storage.memory_store.sqlite",
    "stele.storage.memory_store.postgres",
    "stele.storage.memory_store.mariadb",
    "stele.storage.memory_store.clickhouse",
}


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


@pytest.mark.parametrize("module_path", sorted(RECALL_ROOT.rglob("*.py")))
def test_no_forbidden_imports(module_path: Path) -> None:
    imports = _imports(module_path)
    for imp in imports:
        for prefix in FORBIDDEN_PREFIXES:
            assert prefix not in imp, (
                f"{module_path} imports {imp!r} — Phase 4/5 or LLM client drift"
            )
    illegal = {m for m in imports if m in FORBIDDEN_EXACT}
    assert not illegal, (
        f"{module_path} imports {illegal} — must consume Memory facade only"
    )
