"""Interception threshold policy."""

from stele.core.artifact import estimate_tokens
from stele.core.config import InterceptionConfig


def should_intercept(text: str, config: InterceptionConfig, *, always_store: bool = False) -> bool:
    if always_store:
        return True
    if not config.enabled:
        return False
    return len(text) >= config.min_chars or estimate_tokens(text) >= config.min_estimated_tokens

