"""
Vector enrichment service.

Computes embeddings for ESCO taxonomy (skills + occupations) and matches
arbitrary text against them via cosine similarity. Supports enriching
job postings, curriculum documents, and any other source with ESCO links.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.esco_skill import ESCOSkill
from app.models.esco_occupation import ESCOOccupation, ESCOOccupationSkillLink
from app.models.skill import Skill
from app.models.skill_alias import SkillAlias
from app.models.job_posting import JobPosting
from app.services.semantic_vector_service import (
    compute_embedding,
    cosine_similarity,
    text_hash,
    _get_sentence_model,
    SENTENCE_MODEL_KEY,
    SENTENCE_MODEL_NAME,
    DEFAULT_DIMENSIONS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory ESCO index (singleton)
# ---------------------------------------------------------------------------

_ESCO_INDEX: Optional[Dict[str, Any]] = None
_ESCO_INDEX_BUILT_AT: Optional[float] = None
_ESCO_INDEX_TTL = 86400  # rebuild after 24 hours
_ESCO_INDEX_BUILDING = False


def _invalidate_esco_index():
    """Force rebuild of the ESCO index on next access."""
    global _ESCO_INDEX, _ESCO_INDEX_BUILT_AT
    _ESCO_INDEX = None
    _ESCO_INDEX_BUILT_AT = None


class VectorEnrichmentService:
    """
    Embeds ESCO skills and occupations, then matches arbitrary text
    against them using cosine similarity.
    """

    # ------------------------------------------------------------------
    # ESCO index building
    # ------------------------------------------------------------------

    def build_esco_index(self, db: Session, force: bool = False) -> Dict[str, Any]:
        """Build or retrieve the in-memory ESCO embedding index.

        Loads all ESCO skills and occupations, computes their embeddings,
        and caches them in memory for fast similarity search.

        Returns a dict with:
          - skills: list of {esco_skill_id, skill_id, preferred_label, embedding, description}
          - occupations: list of {esco_occupation_id, preferred_label, embedding, description, code}
          - skill_count, occupation_count, build_time_s
        """
        global _ESCO_INDEX, _ESCO_INDEX_BUILT_AT

        now = time.time()
        if (
            not force
            and _ESCO_INDEX is not None
            and _ESCO_INDEX_BUILT_AT is not None
            and (now - _ESCO_INDEX_BUILT_AT) < _ESCO_INDEX_TTL
        ):
            logger.info("[ENRICH] Using cached ESCO index (%d skills, %d occupations)",
                        _ESCO_INDEX["skill_count"], _ESCO_INDEX["occupation_count"])
            return _ESCO_INDEX

        global _ESCO_INDEX_BUILDING
        if _ESCO_INDEX_BUILDING:
            logger.info("[ENRICH] Index build already in progress, waiting...")
            # Wait for existing build to complete
            for _ in range(300):
                time.sleep(2)
                if not _ESCO_INDEX_BUILDING and _ESCO_INDEX is not None:
                    return _ESCO_INDEX
            logger.warning("[ENRICH] Timed out waiting for index build")

        _ESCO_INDEX_BUILDING = True

        logger.info("[ENRICH] Building ESCO embedding index...")
        t0 = time.time()

        # Load ESCO skills with their canonical skill data
        esco_skills = (
            db.query(ESCOSkill)
            .filter(ESCOSkill.preferred_label.isnot(None))
            .all()
        )
        logger.info("[ENRICH] Loaded %d ESCO skills from DB", len(esco_skills))

        # Load ESCO occupations
        esco_occs = (
            db.query(ESCOOccupation)
            .filter(ESCOOccupation.preferred_label.isnot(None))
            .all()
        )
        logger.info("[ENRICH] Loaded %d ESCO occupations from DB", len(esco_occs))

        # Pre-load canonical skill ID mapping + category
        skill_id_map: Dict[UUID, UUID] = {}  # esco_skill_id -> skill_id
        skill_category_map: Dict[UUID, str] = {}  # skill_id -> category
        for es in esco_skills:
            if es.skill_id:
                skill_id_map[es.esco_skill_id] = es.skill_id

        # Batch-load all canonical skills for category
        all_skills = db.query(Skill).filter(Skill.skill_id.isnot(None)).all()
        for s in all_skills:
            skill_category_map[s.skill_id] = s.category or ""
        logger.info("[ENRICH] Loaded %d canonical skills for categories", len(all_skills))

        # Build skill embeddings - use short text for fast embedding
        skill_entries = []
        batch_texts = []
        batch_indices = []

        for idx, es in enumerate(esco_skills):
            label = es.preferred_label or ""
            cat = ""
            # Get category from pre-loaded map
            sid = skill_id_map.get(es.esco_skill_id)
            if sid:
                cat = skill_category_map.get(sid, "")

            # Short text: just label + category for fast embedding
            text_repr = f"{label} [{cat}]" if cat else label
            batch_texts.append(text_repr)
            batch_indices.append(idx)
            skill_entries.append({
                "esco_skill_id": es.esco_skill_id,
                "skill_id": skill_id_map.get(es.esco_skill_id),
                "preferred_label": label,
                "skill_type": es.skill_type or "",
                "reuse_level": es.reuse_level or "",
                "description": es.description[:500] if es.description else "",
                "text_repr": text_repr,
            })

        # Embed skills in batches - large batch for speed
        logger.info("[ENRICH] Embedding %d ESCO skills...", len(batch_texts))
        if batch_texts:
            model = _get_sentence_model()
            embeddings = model.encode(batch_texts, normalize_embeddings=True, batch_size=512, show_progress_bar=False)
            for i, idx in enumerate(batch_indices):
                skill_entries[idx]["embedding"] = [round(float(v), 8) for v in embeddings[i]]

        # Build occupation embeddings - short text
        occ_entries = []
        occ_texts = []
        occ_indices = []

        for idx, occ in enumerate(esco_occs):
            label = occ.preferred_label or ""
            code = occ.code or ""
            text_repr = f"{label} [ISCO {code}]" if code else label
            occ_texts.append(text_repr)
            occ_indices.append(idx)
            occ_entries.append({
                "esco_occupation_id": occ.esco_occupation_id,
                "preferred_label": label,
                "code": code,
                "description": occ.description[:500] if occ.description else "",
                "text_repr": text_repr,
            })

        logger.info("[ENRICH] Embedding %d ESCO occupations...", len(occ_texts))
        if occ_texts:
            model = _get_sentence_model()
            embeddings = model.encode(occ_texts, normalize_embeddings=True, batch_size=512, show_progress_bar=False)
            for i, idx in enumerate(occ_indices):
                occ_entries[idx]["embedding"] = [round(float(v), 8) for v in embeddings[i]]

        # Build occupation -> skill links map
        occ_skill_links: Dict[UUID, List[UUID]] = defaultdict(list)
        links = db.query(ESCOOccupationSkillLink).all()
        for link in links:
            occ_skill_links[link.occupation_id].append(link.skill_id)

        t1 = time.time()
        _ESCO_INDEX = {
            "skills": skill_entries,
            "occupations": occ_entries,
            "occ_skill_links": {str(k): v for k, v in occ_skill_links.items()},
            "skill_count": len(skill_entries),
            "occupation_count": len(occ_entries),
            "build_time_s": round(t1 - t0, 2),
        }
        _ESCO_INDEX_BUILT_AT = t1

        _ESCO_INDEX_BUILDING = False
        logger.info("[ENRICH] ESCO index built: %d skills, %d occupations in %.1fs",
                     len(skill_entries), len(occ_entries), t1 - t0)
        return _ESCO_INDEX

    # ------------------------------------------------------------------
    # Similarity search
    # ------------------------------------------------------------------

    def find_similar_skills(
        self,
        text: str,
        db: Session,
        top_k: int = 10,
        min_score: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """Find ESCO skills most similar to the given text.

        Returns list of {esco_skill_id, skill_id, preferred_label, score, description}.
        """
        index = self.build_esco_index(db)
        if not index["skills"]:
            return []

        query_emb = compute_embedding(text)
        results = []
        for entry in index["skills"]:
            emb = entry.get("embedding")
            if not emb:
                continue
            score = cosine_similarity(query_emb, emb)
            if score >= min_score:
                results.append({
                    "esco_skill_id": str(entry["esco_skill_id"]),
                    "skill_id": str(entry["skill_id"]) if entry.get("skill_id") else None,
                    "preferred_label": entry["preferred_label"],
                    "score": round(score, 4),
                    "description": entry.get("description", ""),
                    "skill_type": entry.get("skill_type", ""),
                    "reuse_level": entry.get("reuse_level", ""),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def find_similar_occupations(
        self,
        text: str,
        db: Session,
        top_k: int = 5,
        min_score: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """Find ESCO occupations most similar to the given text.

        Returns list of {esco_occupation_id, preferred_label, code, score, description}.
        """
        index = self.build_esco_index(db)
        if not index["occupations"]:
            return []

        query_emb = compute_embedding(text)
        results = []
        for entry in index["occupations"]:
            emb = entry.get("embedding")
            if not emb:
                continue
            score = cosine_similarity(query_emb, emb)
            if score >= min_score:
                # Find related skills for this occupation
                occ_id = entry["esco_occupation_id"]
                related_skill_ids = index["occ_skill_links"].get(str(occ_id), [])

                results.append({
                    "esco_occupation_id": str(occ_id),
                    "preferred_label": entry["preferred_label"],
                    "code": entry.get("code", ""),
                    "score": round(score, 4),
                    "description": entry.get("description", ""),
                    "related_skill_count": len(related_skill_ids),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def find_occupation_skills(
        self,
        esco_occupation_id: UUID,
        db: Session,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get ESCO skills linked to an occupation."""
        index = self.build_esco_index(db)
        skill_ids = index["occ_skill_links"].get(str(esco_occupation_id), [])
        if not skill_ids:
            return []

        skill_id_set = {str(s) for s in skill_ids}
        results = []
        for entry in index["skills"]:
            if str(entry["esco_skill_id"]) in skill_id_set:
                results.append({
                    "esco_skill_id": str(entry["esco_skill_id"]),
                    "skill_id": str(entry["skill_id"]) if entry.get("skill_id") else None,
                    "preferred_label": entry["preferred_label"],
                    "skill_type": entry.get("skill_type", ""),
                })
        return results[:top_k]

    # ------------------------------------------------------------------
    # Batch enrichment
    # ------------------------------------------------------------------

    def enrich_job_posting(
        self,
        db: Session,
        posting: JobPosting,
        top_skill_k: int = 10,
        top_occ_k: int = 3,
        min_skill_score: float = 0.35,
        min_occ_score: float = 0.35,
    ) -> Dict[str, Any]:
        """Enrich a single job posting with ESCO skill and occupation matches.

        Updates posting.required_skills with enriched ESCO matches and
        returns the enrichment result.
        """
        # Build text representation
        title = posting.job_title or ""
        desc = posting.job_description or ""
        text_repr = f"{title}"
        if desc:
            text_repr += f" | {desc[:2000]}"

        # Find matching ESCO skills
        skill_matches = self.find_similar_skills(
            text_repr, db, top_k=top_skill_k, min_score=min_skill_score
        )

        # Find matching ESCO occupations
        occ_matches = self.find_similar_occupations(
            text_repr, db, top_k=top_occ_k, min_score=min_occ_score
        )

        # Get the skills linked to the top occupation match
        occ_skills = []
        if occ_matches:
            top_occ_id = UUID(occ_matches[0]["esco_occupation_id"])
            occ_skills = self.find_occupation_skills(top_occ_id, db)

        # Merge into required_skills JSONB
        existing = posting.required_skills or {}
        if isinstance(existing, dict):
            declared = existing.get("declared", [])
        else:
            declared = []

        # Add ESCO-enriched skills (avoid duplicates with declared)
        declared_lower = {s.lower().strip() for s in declared if isinstance(s, str)}
        enriched_skills = []
        for match in skill_matches:
            label = match["preferred_label"]
            if label.lower().strip() not in declared_lower:
                enriched_skills.append({
                    "label": label,
                    "esco_skill_id": match["esco_skill_id"],
                    "skill_id": match["skill_id"],
                    "confidence": match["score"],
                    "source": "esco_vector_match",
                })

        # Update the posting
        enriched_payload = {
            "declared": declared,
            "enriched": enriched_skills,
            "esco_occupations": occ_matches,
            "top_occupation_skills": [
                {"label": s["preferred_label"], "esco_skill_id": s["esco_skill_id"]}
                for s in occ_skills[:20]
            ],
            "enrichment_metadata": {
                "model": "sentence-transformers/all-mpnet-base-v2",
                "skill_matches": len(skill_matches),
                "occupation_matches": len(occ_matches),
                "enriched_at": time.time(),
            },
        }

        posting.required_skills = enriched_payload
        posting.embedding_generated = True
        posting.last_processed_at = time.time()

        return {
            "posting_id": str(posting.posting_id),
            "job_title": title,
            "skill_matches": skill_matches,
            "occupation_matches": occ_matches,
            "enriched_skill_count": len(enriched_skills),
            "total_skills": len(declared) + len(enriched_skills),
        }

    def enrich_job_postings_batch(
        self,
        db: Session,
        limit: int = 500,
        top_skill_k: int = 10,
        top_occ_k: int = 3,
        min_skill_score: float = 0.35,
        min_occ_score: float = 0.35,
    ) -> Dict[str, Any]:
        """Enrich a batch of unprocessed job postings.

        Finds job postings where embedding_generated=False or is_processed=False,
        enriches them with ESCO matches, and returns summary stats.
        """
        logger.info("[ENRICH] Starting batch enrichment for up to %d job postings", limit)

        postings = (
            db.query(JobPosting)
            .filter(
                (JobPosting.embedding_generated == False)  # noqa: E712
                | (JobPosting.is_processed == False)  # noqa: E712
            )
            .order_by(JobPosting.created_at.desc())
            .limit(limit)
            .all()
        )

        logger.info("[ENRICH] Found %d unprocessed job postings", len(postings))

        # Ensure ESCO index is built
        index = self.build_esco_index(db)

        enriched = 0
        errors = 0
        total_skill_matches = 0
        total_occ_matches = 0
        results = []

        for posting in postings:
            try:
                result = self.enrich_job_posting(
                    db, posting,
                    top_skill_k=top_skill_k,
                    top_occ_k=top_occ_k,
                    min_skill_score=min_skill_score,
                    min_occ_score=min_occ_score,
                )
                posting.is_processed = True
                enriched += 1
                total_skill_matches += result["enriched_skill_count"]
                total_occ_matches += len(result["occupation_matches"])
                results.append(result)
            except Exception as e:
                logger.error("[ENRICH] Error enriching posting %s: %s", posting.posting_id, e)
                errors += 1

        # Commit all changes
        db.flush()

        return {
            "enriched": enriched,
            "errors": errors,
            "total_skill_matches": total_skill_matches,
            "total_occupation_matches": total_occ_matches,
            "esco_index": {
                "skills": index["skill_count"],
                "occupations": index["occupation_count"],
                "build_time_s": index["build_time_s"],
            },
            "sample_results": results[:5],
        }

    # ------------------------------------------------------------------
    # Text enrichment (non-job-posting)
    # ------------------------------------------------------------------

    def enrich_text(
        self,
        text_content: str,
        db: Session,
        top_skill_k: int = 10,
        top_occ_k: int = 5,
        min_score: float = 0.3,
    ) -> Dict[str, Any]:
        """Enrich arbitrary text with ESCO skill and occupation matches.

        Useful for curriculum documents, job descriptions without structured
        records, or any free-form text.
        """
        skill_matches = self.find_similar_skills(
            text_content, db, top_k=top_skill_k, min_score=min_score
        )
        occ_matches = self.find_similar_occupations(
            text_content, db, top_k=top_occ_k, min_score=min_score
        )

        return {
            "text_preview": text_content[:200],
            "skill_matches": skill_matches,
            "occupation_matches": occ_matches,
        }


# Module-level singleton
vector_enrichment_service = VectorEnrichmentService()
