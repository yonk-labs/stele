"""Thin docker-exec HTTP client for the SERVICE tier (bento-stele-shim).

The shim is a FastAPI app on an internal port inside the `bento-stele-shim`
container -- it is NOT published to the host, so every call goes through
``docker exec bento-stele-shim curl ...``. Argv-list subprocess calls (no
``sh -c`` string interpolation) so request bodies never need shell quoting.

Shared by every test module under tests/service/ -- one docker-exec/JSON
wrapper, reused, instead of a fresh inline subprocess+json snippet per test.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

CONTAINER = "bento-stele-shim"
BASE_URL = "http://localhost:8000"


class ShimUnavailable(RuntimeError):
    """The shim container/docker CLI isn't reachable -- callers should skip."""


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def shim_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Call the shim's FastAPI via ``docker exec ... curl``; returns parsed JSON.

    Raises :class:`ShimUnavailable` for anything that means "can't reach the
    shim" (no docker CLI, container not running, non-JSON/empty response) so
    callers can skip cleanly instead of failing on an opaque subprocess error.
    """
    if not _docker_available():
        raise ShimUnavailable("docker CLI not found on PATH")
    cmd = [
        "docker", "exec", CONTAINER,
        "curl", "-s", "-X", method.upper(), f"{BASE_URL}{path}",
        "-H", "Content-Type: application/json",
    ]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise ShimUnavailable(f"docker exec failed: {exc}") from exc
    if proc.returncode != 0:
        raise ShimUnavailable(
            f"docker exec {CONTAINER} failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    text = proc.stdout.strip()
    if not text:
        raise ShimUnavailable(f"empty response from {CONTAINER}{path}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ShimUnavailable(f"non-JSON response from shim {path}: {text[:200]!r}") from exc


def shim_available() -> bool:
    """True iff the shim answers /health with status=ok. Used as a module-level
    skip guard so this suite degrades to 'skipped' (not 'error') when docker /
    the container isn't up -- e.g. on a laptop without the bento stack running."""
    try:
        health = shim_request("GET", "/health")
    except ShimUnavailable:
        return False
    return health.get("status") == "ok"
