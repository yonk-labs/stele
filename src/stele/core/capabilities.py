"""Runtime capability models."""

from typing import Literal

from pydantic import BaseModel

from stele.indexing.bakeoff import BakeoffSummary


class StorageCapabilities(BaseModel):
    backend_type: str
    durable: bool
    ttl_cleanup: bool = True
    hard_delete: bool = True
    bytes_supported: bool = True


class RetrievalCapabilities(BaseModel):
    backend_type: str
    keyword: bool = False
    vector: bool = False
    hybrid: bool = False
    graph: bool = False
    default_mode: str = "keyword"


class StashCapabilities(BaseModel):
    storage: StorageCapabilities
    retrieval: RetrievalCapabilities
    chunk_store_backend: (
        Literal["memory", "sqlite", "postgres", "mariadb", "clickhouse"] | None
    ) = None
    vector_enabled: bool = False
    hybrid_enabled: bool = False
    chunkshop_installed: bool = False
    chunkshop_version: str | None = None
    bakeoff_summary: BakeoffSummary | None = None
    task_backend: str | None = None
    graph_enabled: bool = False
    living_knowledge: bool = False
    pg_raggraph_installed: bool = False
    pg_raggraph_version: str | None = None

