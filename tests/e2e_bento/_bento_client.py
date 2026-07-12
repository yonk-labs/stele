"""Thin JSON client for the 3RD-PARTY/E2E tier: bento-api (published :8000).

bento-api is bento's BFF and the one entry point that's actually published
to the host -- it is the real "third party" consuming stele. Stdlib
``urllib`` only, no new runtime dependency for a handful of JSON calls.
Shared by every test module under tests/e2e_bento/.

Auth: bento-api requires ``Authorization: Bearer <key>``. ``BENTO_ADMIN_API_KEY``
defaults to the project's own documented local-dev placeholder --
``backend/docker/docker-compose.yml``: ``ADMIN_API_KEY:
${ADMIN_API_KEY:-bento_admin_local_dev_only_change_me}`` -- NOT a secret read out
of the live container; override the env var if your stack sets a real key.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE_URL = os.environ.get("BENTO_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("BENTO_ADMIN_API_KEY", "bento_admin_local_dev_only_change_me")


class BentoApiUnavailable(RuntimeError):
    """bento-api isn't reachable, or the configured key doesn't authenticate --
    callers should skip rather than fail loud on infra that isn't up."""


def bento_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    auth: bool = True,
    timeout: float = 15.0,
) -> tuple[int, dict[str, Any]]:
    """Call bento-api; returns (status_code, parsed_json_body)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method=method.upper()
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"_raw": raw.decode(errors="replace")}
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BentoApiUnavailable(f"bento-api unreachable at {BASE_URL}: {exc}") from exc


def bento_api_available() -> bool:
    """True iff bento-api answers /health AND the configured key authenticates
    against a real route. Used as a module-level skip guard."""
    try:
        status, body = bento_request("GET", "/health", auth=False)
        if status != 200 or body.get("status") != "ok":
            return False
        status, _ = bento_request("GET", "/v1/me/kbs")
    except BentoApiUnavailable:
        return False
    return status == 200
