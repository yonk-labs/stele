"""Ranking helpers."""

import re


def tokenize(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", value.lower())


def keyword_score(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    text_tokens = set(tokenize(text))
    return len(query_tokens & text_tokens) / len(query_tokens)


def snippet_around(text: str, query: str, *, max_chars: int = 500) -> str:
    if len(text) <= max_chars:
        return text
    lower = text.lower()
    positions = [lower.find(token) for token in tokenize(query)]
    positions = [pos for pos in positions if pos >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - max_chars // 3)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"

