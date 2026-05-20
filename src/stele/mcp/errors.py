"""MCP error model and handler guard decorator.

All MCP tool handlers wrap through `guard` so exceptions become structured
JSON error responses with stable codes. Unmapped exceptions log their
traceback to stderr and surface as `INTERNAL`.
"""

from __future__ import annotations

import functools
import sys
import traceback
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from stele.core.exceptions import (
    CapabilityError,
    ConfigError,
    PIIBlockedError,
    ValidationError,
)


class McpError(BaseModel):
    code: str
    message: str
    context: dict[str, Any] = {}


_CODE_MAP: dict[type[Exception], str] = {
    ConfigError: "CONFIG",
    PIIBlockedError: "PII_BLOCKED",
    CapabilityError: "CAPABILITY",
    ValidationError: "VALIDATION",
}


def exception_to_error(exc: Exception) -> McpError:
    for exc_type, code in _CODE_MAP.items():
        if isinstance(exc, exc_type):
            return McpError(code=code, message=str(exc))
    return McpError(code="INTERNAL", message=str(exc) or exc.__class__.__name__)


def guard(handler: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(handler)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return handler(*args, **kwargs)
        except Exception as exc:
            err = exception_to_error(exc)
            if err.code == "INTERNAL":
                traceback.print_exception(exc, file=sys.stderr)
            return {"error": err.model_dump()}

    return wrapped
