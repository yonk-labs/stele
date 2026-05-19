"""Deterministic 100-document corpus for living-knowledge / tool-call /
PII tests and the runtime benchmark. No randomness — same output every run
so benchmark numbers and test assertions are stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Lane = Literal[
    "versioned_docs", "retracted_claim", "policy_update",
    "account_state", "pii_heavy", "tool_output", "plain",
]
_LANES: list[Lane] = [
    "versioned_docs", "retracted_claim", "policy_update",
    "account_state", "pii_heavy", "tool_output", "plain",
]


@dataclass(frozen=True)
class CorpusDoc:
    id: str
    lane: Lane
    text: str
    fact: str                  # answer-bearing phrase (PII-free)
    pii: str | None            # raw PII that MUST be scrubbed, or None
    version: str | None        # version label, or None
    supersedes: str | None     # corpus id this doc supersedes, or None
    retract: bool              # should be retracted post-ingest


def _doc(i: int, lane: Lane) -> CorpusDoc:
    did = f"doc-{i:03d}"
    if lane == "versioned_docs":
        ver = "v2" if i % 2 else "v1"
        fact = f"service-{i} auth uses {'OAuth2' if ver == 'v2' else 'API keys'}"
        sup = f"doc-{i - 1:03d}" if ver == "v2" and i > 0 else None
        return CorpusDoc(did, lane, f"API doc {ver}: {fact}.", fact, None,
                         ver, sup, False)
    if lane == "retracted_claim":
        fact = f"compound-Z{i} reduces risk by {i % 50}%"
        return CorpusDoc(did, lane, f"Study {i}: {fact}.", fact, None,
                         None, None, True)
    if lane == "policy_update":
        ver = f"20{20 + i % 6}"
        fact = f"travel policy {ver}: {'business' if i % 2 else 'economy'} class"
        return CorpusDoc(did, lane, f"Policy {ver}. {fact}.", fact, None,
                         ver, None, False)
    if lane == "account_state":
        tier = "enterprise" if i % 3 == 0 else "free"
        fact = f"account-{i} tier is {tier}"
        return CorpusDoc(did, lane, f"Account update: {fact}.", fact, None,
                         None, None, False)
    if lane == "pii_heavy":
        email = f"user{i}@example.com"
        fact = f"ticket-{i} priority is {'high' if i % 2 else 'low'}"
        return CorpusDoc(
            did, lane,
            f"Reporter {email} (SSN 123-45-{i:04d}) filed it. {fact}.",
            fact, email, None, None, False,
        )
    if lane == "tool_output":
        fact = f"build-{i} exit code is {i % 2}"
        body = f"$ make test\n{fact}.\n" + ("stack frame line. " * 60)
        return CorpusDoc(did, lane, body, fact,
                         f"ops{i}@example.com", None, None, False)
    fact = f"note-{i}: deploy region is {'eu-west-1' if i % 2 else 'us-east-1'}"
    return CorpusDoc(did, lane, f"{fact}.", fact, None, None, None, False)


def sample_corpus(n: int = 100) -> list[CorpusDoc]:
    return [_doc(i, _LANES[i % len(_LANES)]) for i in range(n)]
