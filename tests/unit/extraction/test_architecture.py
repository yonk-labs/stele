"""Architectural import-layer checks for the extraction package."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

EXTRACTION_ROOT = Path(__file__).resolve().parents[3] / "src" / "stele" / "extraction"

FORBIDDEN_MODULES = {
    "stele.storage.memory_store",
    "stele.storage.memory_store.base",
    "stele.storage.memory_store.memory",
    "stele.storage.memory_store.sqlite",
    "stele.storage.memory_store.postgres",
    "stele.storage.memory_store.mariadb",
    "stele.storage.memory_store.clickhouse",
}

FORBIDDEN_PREFIXES = (
    "pg_raggraph",
    "chunkshop",
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


@pytest.mark.parametrize("module_path", sorted(EXTRACTION_ROOT.rglob("*.py")))
def test_no_forbidden_imports(module_path: Path) -> None:
    imports = _imports(module_path)
    illegal = {m for m in imports if m in FORBIDDEN_MODULES}
    assert not illegal, f"{module_path} imports {illegal} — must consume Memory facade only"
    for imp in imports:
        for prefix in FORBIDDEN_PREFIXES:
            assert prefix not in imp, (
                f"{module_path} imports {imp!r} — Phase 4/5 drift detected"
            )
