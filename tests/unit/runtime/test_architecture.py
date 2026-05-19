"""Runtime SDK purity gate (recon §3.6/§3.7): deterministic, no LLM client,
no pg-raggraph, no network, no concurrency primitives in the core helpers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RT = Path(__file__).resolve().parents[3] / "src" / "stele" / "runtime"
FILES = sorted(RT.rglob("*.py"))
FORBIDDEN = ("pg_raggraph", "openai", "anthropic", "asyncio", "threading", "httpx")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_runtime_has_no_forbidden_imports(path: Path) -> None:
    imports = _imports(path)
    bad = {
        i for i in imports
        for f in FORBIDDEN
        if i == f or i.startswith(f + ".")
    }
    assert not bad, f"{path.name} imports {bad} — runtime SDK must stay pure"
