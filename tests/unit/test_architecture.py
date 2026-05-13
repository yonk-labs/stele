"""Layering checks — Memory facade does not import storage internals (SC-011)."""

import ast
from pathlib import Path

REPO = Path(__file__).parent.parent.parent


def _imports(file: Path) -> list[str]:
    tree = ast.parse(file.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
    return names


def test_memory_facade_does_not_import_storage_backends_directly() -> None:
    """The Memory facade should depend on MemoryStore protocol, not concrete stores.

    Concrete stores are imported lazily in Stele.memory property; the facade
    module itself only knows about the abstract protocol.
    """
    facade = REPO / "src/stele/core/memory.py"
    imports = _imports(facade)
    forbidden = [
        "stele.storage.memory_store.sqlite",
        "stele.storage.memory_store.postgres",
        "stele.storage.memory_store.mariadb",
        "stele.storage.memory_store.clickhouse",
        "stele.storage.sqlite",
        "stele.storage.postgres",
    ]
    for f in forbidden:
        assert f not in imports, f"Memory facade illegally imports {f}"


def test_memory_record_module_has_no_storage_imports() -> None:
    record = REPO / "src/stele/core/memory_record.py"
    imports = _imports(record)
    for name in imports:
        assert not name.startswith("stele.storage"), (
            f"memory_record.py imports storage module: {name}"
        )


def test_no_artifact_evolution_columns_added() -> None:
    """SC-011 + Evolution Boundary: artifact model is unchanged."""
    artifact = REPO / "src/stele/core/artifact.py"
    src = artifact.read_text()
    for forbidden in (
        "effective_from",
        "effective_until",
        "retracted",
        "supersedes",
    ):
        assert forbidden not in src, (
            f"artifact.py contains '{forbidden}' — Evolution Boundary violated"
        )
