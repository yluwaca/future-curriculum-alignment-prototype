"""
Schemas for vector repository and semantic search APIs.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


MODEL_CONFIG = ConfigDict(protected_namespaces=())


class VectorRepositoryStatusResponse(BaseModel):
    default_model: Dict[str, Any]
    sentence_transformers_available: bool
    active_embedding: str
    pgvector_available: bool
    pgvector_installed: bool
    pgvector_column_present: bool
    active_storage_backend: str
    readiness_status: str = 'not_ready'
    issues: List[str] = Field(default_factory=list)
    required_actions: List[str] = Field(default_factory=list)


class CurriculumIndexRequest(BaseModel):
    version_id: Optional[UUID] = None
    limit: int = Field(default=1000, ge=1, le=10000)


class CurriculumIndexResponse(BaseModel):
    model_key: str
    version_id: Optional[str]
    chunks_seen: int
    embeddings_indexed: int
    embeddings_skipped: int

    model_config = MODEL_CONFIG


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=10, ge=1, le=50)
    source_entity_type: str = "document_chunk"
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)


class SemanticSearchResult(BaseModel):
    score: float
    embedding_id: str
    source_entity_type: str
    source_entity_id: str
    chunk_id: str
    version_id: str
    chunk_index: int
    page_start: Optional[int]
    page_end: Optional[int]
    token_count: int
    content_preview: str


class SemanticSearchResponse(BaseModel):
    query_id: str
    model_key: str
    result_count: int
    results: List[SemanticSearchResult]

    model_config = MODEL_CONFIG
