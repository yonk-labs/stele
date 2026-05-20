"""Storage backend protocol."""

from typing import Protocol

from stele.core.artifact import Artifact, ArtifactRecord, CleanupResult, Page
from stele.core.capabilities import StorageCapabilities
from stele.core.reference import Reference


class StorageBackend(Protocol):
    def initialize(self) -> None: ...
    def store(self, artifact: Artifact) -> ArtifactRecord: ...
    def fetch(self, reference: Reference) -> ArtifactRecord: ...
    def try_fetch(self, reference: Reference) -> ArtifactRecord | None: ...
    def list(
        self,
        *,
        namespace: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[ArtifactRecord]: ...
    def delete(self, reference: Reference) -> bool: ...
    def delete_namespace(self, namespace: str) -> int:
        """Hard-delete every artifact in ``namespace``. Returns the count
        removed. Idempotent: a namespace with zero artifacts returns 0.
        Other namespaces are never touched.

        Used by :meth:`Stele.purge_namespace` for GDPR-style lifecycle ops.
        Backend implementations MUST scope the DELETE by ``namespace=`` —
        callers depend on cross-namespace isolation.
        """
        ...
    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult: ...
    def capabilities(self) -> StorageCapabilities: ...
    def close(self) -> None: ...

