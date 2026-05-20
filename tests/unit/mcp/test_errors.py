from __future__ import annotations

import pytest

from stele.core.exceptions import (
    CapabilityError,
    ConfigError,
    PIIBlockedError,
    ValidationError,
)
from stele.mcp.errors import McpError, exception_to_error, guard


def test_known_exceptions_map_to_codes() -> None:
    assert exception_to_error(ConfigError("bad")).code == "CONFIG"
    assert exception_to_error(PIIBlockedError("blocked")).code == "PII_BLOCKED"
    assert exception_to_error(CapabilityError("missing")).code == "CAPABILITY"
    assert exception_to_error(ValidationError("invalid")).code == "VALIDATION"


def test_unknown_exception_maps_to_internal() -> None:
    err = exception_to_error(RuntimeError("boom"))
    assert err.code == "INTERNAL"
    assert "boom" in err.message


def test_mcperror_serializes_as_dict() -> None:
    err = McpError(code="CONFIG", message="bad", context={"path": "/tmp"})
    assert err.model_dump() == {
        "code": "CONFIG",
        "message": "bad",
        "context": {"path": "/tmp"},
    }


def test_guard_decorator_catches_and_wraps() -> None:
    @guard
    def handler(arg: str) -> str:
        raise ConfigError("nope")

    out = handler("x")
    assert out == {"error": {"code": "CONFIG", "message": "nope", "context": {}}}


def test_guard_passes_through_success() -> None:
    @guard
    def handler(arg: str) -> dict[str, str]:
        return {"ok": arg}

    assert handler("yes") == {"ok": "yes"}


def test_guard_logs_unmapped_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    @guard
    def handler() -> None:
        raise RuntimeError("unexpected")

    out = handler()
    assert out["error"]["code"] == "INTERNAL"
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "unexpected" in captured.err
