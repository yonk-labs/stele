from __future__ import annotations

from pathlib import Path


def test_server_module_imports() -> None:
    from stele.mcp import server

    assert hasattr(server, "main")
    assert callable(server.main)


def test_build_stele_with_no_config_uses_memory_backend(
    tmp_path: Path, monkeypatch: object
) -> None:
    """When no config is found anywhere, fall back to in-memory."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        Path, "home", lambda: tmp_path / "empty-home"
    )

    from stele.mcp.server import _build_stele

    s = _build_stele()
    caps = s.capabilities()
    assert caps is not None
