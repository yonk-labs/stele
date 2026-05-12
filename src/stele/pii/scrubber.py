"""PII scrubber factory."""

from stele.core.artifact import ScrubResult
from stele.core.config import PIIConfig
from stele.pii.regex import RegexPIIScrubber


class DisabledPIIScrubber:
    def scrub(self, text: str, *, context: dict[str, object] | None = None) -> ScrubResult:
        del context
        return ScrubResult(text=text, detections=[])


def build_pii_scrubber(config: PIIConfig) -> RegexPIIScrubber | DisabledPIIScrubber:
    if not config.enabled:
        return DisabledPIIScrubber()
    return RegexPIIScrubber()

