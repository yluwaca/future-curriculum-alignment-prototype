"""
Vector repository and semantic search service.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.models.embedding_model import EmbeddingModel
from app.models.semantic_search_query import SemanticSearchQuery
from app.models.vector_embedding import VectorEmbedding


from pgvector.sqlalchemy import Vector as PgVectorType
from sentence_transformers import SentenceTransformer as SentenceTransformerCls

logger = logging.getLogger(__name__)


class PgvectorNotReadyError(RuntimeError):
    """Raised when native pgvector storage/search is required but unavailable."""


DEFAULT_MODEL_KEY = "sentence_all-mpnet-base-v2_768_v1"
DEFAULT_DIMENSIONS = 768
SENTENCE_MODEL_KEY = "sentence_all-mpnet-base-v2_768_v1"
SENTENCE_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"

_SENTENCE_TRANSFORMER_MODEL = None


def text_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def tokenise(content: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9]+", content.lower())


def local_hash_embedding(content: str, dimensions: int = DEFAULT_DIMENSIONS) -> List[float]:
    """
    Deterministic embedding using signed hashing over tokens.
    """
    vector = [0.0] * dimensions
    tokens = tokenise(content)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 8) for value in vector]


def _get_sentence_model():
    global _SENTENCE_TRANSFORMER_MODEL
    if _SENTENCE_TRANSFORMER_MODEL is None:
        logger.info("[EMBED] Loading sentence-transformer model: %s", SENTENCE_MODEL_NAME)
        _SENTENCE_TRANSFORMER_MODEL = SentenceTransformerCls(SENTENCE_MODEL_NAME)
        logger.info("[EMBED] Sentence-transformer model loaded successfully")
    return _SENTENCE_TRANSFORMER_MODEL


def sentence_embed(content: str) -> List[float]:
    model = _get_sentence_model()
    emb = model.encode(content, normalize_embeddings=True)
    return [round(float(v), 8) for v in emb]


def compute_embedding(content: str, model_key: str = DEFAULT_MODEL_KEY, dimensions: int = DEFAULT_DIMENSIONS) -> List[float]:
    return sentence_embed(content)


def cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))

    if left_norm == 0 or right_norm == 0:
        return 0.0

    return dot / (left_norm * right_norm)


class SemanticVectorService:
    """
    Embedding indexing and semantic search over vector-ready repositories.
    """

    def get_default_model(self, db: Session) -> EmbeddingModel:
        model = (
            db.query(EmbeddingModel)
            .filter(
                EmbeddingModel.model_key == SENTENCE_MODEL_KEY,
                EmbeddingModel.status == "active",
            )
            .first()
        )

        if model:
            return model

        model = EmbeddingModel(
            model_key=SENTENCE_MODEL_KEY,
            provider="sentence-transformers",
            model_name=SENTENCE_MODEL_NAME,
            model_version="1",
            dimensions=DEFAULT_DIMENSIONS,
            distance_metric="cosine",
            status="active",
            is_default=True,
            pgvector_enabled=self.pgvector_installed(db),
            description="Sentence-transformer all-mpnet-base-v2 embeddings (768-dim).",
            model_metadata={"purpose": "semantic", "requires_external_model": True},
        )
        db.add(model)
        db.flush()
        return model

    def get_sentence_model(self, db: Session) -> Optional[EmbeddingModel]:
        model = (
            db.query(EmbeddingModel)
            .filter(
                EmbeddingModel.model_key == SENTENCE_MODEL_KEY,
                EmbeddingModel.status == "active",
            )
            .first()
        )
        if model:
            return model
        return self.get_default_model(db)

    def pgvector_available(self, db: Session) -> bool:
        return bool(
            db.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = :name)"
                ),
                {"name": "vector"},
            ).scalar()
        )

    def pgvector_installed(self, db: Session) -> bool:
        return bool(
            db.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = :name)"),
                {"name": "vector"},
            ).scalar()
        )

    def vector_column_present(self, db: Session) -> bool:
        return bool(
            db.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'vector_embedding'
                          AND column_name = 'embedding_vector'
                    )
                    """
                )
            ).scalar()
        )

    def status(self, db: Session) -> Dict[str, Any]:
        model = self.get_default_model(db)
        pgvector_available = self.pgvector_available(db)
        pgvector_installed = self.pgvector_installed(db)
        pgvector_column_present = self.vector_column_present(db)
        ready = pgvector_installed and pgvector_column_present
        issues = []
        if not pgvector_available:
            issues.append("PostgreSQL server does not provide the pgvector extension.")
        elif not pgvector_installed:
            issues.append("pgvector extension is available but not enabled in this database.")
        if not pgvector_column_present:
            issues.append("vector_embedding.embedding_vector column is missing.")
        return {
            "default_model": {
                "model_id": str(model.model_id),
                "model_key": model.model_key,
                "provider": model.provider,
                "dimensions": model.dimensions,
                "distance_metric": model.distance_metric,
            },
            "sentence_transformers_available": True,
            "active_embedding": "sentence-transformers",
            "pgvector_available": pgvector_available,
            "pgvector_installed": pgvector_installed,
            "pgvector_column_present": pgvector_column_present,
            "active_storage_backend": "pgvector" if ready else "not_ready",
            "readiness_status": "ready" if ready else "not_ready",
            "issues": issues,
            "required_actions": [] if ready else [
                "Install/use PostgreSQL with pgvector support.",
                "Run CREATE EXTENSION vector through Alembic migration.",
                "Ensure vector_embedding.embedding_vector vector(768) and cosine index exist.",
                "Re-index curriculum embeddings after enabling pgvector.",
            ],
        }

    def require_pgvector_ready(self, db: Session) -> None:
        status = self.status(db)
        if status["readiness_status"] != "ready":
            raise PgvectorNotReadyError("; ".join(status["issues"] or status["required_actions"]))

    def index_curriculum_chunks(
        self,
        db: Session,
        version_id: Optional[UUID] = None,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        self.require_pgvector_ready(db)
        model = self.get_default_model(db)
        use_pgvector = True
        query = db.query(DocumentChunk)

        if version_id:
            query = query.filter(DocumentChunk.version_id == version_id)

        chunks = (
            query
            .order_by(DocumentChunk.created_at.asc(), DocumentChunk.chunk_index.asc())
            .limit(limit)
            .all()
        )

        indexed = 0
        skipped = 0

        for chunk in chunks:
            existing = (
                db.query(VectorEmbedding)
                .filter(
                    VectorEmbedding.source_entity_type == "document_chunk",
                    VectorEmbedding.source_entity_id == chunk.chunk_id,
                    VectorEmbedding.model_id == model.model_id,
                )
                .first()
            )

            source_hash = text_hash(chunk.content)
            embedding = compute_embedding(chunk.content, model.model_key)

            if existing and existing.source_text_hash == source_hash:
                if not use_pgvector or existing.embedding_vector is not None:
                    skipped += 1
                    continue

            if existing:
                existing.source_text_hash = source_hash
                existing.embedding = embedding
                existing.embedding_text = self.embedding_to_text(embedding)
                existing.dimensions = model.dimensions
                existing.storage_backend = "pgvector+jsonb" if use_pgvector else "jsonb"
                if use_pgvector:
                    existing.embedding_vector = embedding
                existing.embedding_metadata = {
                    "version_id": str(chunk.version_id),
                    "chunk_index": chunk.chunk_index,
                    "token_count": chunk.token_count,
                }
            else:
                kwargs = dict(
                    model_id=model.model_id,
                    source_entity_type="document_chunk",
                    source_entity_id=chunk.chunk_id,
                    source_text_hash=source_hash,
                    dimensions=model.dimensions,
                    embedding=embedding,
                    embedding_text=self.embedding_to_text(embedding),
                    storage_backend="pgvector+jsonb" if use_pgvector else "jsonb",
                    embedding_metadata={
                        "version_id": str(chunk.version_id),
                        "chunk_index": chunk.chunk_index,
                        "token_count": chunk.token_count,
                    },
                )
                if use_pgvector:
                    kwargs["embedding_vector"] = embedding
                db.add(VectorEmbedding(**kwargs))
            indexed += 1

        db.commit()

        return {
            "model_key": model.model_key,
            "version_id": str(version_id) if version_id else None,
            "chunks_seen": len(chunks),
            "embeddings_indexed": indexed,
            "embeddings_skipped": skipped,
        }

    def semantic_search(
        self,
        db: Session,
        query_text: str,
        actor_id: Optional[str],
        top_k: int = 10,
        source_entity_type: str = "document_chunk",
        min_score: float = 0.0,
    ) -> Dict[str, Any]:
        model = self.get_default_model(db)
        query_embedding = compute_embedding(query_text, model.model_key)

        self.require_pgvector_ready(db)

        vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
        sql = text("""
            SELECT ve.embedding_id, ve.source_entity_type, ve.source_entity_id,
                   ve.embedding, ve.embedding_metadata,
                   dc.chunk_id, dc.version_id, dc.chunk_index,
                   dc.page_start, dc.page_end, dc.token_count, dc.content,
                   1 - (ve.embedding_vector <=> CAST(:query_vec AS vector)) AS score
            FROM vector_embedding ve
            JOIN document_chunk dc ON ve.source_entity_id = dc.chunk_id
            WHERE ve.model_id = CAST(:model_id AS uuid)
              AND ve.source_entity_type = :entity_type
              AND ve.embedding_vector IS NOT NULL
            ORDER BY ve.embedding_vector <=> CAST(:query_vec AS vector)
            LIMIT :limit
        """)
        rows = db.execute(sql, {
            "query_vec": vec_str,
            "model_id": str(model.model_id),
            "entity_type": source_entity_type,
            "limit": top_k * 2,
        }).fetchall()

        ranked = []
        for row in rows:
            score = float(row.score)
            if score < min_score:
                continue
            ranked.append({
                "score": round(score, 6),
                "embedding_id": str(row.embedding_id),
                "source_entity_type": row.source_entity_type,
                "source_entity_id": str(row.source_entity_id),
                "chunk_id": str(row.chunk_id),
                "version_id": str(row.version_id),
                "chunk_index": row.chunk_index,
                "page_start": row.page_start,
                "page_end": row.page_end,
                "token_count": row.token_count,
                "content_preview": row.content[:500],
            })
        ranked.sort(key=lambda item: item["score"], reverse=True)
        results = ranked[:top_k]
        storage = "pgvector"

        query_log = SemanticSearchQuery(
            actor_id=actor_id,
            model_id=model.model_id,
            query_text=query_text,
            query_embedding=query_embedding,
            source_entity_type=source_entity_type,
            result_count=len(results),
            top_k=top_k,
            results=results,
            search_metadata={
                "min_score": min_score,
                "candidate_count": len(ranked) + len(results),
                "storage_backend": storage,
            },
        )
        db.add(query_log)
        db.commit()
        db.refresh(query_log)

        return {
            "query_id": str(query_log.query_id),
            "model_key": model.model_key,
            "results": results,
            "result_count": len(results),
        }

    @staticmethod
    def embedding_to_text(embedding: Optional[List[float]]) -> str:
        if not embedding:
            return "[]"
        return "[" + ",".join(str(value) for value in embedding) + "]"


semantic_vector_service = SemanticVectorService()
