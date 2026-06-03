# ruff: noqa: E501 -- minify utility.
"""Minify agent transcripts: reduce to signal before storing/embedding.

Two modes (the user's two timings):
  --file PATH        minify a transcript on the way IN (print minified; store it
                     instead of / alongside the raw). Lossy vs exact bytes, so use
                     for a derivative, or accept loss for the 30-day raw tier.
  --ref stele://...  minify an ALREADY-stored artifact AFTER the fact. Re-stores
                     the minified text as a new artifact, which RE-CHUNKS and
                     RE-EMBEDS it when indexing is on (the original embeddings were
                     built on the full text and are now stale).

--caveman adds lede.clean_text (filler/markdown/boilerplate) on natural-language
turns only; lossy, best for the embedding path. Structural reduction is always on.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from stele.extraction.session import minify_transcript


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="path to a transcript (.jsonl or message JSON)")
    src.add_argument("--ref", help="stele:// ref of an already-stored transcript artifact")
    ap.add_argument("--caveman", action="store_true", help="also run lede.clean_text on prose (lossy; embedding path)")
    ap.add_argument("--store", action="store_true", help="(with --ref) re-store the minified artifact (re-embeds)")
    ap.add_argument("--namespace", default="minified")
    ap.add_argument("--dsn", default=None)
    args = ap.parse_args(argv)

    if args.file:
        raw_len = len(Path(args.file).read_text(errors="replace"))
        mini = minify_transcript(args.file, caveman=args.caveman)
        print(f"# minified {raw_len} -> {len(mini)} chars ({(1 - len(mini) / max(raw_len, 1)) * 100:.0f}% smaller)")
        print(mini)
        return 0

    # --ref: minify a stored artifact, optionally re-store (re-embeds)
    from stele.core.config import BackendConfig, StashConfig
    from stele.core.stash import Stele

    dsn = args.dsn or os.environ.get("STELE_PG_DSN")
    if not dsn:
        raise SystemExit("set STELE_PG_DSN or pass --dsn for --ref mode")
    stele = Stele(config=StashConfig(backend=BackendConfig(type="postgres", dsn=dsn)))
    fetched = stele.fetch(args.ref)
    content = fetched.content if isinstance(fetched.content, str) else fetched.content.decode("utf-8", errors="replace")
    raw_len = len(content)
    # the stored transcript may be rendered text already; minify handles message-JSON or falls through
    mini = minify_transcript(content, caveman=args.caveman)
    print(f"# {args.ref}: {raw_len} -> {len(mini)} chars ({(1 - len(mini) / max(raw_len, 1)) * 100:.0f}% smaller)")
    if args.store:
        new_ref = str(stele.store(mini, namespace=args.namespace).reference)
        print(f"# re-stored minified -> {new_ref}")
        print("# NOTE: this re-chunks/re-embeds the minified text (indexing on); the "
              "original artifact's embeddings are now stale -- delete it or let its TTL expire.")
    else:
        print(mini[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
