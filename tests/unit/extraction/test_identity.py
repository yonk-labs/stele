from stele.extraction.identity import (
    canonical_aspect,
    canonical_subject,
    canonical_subject_type,
    is_self_referential,
)


def test_subject_type_seeded_and_default() -> None:
    assert canonical_subject_type("Service") == "service"
    assert canonical_subject_type("") == "entity"        # empty -> default
    assert canonical_subject_type("widget") == "widget"  # unknown kept distinct
    assert canonical_subject_type("my service") == "my_service"  # multi-word to underscore


def test_self_referential_detection() -> None:
    assert is_self_referential("I")
    assert is_self_referential("me")
    assert is_self_referential("the user")
    assert not is_self_referential("postgres")
    assert not is_self_referential("Test 1")
    assert not is_self_referential("user")  # bare "user" is ambiguous, not self-ref
    assert canonical_subject_type("user") == "user"  # "user" stays a valid seeded type


def test_subject_variants_collapse() -> None:
    assert (
        canonical_subject("Test 1")
        == canonical_subject("test1")
        == canonical_subject("test-1")
        == "test 1"
    )


def test_distinct_subjects_stay_distinct() -> None:
    assert canonical_subject("Test 1") != canonical_subject("Test 2")


def test_empty_subject_is_empty() -> None:
    assert canonical_subject("  ") == ""


def test_aspect_synonyms_fold() -> None:
    assert canonical_aspect("reliability") == "status"
    assert canonical_aspect("scope") == "coverage"


def test_unknown_aspect_kept_distinct_not_other() -> None:
    # never silently folded into a wrong/shared bucket
    assert canonical_aspect("latency") == "latency"


def test_empty_aspect_is_empty() -> None:
    assert canonical_aspect("") == ""


def test_implementation_cluster_folds_to_one_aspect() -> None:
    # #72: the "what technology IS it" attribute is the one the LLM relabels most
    # across sessions; fold the cluster so a value swap lands in one slot.
    folded = {
        canonical_aspect(a)
        for a in ("engine", "runtime", "framework", "platform",
                  "technology", "tech", "tool")
    }
    assert folded == {"implementation"}


def test_scale_synonyms_fold() -> None:
    assert canonical_aspect("replica_count") == canonical_aspect("replicas") == "replicas"
    assert canonical_aspect("replica") == "replicas"


def test_implementation_fold_does_not_swallow_distinct_aspects() -> None:
    # Over-merge guard at the canonicalizer: folding the implementation cluster
    # must NOT collapse genuinely-distinct attributes of the same subject.
    impl = canonical_aspect("engine")
    assert impl == "implementation"
    for distinct in ("version", "location", "owner", "status", "coverage", "config"):
        assert canonical_aspect(distinct) != impl
    # seeded aspects still pass through untouched
    assert canonical_aspect("version") == "version"
    assert canonical_aspect("location") == "location"
