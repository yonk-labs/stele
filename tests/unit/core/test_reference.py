from datetime import UTC, datetime, timedelta

import pytest

from stele.core.config import SigningConfig
from stele.core.exceptions import ReferenceError, SignatureError
from stele.core.reference import make_reference, parse_reference
from stele.core.reference_auth import sign_reference, validate_reference_signature


def test_parse_stash_reference() -> None:
    ref = parse_reference("stele://default/abc")

    assert ref.scheme == "stele"
    assert ref.namespace == "default"
    assert ref.artifact_id == "abc"


def test_parse_nested_namespace() -> None:
    ref = parse_reference("stele://team/project/abc")

    assert ref.namespace == "team/project"
    assert ref.artifact_id == "abc"


def test_rejects_unknown_reference_scheme() -> None:
    with pytest.raises(ReferenceError):
        parse_reference("other://default/abc")


def test_signed_reference_validates() -> None:
    config = SigningConfig(mode="required", secret="secret")
    expires = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    signed = sign_reference(make_reference("default", "abc"), config, expires_at=expires)

    assert validate_reference_signature(signed, config).artifact_id == "abc"


def test_tampered_signature_rejected() -> None:
    config = SigningConfig(mode="required", secret="secret")
    signed = sign_reference(make_reference("default", "abc"), config)
    tampered = signed.replace("abc", "def")

    with pytest.raises(SignatureError):
        validate_reference_signature(tampered, config)


def test_unsigned_reference_allowed_when_disabled() -> None:
    config = SigningConfig(mode="disabled")

    assert validate_reference_signature("stele://default/abc", config).artifact_id == "abc"
