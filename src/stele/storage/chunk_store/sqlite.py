"""SQLite chunk store — chunkshop 0.4.3 sqlite-vec sink."""

from __future__ import annotations

from typing import Literal

from stele.core.config import IndexingConfig
from stele.storage.chunk_store._chunkshop_base import ChunkshopChunkStore


class SQLiteChunkStore(ChunkshopChunkStore):
    name: Literal["sqlite"] = "sqlite"
    _target_type: Literal["sqlite"] = "sqlite"

    def __init__(
        self, config: IndexingConfig, *, db_path: str, table: str = "chunks"
    ) -> None:
        super().__init__(config, dsn=db_path, table=table)
