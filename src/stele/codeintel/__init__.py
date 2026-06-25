"""codeintel — the code-intelligence sync layer (file watcher + manifest).

Best-of-both-worlds with CodeGraph (MIT design port; see NOTICE): keep stele's
bounded-view assembler + memory, add a content-hash file manifest and a watcher
that keeps it fresh. Distinct from ``stele.codeview`` (the pure bounded-view
assembler); codeintel is the persistent/sync concern that future incremental
indexing and staleness reporting build on.
"""

from __future__ import annotations

from stele.codeintel.graph import GraphResolver
from stele.codeintel.manifest import Changes, FileManifest, default_ignore
from stele.codeintel.watcher import WatchUnavailable, is_wsl, watch, watching_disabled

__all__ = [
    "Changes",
    "FileManifest",
    "GraphResolver",
    "WatchUnavailable",
    "default_ignore",
    "is_wsl",
    "watch",
    "watching_disabled",
]
