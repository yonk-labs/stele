from stele import Stele


def test_chunk_index_returns_targeted_chunk_not_whole_artifact() -> None:
    stash = Stele.from_config(
        {
            "backend": {"type": "memory"},
            "indexing": {
                "provider": "chunkshop",
                "mode": "sync",
                "chunk_words": 8,
                "chunk_overlap_words": 2,
            },
        }
    )
    content = (
        "alpha alpha alpha alpha alpha alpha alpha alpha "
        "the deployment fix is to rebuild the postgres index "
        "omega omega omega omega omega omega omega omega"
    )
    stored = stash.store(content, namespace="chunked")

    hits = stash.search(stored.reference, "postgres index", mode="hybrid")

    assert hits
    assert hits[0].chunk_id is not None
    assert hits[0].retrieval_mode == "hybrid"
    assert "postgres index" in hits[0].text
    assert len(hits[0].text) < len(content)


def test_chunk_index_is_deleted_with_artifact() -> None:
    stash = Stele.from_config(
        {
            "backend": {"type": "memory"},
            "indexing": {"provider": "chunkshop", "mode": "sync", "chunk_words": 4},
        }
    )
    stored = stash.store("mariadb migration marker", namespace="chunked")

    assert stash.search(stored.reference, "marker")
    assert stash.delete(stored.reference) is True
    assert stash.chunk_index is not None
    assert stash.chunk_index.search_reference(stored.reference, "marker", limit=10) == []
