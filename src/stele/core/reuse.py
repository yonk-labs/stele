"""Canary reuse gate for cached outcomes (pure, I/O-free, LLM-free).

Decide whether a stored outcome is still valid to reuse using ONE cheap broad fingerprint of
the current environment instead of per-dependency checks. Drift anywhere in the fingerprinted
slice (including dimensions never explicitly declared) invalidates the cache; only drift
OUTSIDE the slice slips through (the semantic blind spot). This is the mechanism validated in
``benchmarks/outcome_reuse.py`` (``_canary``) and the assurance lanes, ported for
``Stele.memory``. See docs/specs/ledger-record-spec.md section 12.

The fingerprint is stored on an outcome memory's ``metadata`` (JSON-backed, so it round-trips
on every backend), which is why both inputs are normalized before comparison: a tuple written
at derivation comes back as a list after a JSON round trip.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

# metadata keys carrying the canary anchors on an outcome memory record.
META_FINGERPRINT = "reuse_fingerprint"
META_FINGERPRINT_DIMS = "reuse_fingerprint_dims"
META_DECLARED_DEPS = "reuse_declared_deps"
META_DEPS_AT_DERIVATION = "reuse_deps_at_derivation"
META_COST = "reuse_cost"
META_TTL = "reuse_ttl_seconds"
META_SOURCE_HASH = "reuse_source_hash"  # content fingerprint of a recalled context's source
META_INTENT = "reuse_intent"  # the trigger an outcome/procedure/context answers (routing key)
META_ENV = "reuse_env"  # applicability snapshot for a procedure (env observed at recording)

Fingerprint = list[list[str]]  # sorted [key, value] pairs; JSON-friendly


def fingerprint(env: dict[str, str], dims: tuple[str, ...] | None = None) -> Fingerprint:
    """A cheap broad drift fingerprint over an observable env slice (default: the whole slice).

    One comparison catches ANY in-slice drift, including dimensions not explicitly declared.
    Pass ``dims`` to scope the slice (the tuning knob) and exclude known-irrelevant churn.
    """
    keys = sorted(env) if dims is None else sorted(d for d in dims if d in env)
    return [[k, env[k]] for k in keys]


def _norm(fp: object) -> list[tuple[str, str]]:
    """Normalize a fingerprint (tuple-of-tuples or JSON list-of-lists) to comparable form."""
    if not isinstance(fp, (list, tuple)):
        return []
    return [(str(pair[0]), str(pair[1])) for pair in fp]


def is_valid(
    stored: object, current_env: dict[str, str], dims: tuple[str, ...] | None = None
) -> bool:
    """True if a stored outcome is still valid to reuse: its broad fingerprint matches the
    current environment. False means in-slice drift, so the caller should re-derive."""
    return _norm(stored) == _norm(fingerprint(current_env, dims))


def is_expired(created_at: datetime, ttl_seconds: float | None, now: datetime) -> bool:
    """True if a stored outcome has aged past its TTL: a time bound on the canary's semantic
    blind spot (drift you cannot observe). ``ttl_seconds=None`` means no bound (default, off), so
    it stays opt-in and back-compatible. This is the caller's FIRST gate: a stale outcome is
    distrusted even when its fingerprint still matches. The boundary is inclusive (age == ttl is
    still fresh; strict ``>``)."""
    if ttl_seconds is None:
        return False
    return now - created_at > timedelta(seconds=ttl_seconds)


def source_hash(text: str) -> str:
    """Content fingerprint of a source a recalled context was derived from (Phase 3)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_stale(
    stored_hash: str | None,
    current_source: str | None,
    created_at: datetime,
    ttl_seconds: float | None,
    now: datetime,
) -> bool:
    """True if recalled context can no longer be trusted: its source changed
    (observable drift) OR it has aged past its TTL (the backstop for drift you cannot
    observe). The source-hash check is skipped when the stored hash or the current
    source is absent, so freshness then rests on TTL alone (the unverified-source case).
    Mirrors the outcome canary+TTL pairing, ported to context recall."""
    if (
        stored_hash is not None
        and current_source is not None
        and source_hash(current_source) != stored_hash
    ):
        return True
    return is_expired(created_at, ttl_seconds, now)


@dataclass(frozen=True)
class Decision:
    """A reuse verdict and the reason for it (no record attached; that is the facade's job)."""

    reuse: bool
    reason: str  # "fingerprint-match" | "drift" | "reused-noise" | "not-worth-reuse"


def _num(cost: dict[str, object], key: str, default: int) -> int:
    v = cost.get(key, default)
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def worth_reusing(cost: dict[str, object] | None, n_checks: int) -> bool:
    """Cost gate (the benchmark's net>0): reuse pays only if validating (``n_checks`` cheap
    checks) plus one recall costs fewer turns than re-deriving from scratch. With no recorded
    derive cost the gate is OFF (reuse purely on validity), so it is opt-in and back-compatible:
    record a ``cost={"derive": N, ...}`` to enable it."""
    if not cost:
        return True
    derive = _num(cost, "derive", 0)
    if derive <= 0:
        return True
    return derive - n_checks * _num(cost, "check", 1) - _num(cost, "recall", 1) > 0


def decide_canary(
    stored: object,
    current_env: dict[str, str],
    dims: tuple[str, ...] | None = None,
    cost: dict[str, object] | None = None,
) -> Decision:
    """Canary gate: reuse only when the broad fingerprint is unchanged AND reuse is worth it."""
    if not is_valid(stored, current_env, dims):
        return Decision(reuse=False, reason="drift")
    if not worth_reusing(cost, n_checks=1):
        return Decision(reuse=False, reason="not-worth-reuse")
    return Decision(reuse=True, reason="fingerprint-match")


def decide_tiered(
    stored: object,
    dims: tuple[str, ...] | None,
    declared: list[str],
    deps_at_derivation: dict[str, object],
    current_env: dict[str, str],
    cost: dict[str, object] | None = None,
) -> Decision:
    """Tiered gate: the broad fingerprint first; on a trip, a NARROW check of the declared
    (believed-relevant) dimensions tells real drift from noise instead of blindly re-deriving.
    A clean broad slice reuses; a declared dimension that drifted re-derives; a trip from only
    UNDECLARED dimensions is reused optimistically (``reused-noise``), removing the canary's
    over-invalidation at the cost of a possible false-valid the caller can later teach away via
    learning. Either reuse path also passes the cost gate. This is the validated tiered arm."""
    if is_valid(stored, current_env, dims):
        if not worth_reusing(cost, n_checks=1):
            return Decision(reuse=False, reason="not-worth-reuse")
        return Decision(reuse=True, reason="fingerprint-match")
    drifted = any(
        str(current_env.get(d)) != str(deps_at_derivation.get(d)) for d in declared
    )
    if drifted:
        return Decision(reuse=False, reason="drift")
    if not worth_reusing(cost, n_checks=2):
        return Decision(reuse=False, reason="not-worth-reuse")
    return Decision(reuse=True, reason="reused-noise")
