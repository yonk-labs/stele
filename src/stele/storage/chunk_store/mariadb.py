"""MariaDB chunk store — chunkshop 0.4.3 mariadb VECTOR sink."""

from __future__ import annotations

from typing import Literal

from stele.core.config import IndexingConfig
from stele.storage.chunk_store._chunkshop_base import ChunkshopChunkStore


class MariaDBChunkStore(ChunkshopChunkStore):
    name: Literal["mariadb"] = "mariadb"
    _target_type: Literal["mariadb"] = "mariadb"

    def __init__(
        self, config: IndexingConfig, *, dsn: str, table: str = "chunks"
    ) -> None:
        super().__init__(config, dsn=dsn, table=table)
