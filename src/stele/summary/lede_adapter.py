"""Adapter for lede summaries with a deterministic local fallback."""

from __future__ import annotations

import re

from stele.core.exceptions import SteleError


class LedeSummaryProvider:
    def summarize(self, text: str, *, max_chars: int = 1200) -> str:
        if not text:
            return ""
        try:
            from lede import summarize as lede_summarize

            result = lede_summarize(text, max_length=max_chars)
            summary = getattr(result, "summary", result)
            return _trim(str(summary), max_chars)
        except ModuleNotFoundError:
            return _fallback_summary(text, max_chars=max_chars)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise SteleError("Summary generation failed") from exc


def _fallback_summary(text: str, *, max_chars: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return _trim(text, max_chars)
    picked: list[str] = []
    total = 0
    for sentence in sentences:
        if not sentence:
            continue
        next_total = total + len(sentence) + (1 if picked else 0)
        if next_total > max_chars and picked:
            break
        picked.append(sentence)
        total = next_total
        if total >= max_chars:
            break
    return _trim(" ".join(picked) if picked else text, max_chars)


def _trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."
