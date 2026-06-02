"""Regression for the memory embedder output coercion (stele#39).

The real fastembed embedder returns a numpy array shaped (1, dim); the original
v0.5.0 wrapper did `list(...)` and crashed when building the pgvector literal.
`_to_vector` must flatten any of these shapes to a flat list[float]. The
contract test uses a fake embedder that returns a flat list, so this is the
test that actually exercises the numpy path.
"""

from __future__ import annotations

import numpy as np
import pytest

from stele.storage.memory_store._embedder import _to_vector, vec_literal


def test_flat_list_passthrough() -> None:
    assert _to_vector([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]


def test_nested_single_row_list() -> None:
    assert _to_vector([[1.0, 2.0, 3.0]]) == [1.0, 2.0, 3.0]


def test_numpy_2d_single_row() -> None:
    arr = np.array([[0.5, -0.25, 4.0]], dtype="float32")  # shape (1, 3) like fastembed
    assert _to_vector(arr) == [0.5, -0.25, 4.0]


def test_numpy_1d() -> None:
    assert _to_vector(np.array([1.0, 2.0], dtype="float64")) == [1.0, 2.0]


def test_vec_literal_roundtrips_numpy_output() -> None:
    arr = np.array([[1.0, 2.0, 3.0]], dtype="float32")
    lit = vec_literal(_to_vector(arr))
    assert lit.startswith("[") and lit.endswith("]")
    assert lit.count(",") == 2  # three components -> two separators


def test_to_vector_elements_are_python_floats() -> None:
    out = _to_vector(np.array([[1.0, 2.0]], dtype="float32"))
    assert all(type(x) is float for x in out)


def test_vec_literal_rejects_nothing_for_plain_floats() -> None:
    # vec_literal must not choke on the coerced flat list.
    assert vec_literal([0.1, 0.2]) == "[0.1,0.2]"


@pytest.mark.parametrize("bad_dim_input", [np.zeros((1, 5)), [0.0] * 5])
def test_to_vector_length_matches_elements(bad_dim_input: object) -> None:
    assert len(_to_vector(bad_dim_input)) == 5
