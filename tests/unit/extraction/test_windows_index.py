from stele.extraction.session import Turn, windows


def test_windows_return_indexed_in_original_order():
    turns = [Turn("user", "x" * 4100), Turn("assistant", "y" * 4100),
             Turn("result", "boom", is_error=True)]
    out = windows(turns, max_chars=4000, limit=3)
    assert all(isinstance(w, tuple) and isinstance(w[0], int) for w in out)
    idxs = [w[0] for w in out]
    assert idxs == sorted(idxs)  # chronological
