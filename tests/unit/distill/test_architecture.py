from __future__ import annotations

import ast
from pathlib import Path

import pytest

DISTILL_ROOT = Path(__file__).resolve().parents[3] / "src" / "stele" / "distill"
FORBIDDEN_PREFIXES = ("openai", "anthropic", "pg_raggraph", "chunkshop")  # LLM is INJECTED
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
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("py", sorted(DISTILL_ROOT.glob("*.py")), ids=lambda p: p.name)
def test_distill_imports_only_public_facades(py: Path) -> None:
    for imp in _imports(py):
        assert imp not in FORBIDDEN_EXACT, f"{py.name} imports storage internal {imp}"
        forbidden = any(imp == p or imp.startswith(p + ".") for p in FORBIDDEN_PREFIXES)
        assert not forbidden, (
            f"{py.name} imports forbidden {imp}"
            " (LLM must be injected, storage stays behind facades)"
        )
