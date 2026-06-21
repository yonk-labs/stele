from typing import Literal

import pytest

from stele.extraction.registry import (
    ExistingSubject,
    SubjectDisambiguationError,
    resolve_subject,
)


def _resolve(
    label: str,
    *,
    existing: list[ExistingSubject] | None = None,
    aliases: dict[str, str] | None = None,
    user_id: str | None = None,
    subject_type: str = "service",
    on_ambiguous: Literal["refuse", "mint"] = "refuse",
    proposed_subject_id: str | None = None,
) -> str:
    return resolve_subject(
        scope_key="ns=proj",
        subject_type=subject_type,
        raw_label=label,
        user_id=user_id,
        existing=existing or [],
        aliases=aliases or {},
        proposed_subject_id=proposed_subject_id,
        on_ambiguous=on_ambiguous,
    )


def test_mint_is_deterministic_same_label() -> None:
    assert _resolve("postgres") == _resolve("postgres") == "service:postgres"


def test_alias_binds_different_label_to_same_id() -> None:
    # the #69 fix (curated path): "production" is an explicit alias of postgres
    aliases = {"production": "service:postgres"}
    assert _resolve("production", aliases=aliases) == "service:postgres"


def test_validated_handoff_selects_existing_id() -> None:
    # the #69 fix (no manual alias): the extractor LLM saw the active subjects and
    # handed back the existing id for a drifted label.
    existing = [ExistingSubject("service:postgres", "service", "postgres")]
    assert (
        _resolve(
            "production",
            existing=existing,
            proposed_subject_id="service:postgres",
        )
        == "service:postgres"
    )


def test_invalid_handoff_is_ignored_then_mints() -> None:
    # the LLM may only SELECT an active id; an unknown proposal is ignored.
    assert (
        _resolve("production", proposed_subject_id="service:bogus")
        == "service:production"
    )


def test_distinct_labels_stay_distinct_without_alias() -> None:
    # no auto-merge: over-merge is worse than under-merge
    assert _resolve("postgres") != _resolve("mysql")


def test_self_referential_resolves_to_user() -> None:
    assert _resolve("I", user_id="u42", subject_type="user") == "user:u42"
    assert _resolve("the user", user_id="u42", subject_type="user") == "user:u42"


def test_self_ref_without_user_id_falls_through() -> None:
    # "I" with no user_id must NOT become "user:None"; it falls through to mint
    assert _resolve("I", user_id=None) == "service:i"


def test_ambiguous_refuses_by_default() -> None:
    existing = [
        ExistingSubject("service:pg-a", "service", "postgres"),
        ExistingSubject("service:pg-b", "service", "postgres"),
    ]
    with pytest.raises(SubjectDisambiguationError):
        _resolve("postgres", existing=existing)


def test_ambiguous_mints_when_policy_allows() -> None:
    existing = [
        ExistingSubject("service:pg-a", "service", "postgres"),
        ExistingSubject("service:pg-b", "service", "postgres"),
    ]
    out = _resolve("postgres", existing=existing, on_ambiguous="mint")
    assert out == "service:postgres"


def test_alias_beats_conflicting_handoff() -> None:
    # A curated alias is authoritative; a valid LLM handoff to a DIFFERENT active
    # id must NOT override it.
    existing = [
        ExistingSubject("service:postgres", "service", "postgres"),
        ExistingSubject("service:other", "service", "other"),
    ]
    out = _resolve(
        "prod",
        existing=existing,
        aliases={"prod": "service:postgres"},
        proposed_subject_id="service:other",
    )
    assert out == "service:postgres"  # alias wins, not the handoff
