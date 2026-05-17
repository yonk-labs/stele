"""Public package exports."""

from stele.core.artifact import (
    Artifact,
    ArtifactRecord,
    CleanupResult,
    ExportResult,
    FetchResult,
    ImportResult,
    Page,
    SearchHit,
    StoredResult,
)
from stele.core.capabilities import StashCapabilities
from stele.core.config import StashConfig
from stele.core.exceptions import (
    ArtifactNotFound,
    BackendError,
    CapabilityError,
    ConfigError,
    OptionalDependencyError,
    PIIBlockedError,
    ReferenceError,
    SignatureError,
    SteleError,
    ValidationError,
)
from stele.core.memory import Memory
from stele.core.memory_record import (
    MemoryAddResult,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
)
from stele.core.stash import Stele
from stele.extraction.models import (
    AcceptedCandidate,
    ExtractionReport,
    ExtractionStats,
    MemoryCandidate,
    RejectedCandidate,
)
from stele.indexing.bakeoff import (
    BakeoffChunker,
    BakeoffConfig,
    BakeoffEmbedder,
    BakeoffSummary,
)
from stele.indexing.task_backend.base import IndexTask, TaskStatus
from stele.recall.models import (
    Citation,
    Escalation,
    RecallContext,
    RecallRequest,
    RecallResult,
    RecallStats,
)

__all__ = [
    "AcceptedCandidate",
    "Artifact",
    "Citation",
    "Escalation",
    "RecallContext",
    "RecallRequest",
    "RecallResult",
    "RecallStats",
    "ArtifactNotFound",
    "ArtifactRecord",
    "BackendError",
    "CapabilityError",
    "CleanupResult",
    "ConfigError",
    "ExportResult",
    "ExtractionReport",
    "ExtractionStats",
    "FetchResult",
    "ImportResult",
    "Memory",
    "MemoryAddResult",
    "MemoryCandidate",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryScope",
    "RejectedCandidate",
    "Stele",
    "SteleError",
    "OptionalDependencyError",
    "PIIBlockedError",
    "Page",
    "ReferenceError",
    "SearchHit",
    "SignatureError",
    "StashConfig",
    "StoredResult",
    "ValidationError",
    # Phase 4 public types
    "StashCapabilities",
    "BakeoffConfig",
    "BakeoffEmbedder",
    "BakeoffChunker",
    "BakeoffSummary",
    "IndexTask",
    "TaskStatus",
]
