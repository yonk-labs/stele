"""Shared literal types."""

from typing import Literal

ContentType = Literal[
    "text",
    "json",
    "table",
    "csv",
    "sql",
    "code",
    "code_diff",
    "log",
    "html",
    "markdown",
    "blob",
]

Lifecycle = Literal["session", "ttl", "manual"]
RetrievalMode = Literal["keyword", "vector", "hybrid", "graph"]
IndexStatus = Literal["queued", "indexed", "skipped", "failed"]
FailureMode = Literal["raise", "fail_open", "fail_closed"]
ContentEncoding = Literal["utf-8", "base64", "bytes"]

