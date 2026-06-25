import pytest

from stele.core.exceptions import ValidationError
from stele.core.ledger import validate_ledger_record


def test_decision_requires_rationale_and_scope():
    with pytest.raises(ValidationError) as exc:
        validate_ledger_record("decision", {"summary": "use Redis"})
    assert "rationale" in str(exc.value)


def test_decision_with_required_fields_passes():
    validate_ledger_record("decision",
                           {"summary": "use Redis", "rationale": "ops overhead"})


def test_verification_method_requires_method():
    with pytest.raises(ValidationError):
        validate_ledger_record("verification_method", {"summary": "db version"})


def test_unknown_mode_is_noop():
    validate_ledger_record("fact", {})  # not a ledger mode -> no requirement
