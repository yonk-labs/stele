"""Task 0: SessionMemory schema gains subject_type + subject_id.
Task 6: build_extract_prompt known-subject handoff.
"""

from __future__ import annotations


def test_session_memory_has_subject_type_and_id() -> None:
    from stele.extraction.session import SessionMemory
    m = SessionMemory(kind="fact", summary="x", detail="",
                      subject_label="postgres", aspect="version")
    assert m.subject_type == "entity"   # safe default
    assert m.subject_id is None
    m2 = SessionMemory(kind="fact", summary="x", detail="", subject_label="postgres",
                       aspect="version", subject_type="service",
                       subject_id="service:postgres")
    assert m2.subject_type == "service" and m2.subject_id == "service:postgres"


def test_prompt_offers_known_subjects_for_handoff() -> None:
    from stele.extraction.session import build_extract_prompt
    known = [("service:postgres", "postgres"), ("project:ci", "ci")]
    p = build_extract_prompt(window="...", known_subjects=known)
    assert "service:postgres" in p
    assert "postgres" in p
    assert "subject_id" in p  # instructs the model to return an existing id
    p2 = build_extract_prompt(window="...", known_subjects=[])
    assert "service:postgres" not in p2  # nothing injected when none known
    p3 = build_extract_prompt(window="...", known_subjects=None)
    assert "service:postgres" not in p3  # same: no-op when None
