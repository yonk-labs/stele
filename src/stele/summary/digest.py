"""Digest packer — the proven-best hybrid-search packing.

Packs a set of retrieved hits into a query-biased lede summary + extracted
facts (``lede.readable_report``) followed by the top-N raw chunks. This is the
same shape as pg-raggraph's ``balanced`` profile / chunkshop ``summarize_hits``.

Lives under ``summary/`` (lede is allowed here) and is injected into the recall
layer via ``_RecallDeps`` so ``recall/`` never imports lede.
"""

from __future__ import annotations

from collections.abc import Sequence

from stele.core.artifact import SearchHit


class DigestPacker:
    def __init__(self, *, top_chunks: int = 5, summary_max_chars: int = 2000) -> None:
        self._top_chunks = top_chunks
        self._summary_max_chars = summary_max_chars

    def pack(self, hits: Sequence[SearchHit], query: str) -> str:
        if not hits:
            return ""
        joined = "\n\n".join(hit.text for hit in hits if hit.text)
        if not joined:
            return ""
        top = "\n\n---\n\n".join(hit.text for hit in hits[: self._top_chunks] if hit.text)
        try:
            import lede

            report = lede.readable_report(
                joined,
                max_length=self._summary_max_chars,
                hints=[query] if query else None,
            )
            summary_block = report.to_markdown()
        except ModuleNotFoundError:
            # No lede — degrade to the raw top chunks (still useful context).
            return top
        except Exception:  # pragma: no cover - defensive: never fail recall on packing
            return top
        return f"{summary_block}\n\n## Retrieved Chunks\n\n{top}"
