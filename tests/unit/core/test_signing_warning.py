import warnings

import pytest

from stele import Stele
from stele.core.exceptions import SteleSecurityWarning


def test_disabled_signing_emits_security_warning() -> None:
    with pytest.warns(SteleSecurityWarning) as record:
        Stele.from_config({"backend": {"type": "memory"}})

    messages = [str(w.message) for w in record]
    assert any(
        "signing" in m and ("forgeable" in m or "DISABLED" in m or "disabled" in m)
        for m in messages
    ), messages


def test_optional_signing_does_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", SteleSecurityWarning)
        Stele.from_config(
            {"backend": {"type": "memory"}, "signing": {"mode": "optional"}}
        )


def test_required_signing_does_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", SteleSecurityWarning)
        Stele.from_config(
            {
                "backend": {"type": "memory"},
                "signing": {"mode": "required", "secret": "x" * 32},
            }
        )
