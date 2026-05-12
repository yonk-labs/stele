"""PII scrubber contract."""

from typing import Protocol

from stele.core.artifact import ScrubResult


class PIIScrubber(Protocol):
    def scrub(self, text: str, *, context: dict[str, object] | None = None) -> ScrubResult: ...

