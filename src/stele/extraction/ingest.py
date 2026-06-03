"""Streaming conversation feed: reduce a Claude session to its keep120 signal at
the INGESTION boundary and store it as one reduced artifact (never the raw bytes).

This is the live-stream counterpart to distill-time parsing. A Claude Code
SessionEnd/Stop hook calls ``stele-ingest <transcript_path>``; every event flows
through the same ``reduce_event`` filter the backfill uses (signatures, snapshots,
metadata dropped; tool bodies truncated; role + is_error kept), so the stored
session is already reduced and PII-scrubbed (the store boundary scrubs when
``pii.enabled``). Distillation later reads this reduced artifact -- the raw
transcript never has to be stored or re-parsed.

The reduction is config-driven (``ExtractionConfig.reduce_*``), so the live feed
and the on-disk backfill stay in lock-step.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from stele.core.config import ExtractionConfig
from stele.core.stash import Stele
from stele.extraction.session import (
    ReduceConfig,
    Turn,
    parse_claude_jsonl,
    reduce_event,
    render,
)

DEFAULT_TTL_SECONDS = 30 * 86_400  # raw retention window; distilled memory has none


def reduce_config_from(extraction: ExtractionConfig) -> ReduceConfig:
    """The one place the ExtractionConfig.reduce_* knobs become a ReduceConfig,
    so the stream feed and the backfill parser reduce identically."""
    return ReduceConfig(
        result_chars=extraction.reduce_result_chars,
        error_chars=extraction.reduce_error_chars,
        tool_chars=extraction.reduce_tool_chars,
        drop_success_results=extraction.reduce_drop_success_results,
    )


def reduce_stream(events: Iterable[dict[str, Any]], cfg: ReduceConfig | None = None) -> list[Turn]:
    """Apply ``reduce_event`` to a live, ordered stream of transcript events.
    Pure and incremental: this is what a per-event hook accumulates."""
    cfg = cfg or ReduceConfig()
    turns: list[Turn] = []
    for ev in events:
        turns.extend(reduce_event(ev, cfg))
    return turns


def ingest_session(
    stele: Stele,
    *,
    transcript: str | Path | Iterable[dict[str, Any]],
    namespace: str = "sessions",
    session_id: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    cfg: ReduceConfig | None = None,
    keep_raw: bool = False,
) -> dict[str, Any]:
    """Reduce a whole session (a ``.jsonl`` path, or an iterable of event dicts)
    and store it as ONE reduced artifact carrying a TTL. The reduction tier is
    `cfg` (keep120 default; result_chars=300 for keep300; None for the full,
    untruncated tier). PII scrubbing is inherited from the store boundary.

    keep_raw=True ALSO stores the exact original bytes as a second artifact
    (source=session-raw) for full-fidelity retention, so you can keep both the
    distill-ready reduced form and the verbatim raw. Returns
    ``{ref, raw_ref, turns, chars}`` (refs are None for an empty/thin session)."""
    cfg = cfg or reduce_config_from(stele.config.extraction)
    raw_path: Path | None = None
    if isinstance(transcript, str | Path):
        raw_path = Path(str(transcript))
        turns = parse_claude_jsonl(raw_path, cfg)
    else:
        turns = reduce_stream(transcript, cfg)
    if not turns:
        return {"ref": None, "raw_ref": None, "turns": 0, "chars": 0}
    text = render(turns)
    stored = stele.store(
        text,
        namespace=namespace,
        session_id=session_id,
        ttl_seconds=ttl_seconds,
        metadata={"source": "session-ingest", "reduced": True},
    )
    raw_ref: str | None = None
    if keep_raw and raw_path is not None:
        raw_stored = stele.store(
            raw_path.read_bytes(),
            namespace=namespace,
            session_id=session_id,
            ttl_seconds=ttl_seconds,
            metadata={"source": "session-raw", "reduced": False},
        )
        raw_ref = str(raw_stored.reference)
    return {"ref": str(stored.reference), "raw_ref": raw_ref,
            "turns": len(turns), "chars": len(text)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="stele-ingest",
        description="Reduce a Claude session transcript (keep120) and store it as "
        "one artifact. Meant to be called from a SessionEnd/Stop hook.",
    )
    ap.add_argument("transcript", help="path to the session .jsonl (Claude's transcript_path)")
    ap.add_argument("--namespace", default="sessions")
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--ttl-days", type=float, default=30.0)
    ap.add_argument("--result-chars", type=int, default=None,
                    help="truncate successful results to N chars (e.g. 300 for keep300; "
                    "default: config keep120)")
    ap.add_argument("--full", action="store_true",
                    help="keep full result/tool bodies (no truncation)")
    ap.add_argument("--keep-raw", action="store_true",
                    help="ALSO store the exact raw transcript bytes (full-fidelity retention)")
    args = ap.parse_args(argv)

    import dataclasses

    from stele.mcp.config import config_path, load_raw_config

    cfg_path = config_path()
    raw: dict[str, Any] = (
        load_raw_config(cfg_path) if cfg_path else {"backend": {"type": "memory"}}
    )
    stele = Stele.from_config(raw)
    cfg = reduce_config_from(stele.config.extraction)
    if args.full:
        cfg = dataclasses.replace(cfg, result_chars=None, error_chars=None, tool_chars=None)
    elif args.result_chars is not None:
        cfg = dataclasses.replace(cfg, result_chars=args.result_chars)
    report = ingest_session(
        stele,
        transcript=args.transcript,
        namespace=args.namespace,
        session_id=args.session_id,
        ttl_seconds=int(args.ttl_days * 86_400),
        cfg=cfg,
        keep_raw=args.keep_raw,
    )
    sys.stdout.write(json.dumps(report, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
