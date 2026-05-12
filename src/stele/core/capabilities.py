"""Runtime capability models."""

from pydantic import BaseModel


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

