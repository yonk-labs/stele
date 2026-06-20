from stele.extraction.identity import canonical_aspect, canonical_subject


def test_subject_variants_collapse():
    assert (
        canonical_subject("Test 1")
        == canonical_subject("test1")
        == canonical_subject("test-1")
        == "test 1"
    )


def test_distinct_subjects_stay_distinct():
    assert canonical_subject("Test 1") != canonical_subject("Test 2")


def test_empty_subject_is_empty():
    assert canonical_subject("  ") == ""


def test_aspect_synonyms_fold():
    assert canonical_aspect("reliability") == "status"
    assert canonical_aspect("scope") == "coverage"


def test_unknown_aspect_kept_distinct_not_other():
    # never silently folded into a wrong/shared bucket
    assert canonical_aspect("latency") == "latency"


def test_empty_aspect_is_empty():
    assert canonical_aspect("") == ""
