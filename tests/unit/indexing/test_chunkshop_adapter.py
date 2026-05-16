"""chunk_id <-> chunkshop row translation (SC-011). No chunkshop import."""

from __future__ import annotations

import subprocess
import sys

import pytest

from stele.core.exceptions import BackendError
from stele.indexing.chunkshop_adapter import (
    score_from_distance,
    split_chunk_id,
    stele_chunk_id,
)


def test_chunk_id_format() -> None:
    assert stele_chunk_id("aid", 0) == "aid:0"
    assert stele_chunk_id("01HXYZ", 12) == "01HXYZ:12"


def test_round_trip() -> None:
    for aid, ordn in [("aid", 0), ("01HXYZ", 12), ("a-b_c", 7)]:
        assert split_chunk_id(stele_chunk_id(aid, ordn)) == (aid, ordn)


def test_artifact_id_containing_colon_round_trips() -> None:
    # Ordinal is always the final segment -> rsplit on last ':'.
    cid = stele_chunk_id("ns:default:aid", 3)
    assert cid == "ns:default:aid:3"
    assert split_chunk_id(cid) == ("ns:default:aid", 3)


@pytest.mark.parametrize(
    "bad",
    ["", "noseparator", "aid:", ":3", "aid:notanint", "aid:-1", "aid:1.5"],
)
def test_malformed_raises_backend_error(bad: str) -> None:
    with pytest.raises(BackendError):
        split_chunk_id(bad)


def test_score_from_distance_clamps() -> None:
    assert score_from_distance(0.0) == 1.0
    assert score_from_distance(1.0) == 0.0
    assert score_from_distance(2.0) == 0.0  # clamp low
    assert score_from_distance(-0.2) == 1.0  # clamp high
    assert score_from_distance(0.25) == pytest.approx(0.75)


def test_no_chunkshop_import() -> None:
    # Clean subprocess: chunkshop is installed, so an in-session sys.modules
    # check is order-fragile. Importing only the adapter must not pull it in.
    code = (
        "import sys, stele.indexing.chunkshop_adapter as a; "
        "assert not [m for m in sys.modules if m == 'chunkshop' "
        "or m.startswith('chunkshop.')], 'adapter imported chunkshop'; "
        "print('clean')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "clean"
