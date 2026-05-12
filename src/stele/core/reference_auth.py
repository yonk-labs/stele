"""HMAC signing for references."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from hashlib import sha256

from stele.core.config import SigningConfig
from stele.core.exceptions import SignatureError
from stele.core.reference import Reference, parse_reference


def sign_reference(
    reference: Reference,
    config: SigningConfig,
    *,
    expires_at: int | None = None,
) -> str:
    if not config.secret:
        raise SignatureError("Signing secret is required")
    params = dict(reference.params)
    if expires_at is not None:
        params["exp"] = str(expires_at)
    unsigned = Reference(
        scheme=reference.scheme,
        namespace=reference.namespace,
        artifact_id=reference.artifact_id,
        params={k: v for k, v in params.items() if k != "sig"},
    )
    params["sig"] = _signature(unsigned, config.secret)
    return Reference(
        scheme=reference.scheme,
        namespace=reference.namespace,
        artifact_id=reference.artifact_id,
        params=params,
    ).canonical


def validate_reference_signature(value: str, config: SigningConfig) -> Reference:
    reference = parse_reference(value)
    if config.mode == "disabled":
        return reference
    sig = reference.params.get("sig")
    if not sig:
        if config.mode == "required":
            raise SignatureError("Reference signature is required")
        return reference
    if not config.secret:
        raise SignatureError("Signing secret is required")
    exp = reference.params.get("exp")
    if exp is not None:
        try:
            exp_value = int(exp)
        except ValueError as exc:
            raise SignatureError("Reference signature expiration is invalid") from exc
        if datetime.now(UTC).timestamp() > exp_value:
            raise SignatureError("Reference signature is expired")
    unsigned = Reference(
        scheme=reference.scheme,
        namespace=reference.namespace,
        artifact_id=reference.artifact_id,
        params={k: v for k, v in reference.params.items() if k != "sig"},
    )
    expected = _signature(unsigned, config.secret)
    if not hmac.compare_digest(sig, expected):
        raise SignatureError("Reference signature is invalid")
    return reference


def _signature(reference: Reference, secret: str) -> str:
    msg = reference.canonical_without_params
    if reference.params:
        param_text = "&".join(f"{k}={reference.params[k]}" for k in sorted(reference.params))
        msg = f"{msg}?{param_text}"
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), sha256).hexdigest()
