"""Summary provider contract."""

from typing import Protocol


class SummaryProvider(Protocol):
    def summarize(self, text: str, *, max_chars: int = 1200) -> str: ...

