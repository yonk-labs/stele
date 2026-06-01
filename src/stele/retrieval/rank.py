"""Ranking helpers."""

import re

# Function words carry no retrieval signal. In an OR-joined keyword query they
# only let off-topic chunks match (every chunk contains "the"/"with"/"and"), so
# they're stripped from the QUERY side (never the document side) before scoring
# and before building the FTS expression. Both keyword paths share this set.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
        "could", "did", "do", "does", "for", "from", "had", "has", "have", "he",
        "her", "him", "his", "how", "i", "if", "in", "into", "is", "it", "its",
        "me", "my", "of", "on", "or", "our", "out", "she", "should", "so",
        "that", "the", "their", "them", "then", "they", "this", "to", "up",
        "was", "we", "were", "what", "when", "where", "which", "who", "whom",
        "why", "will", "with", "would", "you", "your",
    }
)


def tokenize(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", value.lower())


def content_terms(query: str) -> list[str]:
    """Query tokens with stopwords removed, order-preserving and de-duplicated.

    Falls back to the full token list when the query is *all* stopwords
    (e.g. "who are they") so such queries still retrieve something.
    """
    tokens = tokenize(query)
    content = [t for t in tokens if t not in STOPWORDS]
    chosen = content or tokens
    seen: set[str] = set()
    deduped: list[str] = []
    for t in chosen:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def keyword_score(query: str, text: str) -> float:
    query_tokens = set(content_terms(query))
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

