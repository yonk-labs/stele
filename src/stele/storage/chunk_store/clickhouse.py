"""ClickHouse chunk store — chunkshop 0.4.3 clickhouse vector sink."""

from __future__ import annotations

from typing import Literal

from stele.core.config import IndexingConfig
from stele.storage.chunk_store._chunkshop_base import ChunkshopChunkStore


class ClickHouseChunkStore(ChunkshopChunkStore):
    name: Literal["clickhouse"] = "clickhouse"
    _target_type: Literal["clickhouse"] = "clickhouse"

    def __init__(
        self, config: IndexingConfig, *, dsn: str, table: str = "chunks"
    ) -> None:
        super().__init__(config, dsn=dsn, table=table)
