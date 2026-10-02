"""
Skills and ESCO harmonisation service.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from collections import defaultdict
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from app.models.document_chunk import DocumentChunk
from app.models.esco_occupation import ESCOOccupation, ESCOOccupationSkillLink
from app.models.esco_skill import ESCOSkill
from app.models.extracted_table_row import ExtractedTableRow
from app.models.labour_market_indicator import LabourMarketIndicator
from app.models.labour_market_observation import LabourMarketObservation
from app.models.labour_market_signal import LabourMarketSignal
from app.models.skill import Skill
from app.models.skill_alias import SkillAlias
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.skill_mapping import SkillMapping
from app.models.skill_mapping_review_event import SkillMappingReviewEvent
from app.services.semantic_vector_service import (cosine_similarity, compute_embedding, local_hash_embedding)
from app.services.audit_service import log_audit_event
from app.services.structured_log import log_structured

logger = logging.getLogger(__name__)


def normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SkillHarmonisationService:
    """
    Extracts skill evidence and maps it to canonical skills/ESCO records.
    """

    NOISY_JOB_SKILL_TERMS = {
        "ability",
        "attention",
        "attitude",
        "career",
        "commitment",
        "company",
        "confidence",
        "deadline",
        "depth perception",
        "detail",
        "drivers license",
        "employment equity",
        "energetic",
        "excellent",
        "flexibility",
        "hard working",
        "honesty",
        "interpersonal",
        "license",
        "matric",
        "must be able",
        "own transport",
        "peripheral vision",
        "personality",
        "physical ability",
        "punctual",
        "reliable",
        "resiliency",
        "self motivated",
        "smart specific measurable",
        "team player",
        "valid drivers",
        "vision",
        "willingness",
    }
    NOISY_JOB_SKILL_PATTERNS = [
        re.compile(r"^\d+$"),
        re.compile(r"^[a-z]\d+$", re.IGNORECASE),
        re.compile(r"\b(please|apply|candidate|applicant|salary|benefit|shift|overtime)\b", re.IGNORECASE),
        re.compile(r"\b(ability to|must have|must be|will be|responsible for|duties include)\b", re.IGNORECASE),
        re.compile(r"\b(years? experience|experience in|previous experience)\b", re.IGNORECASE),
        re.compile(r"\b(hospital|clinic|retail store|restaurant|warehouse)\b", re.IGNORECASE),
    ]
    STRONG_TECHNICAL_TERMS = {
        "api",
        "aws",
        "azure",
        "business intelligence",
        "c#",
        "cloud",
        "cybersecurity",
        "data analysis",
        "database",
        "docker",
        "etl",
        "excel",
        "git",
        "java",
        "javascript",
        "machine learning",
        "network",
        "power bi",
        "python",
        "sql",
        "statistics",
    }

    def list_skills(self, db: Session, limit: int = 500) -> List[Skill]:
        return (
            db.query(Skill)
            .order_by(Skill.name.asc())
            .limit(min(max(limit, 1), 5000))
            .all()
        )

    def list_aliases(
        self,
        db: Session,
        skill_id: Optional[UUID] = None,
        active_only: bool = False,
        limit: int = 500,
    ) -> List[SkillAlias]:
        query = db.query(SkillAlias)
        if skill_id:
            query = query.filter(SkillAlias.skill_id == skill_id)
        if active_only:
            query = query.filter(SkillAlias.is_active.is_(True))
        return query.order_by(SkillAlias.alias.asc()).limit(min(max(limit, 1), 2000)).all()

    def summary(self, db: Session) -> Dict[str, Any]:
        return {
            "skills": db.query(func.count(Skill.skill_id)).scalar() or 0,
            "esco_skills": db.query(func.count(ESCOSkill.esco_skill_id)).scalar() or 0,
            "aliases": db.query(func.count(SkillAlias.alias_id)).scalar() or 0,
            "mappings": db.query(func.count(SkillMapping.mapping_id)).scalar() or 0,
            "curriculum_mappings": (
                db.query(func.count(SkillMapping.mapping_id))
                .filter(SkillMapping.source_domain == "curriculum")
                .scalar()
                or 0
            ),
            "labour_market_mappings": (
                db.query(func.count(SkillMapping.mapping_id))
                .filter(SkillMapping.source_domain == "labour_market")
                .scalar()
                or 0
            ),
            "skill_demand_evidence": (
                db.query(func.count(SkillDemandEvidence.evidence_id)).scalar() or 0
            ),
            "candidate_mappings": (
                db.query(func.count(SkillMapping.mapping_id))
                .filter(SkillMapping.mapping_status == "candidate")
                .scalar()
                or 0
            ),
            "approved_mappings": (
                db.query(func.count(SkillMapping.mapping_id))
                .filter(SkillMapping.mapping_status == "approved")
                .scalar()
                or 0
            ),
            "rejected_mappings": (
                db.query(func.count(SkillMapping.mapping_id))
                .filter(SkillMapping.mapping_status == "rejected")
                .scalar()
                or 0
            ),
        }

    def esco_crosswalk(self, db: Session, version_id: Optional[UUID] = None) -> Dict[str, Any]:
        """Build a crosswalk between curriculum skills and ESCO taxonomy."""
        from collections import Counter

        query = (
            db.query(
                SkillMapping.skill_id,
                Skill.skill_key,
                Skill.name,
                SkillMapping.esco_skill_id,
                SkillMapping.mapping_metadata,
            )
            .join(Skill, SkillMapping.skill_id == Skill.skill_id)
            .filter(
                SkillMapping.source_domain == "curriculum",
                SkillMapping.source_entity_type == "document_chunk",
                SkillMapping.mapping_status.in_(["candidate", "approved"]),
            )
        )
        if version_id:
            query = query.filter(
                SkillMapping.mapping_metadata["version_id"].astext == str(version_id)
            )

        rows = query.all()
        seen: Dict[str, Dict[str, Any]] = {}
        esco_counter: Counter = Counter()
        module_by_skill: Dict[str, set] = {}

        for skill_id, skill_key, name, esco_skill_id, meta in rows:
            key = str(skill_id)
            if key not in seen:
                seen[key] = {
                    "skill_id": skill_id,
                    "skill_key": skill_key,
                    "skill_name": name,
                    "esco_skill_id": esco_skill_id,
                }
                module_by_skill[key] = set()
            module_code = (meta or {}).get("module_code") or (meta or {}).get("section")
            if module_code:
                module_by_skill[key].add(str(module_code)[:80])

        esco_labels: Dict[str, str] = {}
        esco_uris: Dict[str, str] = {}
        if seen:
            esco_ids = [
                item["esco_skill_id"] for item in seen.values() if item["esco_skill_id"]
            ]
            if esco_ids:
                for esco in (
                    db.query(ESCOSkill).filter(ESCOSkill.esco_skill_id.in_(esco_ids)).all()
                ):
                    eid = str(esco.esco_skill_id)
                    esco_labels[eid] = esco.preferred_label
                    esco_uris[eid] = esco.esco_uri or ""
                    esco_counter[eid] += 1

        items = []
        for key, item in seen.items():
            eid = str(item["esco_skill_id"]) if item["esco_skill_id"] else None
            items.append(
                {
                    "skill_id": item["skill_id"],
                    "skill_key": item["skill_key"],
                    "skill_name": item["skill_name"],
                    "esco_skill_id": item["esco_skill_id"],
                    "esco_preferred_label": esco_labels.get(eid) if eid else None,
                    "esco_uri": esco_uris.get(eid) if eid else None,
                    "curriculum_modules": sorted(module_by_skill.get(key, set())),
                    "mapping_count": sum(1 for r in rows if str(r.skill_id) == key),
                }
            )

        covered = sum(1 for i in items if i["esco_skill_id"])
        total = len(items) or 1
        top_esco = [
            {"esco_skill_id": eid, "preferred_label": esco_labels.get(eid), "count": count}
            for eid, count in esco_counter.most_common(20)
        ]
        missing_keys = [i["skill_key"] for i in items if not i["esco_skill_id"]]

        return {
            "total_curriculum_skills": len(items),
            "covered_by_esco": covered,
            "not_covered_by_esco": total - covered,
            "esco_coverage_pct": round(covered / total * 100, 1),
            "items": items,
            "top_esco_skills": top_esco,
            "missing_skill_keys": sorted(missing_keys),
        }

    def duplicate_candidates(
        self,
        db: Session,
        limit: int = 100,
        min_score: float = 0.86,
    ) -> List[Dict[str, Any]]:
        skills = db.query(Skill).filter(Skill.status == "active").order_by(Skill.name.asc()).all()
        mapping_counts = dict(
            db.query(SkillMapping.skill_id, func.count(SkillMapping.mapping_id))
            .group_by(SkillMapping.skill_id)
            .all()
        )
        alias_rows = (
            db.query(SkillAlias.skill_id, SkillAlias.normalised_alias)
            .filter(SkillAlias.is_active.is_(True))
            .all()
        )
        aliases_by_skill: Dict[Any, set[str]] = {}
        for skill_id, alias in alias_rows:
            aliases_by_skill.setdefault(skill_id, set()).add(alias)

        normalised = {
            skill.skill_id: self.canonical_duplicate_key(skill.name)
            for skill in skills
        }
        buckets: Dict[str, List[Skill]] = defaultdict(list)
        for skill in skills:
            key = normalised[skill.skill_id]
            if not key:
                continue
            buckets[f"name:{key}"].append(skill)
            compact = key.replace(" ", "")
            if compact != key and compact:
                buckets[f"compact:{compact}"].append(skill)
        alias_to_skills: Dict[str, List[Skill]] = defaultdict(list)
        skill_by_id = {skill.skill_id: skill for skill in skills}
        for skill_id, aliases in aliases_by_skill.items():
            skill = skill_by_id.get(skill_id)
            if not skill:
                continue
            for alias in aliases:
                alias_to_skills[f"alias:{alias}"].append(skill)
        for alias_key, alias_skills in alias_to_skills.items():
            if 1 < len(alias_skills) <= 25:
                buckets[alias_key].extend(alias_skills)

        candidates: List[Dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            if len(bucket) > 100:
                continue
            for index, left in enumerate(bucket):
                left_id = str(left.skill_id)
                left_key = normalised[left.skill_id]
                for right in bucket[index + 1:]:
                    right_id = str(right.skill_id)
                    pair_key = tuple(sorted((left_id, right_id)))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    right_key = normalised[right.skill_id]
                    if not left_key or not right_key:
                        continue
                    score, reasons = self.duplicate_score(
                        left=left,
                        right=right,
                        left_key=left_key,
                        right_key=right_key,
                        left_aliases=aliases_by_skill.get(left.skill_id, set()),
                        right_aliases=aliases_by_skill.get(right.skill_id, set()),
                    )
                    if score < min_score:
                        continue
                    target, source = self.preferred_merge_direction(
                        left,
                        right,
                        mapping_counts.get(left.skill_id, 0),
                        mapping_counts.get(right.skill_id, 0),
                    )
                    candidates.append(
                        {
                            "source_skill_id": source.skill_id,
                            "source_skill_key": source.skill_key,
                            "source_name": source.name,
                            "target_skill_id": target.skill_id,
                            "target_skill_key": target.skill_key,
                            "target_name": target.name,
                            "score": round(score, 4),
                            "reasons": reasons,
                            "source_mapping_count": int(mapping_counts.get(source.skill_id, 0) or 0),
                            "target_mapping_count": int(mapping_counts.get(target.skill_id, 0) or 0),
                            "recommendation": "merge_candidate",
                        }
                    )

        return sorted(
            candidates,
            key=lambda item: (item["score"], item["source_mapping_count"] + item["target_mapping_count"]),
            reverse=True,
        )[: min(max(limit, 1), 1000)]

    def merge_duplicate_candidate(
        self,
        db: Session,
        source_skill_id: UUID,
        target_skill_id: UUID,
        actor_id: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.merge_skills(
            db=db,
            source_skill_id=source_skill_id,
            target_skill_id=target_skill_id,
            actor_id=actor_id,
            note=note or "Merged from duplicate skill candidate review.",
        )

    def import_esco_records(
        self,
        db: Session,
        records: List[Dict[str, Any]],
        taxonomy_version: str = "imported",
        actor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        skills_created = 0
        esco_created = 0
        esco_updated = 0
        aliases_created = 0

        for row in records:
            label = self.first_value(row, "preferredLabel", "preferred_label", "preferredLabel_en", "label", "title")
            if not label:
                continue
            esco_uri = self.first_value(row, "conceptUri", "concept_uri", "uri", "esco_uri")
            description = self.first_value(row, "description", "description_en", "scopeNote", "definition")
            skill_type = self.first_value(row, "skillType", "skill_type", "type")
            reuse_level = self.first_value(row, "reuseLevel", "reuse_level")
            broader_uri = self.first_value(row, "broaderConceptUri", "broader_concept_uri", "broaderConcept", "broader_concept")
            skill_key = slugify_skill(label)

            skill = db.query(Skill).filter(Skill.skill_key == skill_key).first()
            if not skill:
                skill = Skill(
                    skill_key=skill_key,
                    name=label[:255],
                    category=skill_type or "esco",
                    description=description,
                    status="active",
                    skill_metadata={
                        "source": "esco_import",
                        "taxonomy_version": taxonomy_version,
                    },
                )
                db.add(skill)
                db.flush()
                skills_created += 1

            esco = None
            if esco_uri:
                esco = db.query(ESCOSkill).filter(ESCOSkill.esco_uri == esco_uri).first()
            if not esco:
                esco = ESCOSkill(
                    skill_id=skill.skill_id,
                    esco_uri=esco_uri,
                    preferred_label=label[:255],
                    skill_type=skill_type,
                    reuse_level=reuse_level,
                    description=description,
                    taxonomy_version=taxonomy_version,
                    broader_concept_uri=broader_uri,
                    top_concept=not bool(broader_uri),
                    esco_metadata={
                        "source": "esco_import",
                        "imported_by": actor_id,
                        "raw": row,
                    },
                )
                db.add(esco)
                esco_created += 1
            else:
                esco.skill_id = esco.skill_id or skill.skill_id
                esco.preferred_label = label[:255]
                esco.skill_type = skill_type or esco.skill_type
                esco.reuse_level = reuse_level or esco.reuse_level
                esco.description = description or esco.description
                esco.taxonomy_version = taxonomy_version
                if broader_uri:
                    esco.broader_concept_uri = broader_uri
                    esco.top_concept = False
                esco.esco_metadata = {**(esco.esco_metadata or {}), "last_import_raw": row}
                esco_updated += 1

            for alias in self.esco_aliases(row, label):
                if self.create_alias_if_missing(
                    db=db,
                    skill_id=skill.skill_id,
                    alias=alias,
                    source="esco",
                    confidence_weight=0.95 if alias == label else 0.82,
                ):
                    aliases_created += 1

        db.commit()

        self._resolve_esco_hierarchy(db, taxonomy_version)

        return {
            "records_seen": len(records),
            "skills_created": skills_created,
            "esco_created": esco_created,
            "esco_updated": esco_updated,
            "aliases_created": aliases_created,
        }

    def _resolve_esco_hierarchy(self, db: Session, taxonomy_version: str) -> int:
        """Resolve broader_concept_uri -> parent_id for all ESCO records of a version."""
        skills = db.query(ESCOSkill).filter(
            ESCOSkill.taxonomy_version == taxonomy_version,
        ).all()
        uri_map = {str(s.esco_uri): s for s in skills if s.esco_uri}
        updated = 0
        for skill in skills:
            broader = skill.broader_concept_uri or (skill.esco_metadata or {}).get("broaderConceptUri")
            if broader and broader in uri_map:
                parent = uri_map[broader]
                if parent.esco_skill_id != skill.esco_skill_id:
                    skill.parent_id = parent.esco_skill_id
                    skill.top_concept = False
                    updated += 1
            elif not broader:
                skill.top_concept = True
        db.commit()
        return updated

    def import_esco_occupations(
        self,
        db: Session,
        taxonomy_version: str = "occupation_v1",
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Fetch ESCO occupations from the EU API and persist them."""
        import httpx
        import uuid as _uuid

        occupations_created = 0
        occupations_updated = 0
        skill_links_created = 0

        seen_uris: set = set()
        occupations_data: list = []

        search_terms = [
            "data", "software", "engineer", "manager", "analyst", "technician",
            "developer", "designer", "administrator", "consultant", "specialist",
            "scientist", "operator", "director", "coordinator", "assistant",
            "officer", "supervisor", "trainer", "teacher", "health", "finance",
            "marketing", "sales", "support", "security", "research", "education",
        ]

        for term in search_terms:
            if len(occupations_data) >= limit:
                break
            try:
                resp = httpx.get(
                    "https://ec.europa.eu/esco/api/search",
                    params={"q": term, "type": "occupation", "language": "en", "limit": 20},
                    headers={"Accept": "application/json"},
                    timeout=15.0,
                )
                resp.raise_for_status()
                data = resp.json()
                for r in data.get("_embedded", {}).get("results", []):
                    uri = r.get("uri")
                    if uri and uri not in seen_uris:
                        seen_uris.add(uri)
                        occupations_data.append(r)
                        if len(occupations_data) >= limit:
                            break
            except Exception:
                continue

        for occ_data in occupations_data:
            uri = occ_data.get("uri")
            if not uri:
                continue

            existing = db.query(ESCOOccupation).filter(
                ESCOOccupation.esco_uri == uri
            ).first()

            broader = occ_data.get("broaderOccupation", [None])[0] if occ_data.get("broaderOccupation") else None
            preferred_label = occ_data.get("title") or occ_data.get("preferredLabel", {}).get("en", "Unknown")

            if existing:
                existing.preferred_label = preferred_label
                existing.code = occ_data.get("code")
                existing.broader_occupation_uri = broader
                existing.status = "released"
                existing.taxonomy_version = taxonomy_version
                occupations_updated += 1
            else:
                existing = ESCOOccupation(
                    esco_occupation_id=_uuid.uuid4(),
                    esco_uri=uri,
                    preferred_label=preferred_label,
                    code=occ_data.get("code"),
                    description=occ_data.get("description", {}).get("en", {}).get("literal") if isinstance(occ_data.get("description"), dict) else None,
                    status="released",
                    taxonomy_version=taxonomy_version,
                    broader_occupation_uri=broader,
                    top_concept=broader is None,
                    occupation_metadata={"source": "api_search", "search_term": term},
                )
                db.add(existing)
                occupations_created += 1

        db.flush()

        uri_map = {str(o.esco_uri): o.esco_occupation_id for o in db.query(ESCOOccupation).filter(ESCOOccupation.taxonomy_version == taxonomy_version).all() if o.esco_uri}

        for occ_data in occupations_data:
            uri = occ_data.get("uri")
            if not uri or uri not in uri_map:
                continue
            occ_id = uri_map[uri]
            occ_obj = db.query(ESCOOccupation).filter(ESCOOccupation.esco_occupation_id == occ_id).first()
            if occ_obj and occ_obj.broader_occupation_uri and occ_obj.broader_occupation_uri in uri_map:
                parent_id = uri_map[occ_obj.broader_occupation_uri]
                if parent_id != occ_obj.esco_occupation_id:
                    occ_obj.parent_id = parent_id
                    occ_obj.top_concept = False

        db.commit()
        return {
            "records_seen": len(occupations_data),
            "occupations_created": occupations_created,
            "occupations_updated": occupations_updated,
            "skill_links_created": skill_links_created,
        }

    def create_alias(
        self,
        db: Session,
        skill_id: UUID,
        alias: str,
        language: str = "en",
        source: str = "manual",
        confidence_weight: float = 1.0,
    ) -> SkillAlias:
        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        if not skill:
            raise ValueError("Skill not found")
        normalised = normalise_text(alias)
        existing = (
            db.query(SkillAlias)
            .filter(SkillAlias.skill_id == skill_id, SkillAlias.normalised_alias == normalised)
            .first()
        )
        if existing:
            existing.alias = alias
            existing.language = language
            existing.source = source
            existing.confidence_weight = confidence_weight
            existing.is_active = True
            db.commit()
            db.refresh(existing)
            return existing

        record = SkillAlias(
            skill_id=skill_id,
            alias=alias,
            normalised_alias=normalised,
            language=language,
            source=source,
            confidence_weight=confidence_weight,
            is_active=True,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def canonical_duplicate_key(value: str) -> str:
        text = normalise_text(value)
        replacements = {
            "&": " and ",
            "/": " ",
            "-": " ",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        tokens = [token for token in text.split() if token not in {"skills", "skill", "the", "and"}]
        joined = " ".join(tokens).strip()
        if not joined:
            return ""
        compact = joined.replace(" ", "")
        # Normalise common one-word compounds from scraped job data.
        compounds = {
            "problemsolving": "problem solving",
            "timekeeping": "time keeping",
            "decisionmaking": "decision making",
            "troubleshooting": "trouble shooting",
        }
        return compounds.get(compact, joined)

    @staticmethod
    def duplicate_score(
        left: Skill,
        right: Skill,
        left_key: str,
        right_key: str,
        left_aliases: set[str],
        right_aliases: set[str],
    ) -> tuple[float, List[str]]:
        reasons: List[str] = []
        if left_key == right_key:
            reasons.append("canonical_normalised_name_match")
            return 0.99, reasons
        compact_left = left_key.replace(" ", "")
        compact_right = right_key.replace(" ", "")
        if compact_left == compact_right:
            reasons.append("spacing_or_punctuation_variant")
            return 0.97, reasons
        if left_aliases & right_aliases:
            reasons.append("shared_alias")
            return 0.95, reasons
        ratio = SequenceMatcher(None, left_key, right_key).ratio()
        if ratio >= 0.92:
            reasons.append("high_name_similarity")
        elif ratio >= 0.86:
            reasons.append("moderate_name_similarity")
        if left.category and right.category and left.category == right.category:
            ratio += 0.02
            reasons.append("same_category")
        return min(ratio, 0.94), reasons

    @staticmethod
    def preferred_merge_direction(
        left: Skill,
        right: Skill,
        left_count: int,
        right_count: int,
    ) -> tuple[Skill, Skill]:
        if left_count != right_count:
            return (left, right) if left_count > right_count else (right, left)
        if len(left.name) != len(right.name):
            return (left, right) if len(left.name) < len(right.name) else (right, left)
        return (left, right) if left.name.lower() <= right.name.lower() else (right, left)

    def update_alias(self, db: Session, alias_id: UUID, updates: Dict[str, Any]) -> SkillAlias:
        alias = db.query(SkillAlias).filter(SkillAlias.alias_id == alias_id).first()
        if not alias:
            raise ValueError("Skill alias not found")
        if "alias" in updates and updates["alias"]:
            alias.alias = updates["alias"]
            alias.normalised_alias = normalise_text(updates["alias"])
        for field in ("language", "source", "confidence_weight", "is_active"):
            if field in updates and updates[field] is not None:
                setattr(alias, field, updates[field])
        db.commit()
        db.refresh(alias)
        return alias

    def extract_from_curriculum(
        self,
        db: Session,
        version_id: Optional[UUID] = None,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        query = db.query(DocumentChunk)
        if version_id:
            query = query.filter(DocumentChunk.version_id == version_id)

        chunks = (
            query
            .order_by(DocumentChunk.created_at.asc(), DocumentChunk.chunk_index.asc())
            .limit(limit)
            .all()
        )

        created = 0
        skipped = 0
        alias_pairs = self.active_alias_skill_pairs(db)
        alias_index = self.alias_candidate_index(alias_pairs)
        esco_by_skill = self.esco_by_skill_id(db)
        contexts_seen = 0
        contexts_skipped = 0

        for chunk in chunks:
            contexts = self.curriculum_skill_contexts(chunk)
            if not contexts:
                contexts_skipped += 1
                continue
            contexts_seen += len(contexts)

            for context in contexts:
                matches = self.extract_alias_matches_from_index(
                    context["text"],
                    alias_index=alias_index,
                    esco_by_skill=esco_by_skill,
                )
                for match in matches:
                    if self.is_generic_curriculum_skill(match["matched_text"], match["skill"].name):
                        skipped += 1
                        continue
                    confidence = round(
                        min(0.98, float(match["confidence_score"]) * context["quality_weight"]),
                        4,
                    )
                    if confidence < context["minimum_confidence"]:
                        skipped += 1
                        continue
                    source_hash = content_hash(context["text"])
                    if self.mapping_exists(
                        db=db,
                        source_domain="curriculum",
                        source_entity_type="document_chunk",
                        source_entity_id=chunk.chunk_id,
                        source_record_id=f"{chunk.chunk_id}:{context['context_index']}",
                        skill_id=match["skill"].skill_id,
                        source_text_hash=source_hash,
                        matched_text=match["matched_text"],
                    ):
                        skipped += 1
                        continue

                    db.add(
                        SkillMapping(
                            skill_id=match["skill"].skill_id,
                            esco_skill_id=match["esco_skill_id"],
                            source_domain="curriculum",
                            source_entity_type="document_chunk",
                            source_entity_id=chunk.chunk_id,
                            source_record_id=f"{chunk.chunk_id}:{context['context_index']}",
                            source_text_hash=source_hash,
                            matched_text=match["matched_text"][:255],
                            extraction_method=f"curriculum_{match['calibration']['method']}",
                            confidence_score=confidence,
                            evidence_start=match["start"],
                            evidence_end=match["end"],
                            evidence_text=context["text"][:1000],
                            mapping_status="candidate",
                            confidence_calibration={
                                **match.get("calibration", {}),
                                "curriculum_context_quality": context["quality_weight"],
                                "curriculum_context_type": context["context_type"],
                            },
                            mapping_metadata={
                                "version_id": str(chunk.version_id),
                                "chunk_index": chunk.chunk_index,
                                "page_start": chunk.page_start,
                                "module_id": str(chunk.module_id) if chunk.module_id else None,
                                "programme_id": str(chunk.programme_id) if chunk.programme_id else None,
                                "section": (chunk.chunk_metadata or {}).get("section"),
                                "outcome_type": (chunk.chunk_metadata or {}).get("outcome_type"),
                                "curriculum_evidence_type": (chunk.chunk_metadata or {}).get("curriculum_evidence_type"),
                                "context_type": context["context_type"],
                                "context_index": context["context_index"],
                                "context_quality_weight": context["quality_weight"],
                                "alias_id": str(match["alias"].alias_id) if match.get("alias") else None,
                                "semantic_similarity": match.get("semantic_similarity"),
                            },
                        )
                    )
                    created += 1

        db.commit()
        auto_review = self.auto_approve_high_confidence_mappings(
            db=db,
            source_domain="curriculum",
            min_confidence=0.90,
            note="Auto-approved high-confidence curriculum evidence mappings after generation; uncertain mappings remain for human review.",
        )
        return {
            "source_domain": "curriculum",
            "records_seen": len(chunks),
            "contexts_seen": contexts_seen,
            "contexts_skipped": contexts_skipped,
            "mappings_created": created,
            "mappings_skipped": skipped,
            "auto_review": auto_review,
        }

    def curriculum_skill_contexts(self, chunk: DocumentChunk) -> List[Dict[str, Any]]:
        metadata = chunk.chunk_metadata or {}
        evidence_type = metadata.get("curriculum_evidence_type") or self.infer_curriculum_evidence_type(metadata)
        section = metadata.get("section") or "body"
        outcome_type = metadata.get("outcome_type") or "unknown"
        raw_lines = [line.strip() for line in (chunk.content or "").splitlines() if line.strip()]
        contexts: List[Dict[str, Any]] = []
        preferred_sections = {
            "module_outcome",
            "assessment_criteria",
            "competency",
            "learning_objective",
            "module_topic",
            "assessment_method",
            "module_metadata",
        }
        preferred_markers = re.compile(
            r"\b(outcome|objective|competenc|skill|able to|assessment|topic|module content|syllabus|credits?|nqf|future career|career path|graduates?|technology|software|data|network|programming|development|design|analysis|analytical)\b",
            re.IGNORECASE,
        )
        noisy_markers = re.compile(
            r"\b(appendix|sampling variability|statistics south africa|table\s+\d|page\s+\d|copyright|admission requirements?|additional requirements?|method requirements?|home language|first additional language|language of instruction|closing date|application form|minimum requirement|achievement rating|aps score|grade 11|grade 12|national senior|nsc|selection will be based)\b",
            re.IGNORECASE,
        )
        metadata_only = re.compile(
            r"^(programme|module code|module name|faculty|department|campus|qualification|additional requirements?|method requirements?|instruction|cput test curriculum)\s*:?,?",
            re.IGNORECASE,
        )
        for line in raw_lines:
            cleaned = re.sub(r"\s+", " ", line).strip(" -:;\t")
            if not cleaned or len(cleaned) < 8:
                continue
            if len(cleaned) > 260:
                continue
            if noisy_markers.search(cleaned):
                continue
            if metadata_only.match(cleaned):
                continue
            marker_match = preferred_markers.search(cleaned)
            trusted_section = section in preferred_sections and section != "module_metadata"
            if evidence_type == "prospectus":
                looks_preferred = bool(marker_match)
            else:
                looks_preferred = trusted_section or outcome_type != "unknown" or bool(marker_match)
            if not looks_preferred:
                continue
            quality = self.curriculum_context_quality(
                text=cleaned,
                section=section,
                outcome_type=outcome_type,
                evidence_type=evidence_type,
            )
            if quality < 0.55:
                continue
            contexts.append(
                {
                    "text": cleaned,
                    "context_type": outcome_type if outcome_type != "unknown" else section,
                    "quality_weight": quality,
                    "minimum_confidence": 0.62 if evidence_type == "prospectus" else 0.58,
                    "include_semantic": False,
                    "semantic_threshold": 0.62,
                    "context_index": len(contexts),
                }
            )
            if len(contexts) >= 8:
                break
        return contexts

    @staticmethod
    def is_generic_curriculum_skill(matched_text: str, skill_name: str) -> bool:
        generic_terms = {
            "assessment", "assessments", "assessment criteria", "assignment", "assignments",
            "competency", "competencies", "concept", "concepts", "credits", "curriculum", "environmental",
            "fundamental", "fundamentals", "learning", "learning outcome", "learning outcomes", "module", "modules",
            "issue", "issues", "nqf", "objective", "objectives", "outcome", "outcomes", "portfolio",
            "practical", "programme", "program", "project", "requirement", "requirements",
            "skill", "skills", "student", "students", "technique", "techniques", "topic", "topics",
        }
        values = {normalise_text(matched_text or ""), normalise_text(skill_name or "")}
        return any(value in generic_terms for value in values)
    @staticmethod
    def infer_curriculum_evidence_type(metadata: Dict[str, Any]) -> str:
        source_name = " ".join(
            str(metadata.get(key) or "")
            for key in ("source_filename", "document_key", "document_type")
        ).lower()
        if "prospectus" in source_name:
            return "prospectus"
        if "study guide" in source_name or "study_guide" in source_name:
            return "study_guide"
        if "syllabus" in source_name:
            return "syllabus"
        if "module" in source_name and ("descriptor" in source_name or "guide" in source_name):
            return "module_descriptor"
        return "unknown"
    @staticmethod
    def curriculum_context_quality(
        text: str,
        section: str,
        outcome_type: str,
        evidence_type: str,
    ) -> float:
        quality = 0.48
        if section in {"module_outcome", "assessment_criteria", "competency", "learning_objective"}:
            quality += 0.25
        elif section in {"module_topic", "assessment_method", "module_metadata"}:
            quality += 0.16
        if outcome_type in {"module_outcome", "assessment_criteria", "competency", "learning_objective"}:
            quality += 0.18
        if evidence_type in {"study_guide", "syllabus", "module_descriptor", "curriculum_map"}:
            quality += 0.12
        elif evidence_type == "prospectus":
            quality -= 0.08
        if re.search(r"\b(able to|outcome|objective|competenc|design|develop|analyse|evaluate|implement|manage|apply)\b", text, re.IGNORECASE):
            quality += 0.10
        if re.search(r"\b(software|programming|data|database|network|cyber|web|application|systems?|analytics?|technology|technical|graduates?)\b", text, re.IGNORECASE):
            quality += 0.08
        if len(text) > 180:
            quality -= 0.12
        if re.search(r"\d{4}|www\.|http|admission|minimum requirement", text, re.IGNORECASE):
            quality -= 0.12
        return round(max(0.0, min(1.0, quality)), 4)
    def extract_from_labour_market(
        self,
        db: Session,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        indicators = (
            db.query(LabourMarketIndicator)
            .order_by(LabourMarketIndicator.id_indicator.asc())
            .limit(limit)
            .all()
        )

        created = 0
        skipped = 0
        alias_pairs = self.active_alias_skill_pairs(db)
        alias_index = self.alias_candidate_index(alias_pairs)
        esco_by_skill = self.esco_by_skill_id(db)

        for indicator in indicators:
            observations = (
                db.query(LabourMarketObservation)
                .filter(LabourMarketObservation.indicator_id == indicator.id_indicator)
                .limit(5)
                .all()
            )
            sample_context = " ".join(
                filter(
                    None,
                    [
                        indicator.name,
                        indicator.category,
                        indicator.unit,
                        " ".join(obs.source_file or "" for obs in observations),
                    ],
                )
            )

            matches = self.extract_alias_matches_from_index(
                sample_context,
                alias_index=alias_index,
                esco_by_skill=esco_by_skill,
            )
            for match in matches:
                source_record_id = f"lmi_indicator:{indicator.id_indicator}"
                if self.mapping_exists(
                    db=db,
                    source_domain="labour_market",
                    source_entity_type="lmi_indicator",
                    source_entity_id=None,
                    source_record_id=source_record_id,
                    skill_id=match["skill"].skill_id,
                    source_text_hash=content_hash(sample_context),
                    matched_text=match["matched_text"],
                ):
                    skipped += 1
                    continue

                db.add(
                    SkillMapping(
                        skill_id=match["skill"].skill_id,
                        esco_skill_id=match["esco_skill_id"],
                        source_domain="labour_market",
                        source_entity_type="lmi_indicator",
                        source_entity_id=None,
                        source_record_id=source_record_id,
                        source_text_hash=content_hash(sample_context),
                        matched_text=match["matched_text"],
                        extraction_method="alias_match",
                        confidence_score=match["confidence_score"],
                        evidence_start=match["start"],
                        evidence_end=match["end"],
                        evidence_text=self.evidence_window(sample_context, match["start"], match["end"]),
                        mapping_status="candidate",
                        confidence_calibration=match.get("calibration", {}),
                        mapping_metadata={
                            "indicator_id": indicator.id_indicator,
                            "indicator_name": indicator.name,
                            "observation_samples": len(observations),
                            "alias_id": str(match["alias"].alias_id) if match.get("alias") else None,
                            "semantic_similarity": match.get("semantic_similarity"),
                        },
                    )
                )
                created += 1

        row_limit = max(0, limit - len(indicators))
        extracted_rows = (
            db.query(ExtractedTableRow)
            .order_by(ExtractedTableRow.created_at.desc())
            .limit(row_limit)
            .all()
            if row_limit
            else []
        )

        for row in extracted_rows:
            row_context = json.dumps(
                {
                    "row": row.row_payload,
                    "normalised": row.normalised_payload,
                },
                ensure_ascii=True,
                default=str,
            )

            matches = self.extract_alias_matches_from_index(
                row_context,
                alias_index=alias_index,
                esco_by_skill=esco_by_skill,
            )
            for match in matches:
                source_record_id = f"extracted_table_row:{row.row_id}"
                if self.mapping_exists(
                    db=db,
                    source_domain="labour_market",
                    source_entity_type="extracted_table_row",
                    source_entity_id=row.row_id,
                    source_record_id=source_record_id,
                    skill_id=match["skill"].skill_id,
                    source_text_hash=content_hash(row_context),
                    matched_text=match["matched_text"],
                ):
                    skipped += 1
                    continue

                db.add(
                    SkillMapping(
                        skill_id=match["skill"].skill_id,
                        esco_skill_id=match["esco_skill_id"],
                        source_domain="labour_market",
                        source_entity_type="extracted_table_row",
                        source_entity_id=row.row_id,
                        source_record_id=source_record_id,
                        source_text_hash=content_hash(row_context),
                        matched_text=match["matched_text"],
                        extraction_method="alias_match",
                        confidence_score=match["confidence_score"],
                        evidence_start=match["start"],
                        evidence_end=match["end"],
                        evidence_text=self.evidence_window(row_context, match["start"], match["end"]),
                        mapping_status="candidate",
                        confidence_calibration=match.get("calibration", {}),
                        mapping_metadata={
                            "table_id": str(row.table_id),
                            "row_number": row.row_number,
                            "alias_id": str(match["alias"].alias_id) if match.get("alias") else None,
                            "semantic_similarity": match.get("semantic_similarity"),
                        },
                    )
                )
                created += 1

        db.commit()
        auto_review = self.auto_approve_high_confidence_mappings(
            db=db,
            source_domain="labour_market",
            min_confidence=0.90,
            note="Auto-approved high-confidence labour-market evidence mappings after generation; uncertain mappings remain for human review.",
        )
        return {
            "source_domain": "labour_market",
            "records_seen": len(indicators) + len(extracted_rows),
            "mappings_created": created,
            "mappings_skipped": skipped,
            "auto_review": auto_review,
        }

    def generate_skill_demand_evidence(
        self,
        db: Session,
        limit: int = 10000,
    ) -> Dict[str, Any]:
        signals = (
            db.query(LabourMarketSignal)
            .order_by(LabourMarketSignal.demand_score.desc(), LabourMarketSignal.created_at.asc())
            .limit(limit)
            .all()
        )
        skills = db.query(Skill).filter(Skill.status == "active").all()
        existing_hashes = {
            row[0]
            for row in db.query(SkillDemandEvidence.evidence_hash).all()
        }

        seen = 0
        created = 0
        skipped = 0

        for signal in signals:
            for skill in skills:
                match = self.match_signal_to_skill(signal, skill)
                if not match:
                    continue
                seen += 1
                evidence_hash = self.skill_demand_hash(signal.signal_id, skill.skill_id, match["method"])
                if evidence_hash in existing_hashes:
                    skipped += 1
                    continue

                db.add(
                    SkillDemandEvidence(
                        skill_id=skill.skill_id,
                        signal_id=signal.signal_id,
                        evidence_type="canonical_signal_match",
                        match_method=match["method"],
                        matched_context=match["matched_context"][:255],
                        demand_score=round(signal.demand_score * match["weight"], 4),
                        confidence_score=round(min(0.98, signal.confidence_score * match["confidence"]), 4),
                        evidence_weight=match["weight"],
                        rationale=match["rationale"],
                        evidence_hash=evidence_hash,
                        evidence_metadata={
                            "skill_key": skill.skill_key,
                            "skill_category": skill.category,
                            "canonical_key": signal.canonical_key,
                            "canonical_name": signal.canonical_name,
                            "dimension_type": signal.dimension_type,
                            "dimension_value": signal.dimension_value,
                            "signal_demand_score": signal.demand_score,
                            "signal_confidence_score": signal.confidence_score,
                        },
                    )
                )
                existing_hashes.add(evidence_hash)
                created += 1

        db.commit()
        return {
            "signals_seen": len(signals),
            "skills_seen": len(skills),
            "evidence_seen": seen,
            "evidence_created": created,
            "evidence_skipped": skipped,
        }

    def list_skill_demand_evidence(
        self,
        db: Session,
        skill_id: Optional[UUID] = None,
        limit: int = 200,
    ) -> List[SkillDemandEvidence]:
        query = db.query(SkillDemandEvidence)
        if skill_id:
            query = query.filter(SkillDemandEvidence.skill_id == skill_id)
        return (
            query
            .order_by(SkillDemandEvidence.demand_score.desc(), SkillDemandEvidence.confidence_score.desc())
            .limit(min(max(limit, 1), 1000))
            .all()
        )

    def active_alias_skill_pairs(self, db: Session) -> List[tuple[SkillAlias, Skill]]:
        return (
            db.query(SkillAlias, Skill)
            .join(Skill, SkillAlias.skill_id == Skill.skill_id)
            .filter(SkillAlias.is_active.is_(True), Skill.status == "active")
            .options(
                load_only(
                    SkillAlias.alias_id,
                    SkillAlias.skill_id,
                    SkillAlias.alias,
                    SkillAlias.normalised_alias,
                    SkillAlias.confidence_weight,
                ),
                load_only(
                    Skill.skill_id,
                    Skill.skill_key,
                    Skill.name,
                ),
            )
            .all()
        )

    def alias_candidate_index(
        self,
        alias_pairs: List[tuple[SkillAlias, Skill]],
    ) -> Dict[str, List[tuple[SkillAlias, Skill]]]:
        """Index aliases by informative tokens so batch extraction stays fast."""
        stop_words = {
            "and", "the", "for", "with", "from", "that", "this", "have", "will",
            "are", "can", "job", "jobs", "work", "skill", "skills", "using", "use",
        }
        index: Dict[str, List[tuple[SkillAlias, Skill]]] = defaultdict(list)
        seen: set[tuple[str, UUID]] = set()
        for alias, skill in alias_pairs:
            alias_text = alias.normalised_alias or normalise_text(alias.alias or "")
            tokens = [token for token in re.findall(r"[a-z0-9]+", alias_text) if len(token) >= 3]
            informative_tokens = [token for token in tokens if token not in stop_words]
            if len(alias_text) < 4 or not informative_tokens:
                continue
            if len(informative_tokens) == 1 and len(informative_tokens[0]) < 5:
                continue
            for token in informative_tokens:
                key = (token, alias.alias_id)
                if key in seen:
                    continue
                seen.add(key)
                index[token].append((alias, skill))
        return index

    def extract_alias_matches_from_index(
        self,
        source_text: str,
        alias_index: Dict[str, List[tuple[SkillAlias, Skill]]],
        esco_by_skill: Dict[UUID, Optional[UUID]],
    ) -> List[Dict[str, Any]]:
        cleaned = normalise_text(source_text or "")
        if not cleaned:
            return []
        candidate_pairs: List[tuple[SkillAlias, Skill]] = []
        seen_alias_ids = set()
        for token in set(re.findall(r"[a-z0-9]+", cleaned)):
            for alias, skill in alias_index.get(token, []):
                if alias.alias_id in seen_alias_ids:
                    continue
                seen_alias_ids.add(alias.alias_id)
                candidate_pairs.append((alias, skill))
        if not candidate_pairs:
            return []
        return self.extract_alias_matches_from_pairs(
            source_text=source_text,
            alias_pairs=candidate_pairs,
            esco_by_skill=esco_by_skill,
        )
    def esco_by_skill_id(self, db: Session) -> Dict[UUID, Optional[UUID]]:
        rows = db.query(ESCOSkill.skill_id, ESCOSkill.esco_skill_id).all()
        return {skill_id: esco_skill_id for skill_id, esco_skill_id in rows if skill_id}

    def extract_alias_matches_from_pairs(
        self,
        source_text: str,
        alias_pairs: List[tuple[SkillAlias, Skill]],
        esco_by_skill: Dict[UUID, Optional[UUID]],
    ) -> List[Dict[str, Any]]:
        cleaned = normalise_text(source_text or "")
        if not cleaned:
            return []
        best_by_skill: Dict[UUID, Dict[str, Any]] = {}
        cleaned_tokens = set(re.findall(r"[a-z0-9]+", cleaned))
        for alias, skill in alias_pairs:
            alias_text = alias.normalised_alias
            if len(alias_text) < 4:
                continue
            alias_tokens = re.findall(r"[a-z0-9]+", alias_text)
            if not alias_tokens:
                continue
            if len(alias_tokens) == 1 and len(alias_tokens[0]) < 5:
                continue
            if not any(token in cleaned_tokens for token in alias_tokens):
                continue
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(alias_text) + r"(?![a-zA-Z0-9])"
            match = re.search(pattern, cleaned)
            if not match:
                continue
            alias_length_bonus = min(len(alias_text) / 40, 0.12)
            raw_confidence = min(0.98, 0.72 + alias_length_bonus + (alias.confidence_weight * 0.14))
            calibration = self.calibrate_confidence(
                method="alias_match",
                raw_score=raw_confidence,
                evidence={
                    "alias_length": len(alias_text),
                    "confidence_weight": alias.confidence_weight,
                    "batch_cached": True,
                },
            )
            candidate = {
                "skill": skill,
                "alias": alias,
                "esco_skill_id": esco_by_skill.get(skill.skill_id),
                "matched_text": alias.alias,
                "start": match.start(),
                "end": match.end(),
                "confidence_score": calibration["calibrated_score"],
                "calibration": calibration,
                "semantic_similarity": None,
            }
            existing = best_by_skill.get(skill.skill_id)
            if not existing or candidate["confidence_score"] > existing["confidence_score"]:
                best_by_skill[skill.skill_id] = candidate
        return list(best_by_skill.values())
    def extract_matches(
        self,
        db: Session,
        source_text: str,
        include_semantic: bool = True,
        semantic_threshold: float = 0.40,
    ) -> List[Dict[str, Any]]:
        cleaned = normalise_text(source_text or "")
        if not cleaned:
            return []

        aliases = (
            db.query(SkillAlias, Skill)
            .join(Skill, SkillAlias.skill_id == Skill.skill_id)
            .filter(SkillAlias.is_active.is_(True), Skill.status == "active")
            .all()
        )

        best_by_skill: Dict[UUID, Dict[str, Any]] = {}

        for alias, skill in aliases:
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(alias.normalised_alias) + r"(?![a-zA-Z0-9])"
            match = re.search(pattern, cleaned)
            if not match:
                continue

            esco = (
                db.query(ESCOSkill)
                .filter(ESCOSkill.skill_id == skill.skill_id)
                .first()
            )
            alias_length_bonus = min(len(alias.normalised_alias) / 40, 0.12)
            raw_confidence = min(0.98, 0.72 + alias_length_bonus + (alias.confidence_weight * 0.14))
            calibration = self.calibrate_confidence(
                method="alias_match",
                raw_score=raw_confidence,
                evidence={
                    "alias_length": len(alias.normalised_alias),
                    "confidence_weight": alias.confidence_weight,
                },
            )
            candidate = {
                "skill": skill,
                "alias": alias,
                "esco_skill_id": esco.esco_skill_id if esco else None,
                "matched_text": source_text[match.start():match.end()] or alias.alias,
                "start": match.start(),
                "end": match.end(),
                "confidence_score": calibration["calibrated_score"],
                "calibration": calibration,
                "semantic_similarity": None,
            }

            existing = best_by_skill.get(skill.skill_id)
            if not existing or candidate["confidence_score"] > existing["confidence_score"]:
                best_by_skill[skill.skill_id] = candidate

        if include_semantic:
            for candidate in self.semantic_match_text(db, source_text, threshold=semantic_threshold, limit=10):
                existing = best_by_skill.get(candidate["skill"].skill_id)
                if not existing or candidate["confidence_score"] > existing["confidence_score"]:
                    best_by_skill[candidate["skill"].skill_id] = candidate

        return list(best_by_skill.values())

    def semantic_match_text(
        self,
        db: Session,
        source_text: str,
        threshold: float = 0.40,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        if not source_text:
            return []
        source_vector = compute_embedding(source_text)
        skills = (
            db.query(Skill)
            .filter(Skill.status == "active")
            .order_by(Skill.name.asc())
            .limit(5000)
            .all()
        )
        candidates: List[Dict[str, Any]] = []
        for skill in skills:
            candidate_text = self.skill_semantic_text(db, skill)
            similarity = cosine_similarity(source_vector, compute_embedding(candidate_text))
            if similarity < threshold:
                continue
            esco = db.query(ESCOSkill).filter(ESCOSkill.skill_id == skill.skill_id).first()
            calibration = self.calibrate_confidence(
                method="semantic_embedding",
                raw_score=similarity,
                evidence={"threshold": threshold, "candidate_text_length": len(candidate_text)},
            )
            candidates.append(
                {
                    "skill": skill,
                    "alias": None,
                    "esco_skill_id": esco.esco_skill_id if esco else None,
                    "matched_text": skill.name,
                    "start": None,
                    "end": None,
                    "confidence_score": calibration["calibrated_score"],
                    "calibration": calibration,
                    "semantic_similarity": round(similarity, 4),
                }
            )
        return sorted(candidates, key=lambda item: item["confidence_score"], reverse=True)[:limit]

    def skill_semantic_text(self, db: Session, skill: Skill) -> str:
        aliases = (
            db.query(SkillAlias.alias)
            .filter(SkillAlias.skill_id == skill.skill_id, SkillAlias.is_active.is_(True))
            .limit(25)
            .all()
        )
        esco_rows = (
            db.query(ESCOSkill.preferred_label, ESCOSkill.description)
            .filter(ESCOSkill.skill_id == skill.skill_id)
            .limit(10)
            .all()
        )
        return " ".join(
            filter(
                None,
                [
                    skill.skill_key,
                    skill.name,
                    skill.category,
                    skill.description,
                    " ".join(row[0] for row in aliases),
                    " ".join(" ".join(filter(None, row)) for row in esco_rows),
                ],
            )
        )

    @staticmethod
    def calibrate_confidence(method: str, raw_score: float, evidence: Dict[str, Any]) -> Dict[str, Any]:
        bounded = max(0.0, min(float(raw_score or 0.0), 1.0))
        if method == "alias_match":
            calibrated = min(0.99, max(0.50, bounded))
        elif method in ("semantic_embedding", "semantic_hash_embedding"):
            calibrated = max(0.0, min(0.92, 0.20 + (bounded * 0.85)))
        else:
            calibrated = bounded
        return {
            "method": method,
            "raw_score": round(bounded, 4),
            "calibrated_score": round(calibrated, 4),
            "evidence": evidence,
            "calibration_version": "heuristic_calibration_v1",
        }

    def skill_noise_reasons(self, skill: Skill) -> List[str]:
        name_text = normalise_text(skill.name or "")
        context_text = normalise_text(" ".join(filter(None, [skill.name, skill.description or ""])))
        text = context_text or name_text
        if not text:
            return ["empty_skill_text"]
        reasons: List[str] = []
        tokens = name_text.split()
        has_strong_technical_term = any(term in text for term in self.STRONG_TECHNICAL_TERMS)
        if len(text) <= 2:
            reasons.append("too_short")
        if len(tokens) > 10 and not has_strong_technical_term:
            reasons.append("phrase_too_long_for_skill")
        if any(term in text for term in self.NOISY_JOB_SKILL_TERMS) and not has_strong_technical_term:
            reasons.append("generic_or_non_skill_term")
        for pattern in self.NOISY_JOB_SKILL_PATTERNS:
            if pattern.search(text) and not has_strong_technical_term:
                reasons.append("job_advert_noise_pattern")
                break
        alpha_chars = sum(1 for char in text if char.isalpha())
        if alpha_chars < 3:
            reasons.append("not_enough_alpha_content")
        if text.isupper() and len(text) > 12 and not has_strong_technical_term:
            reasons.append("all_caps_phrase_noise")
        return sorted(set(reasons))

    def alias_quality_reasons(self, alias: SkillAlias) -> List[str]:
        text = normalise_text(alias.alias or alias.normalised_alias or "")
        reasons: List[str] = []
        if len(text) <= 2:
            reasons.append("too_short")
        if len(text.split()) > 8:
            reasons.append("alias_too_long")
        if re.fullmatch(r"[\W_\d]+", text or ""):
            reasons.append("not_skill_text")
        if any(term in text for term in self.NOISY_JOB_SKILL_TERMS):
            reasons.append("generic_alias")
        for pattern in self.NOISY_JOB_SKILL_PATTERNS:
            if pattern.search(text):
                reasons.append("noise_pattern")
                break
        return sorted(set(reasons))

    def noisy_job_skill_queue(
        self,
        db: Session,
        limit: int = 100,
        include_reviewed: bool = False,
    ) -> List[Dict[str, Any]]:
        query = db.query(Skill).filter(Skill.category == "job_posting")
        if not include_reviewed:
            query = query.filter(Skill.status == "active")
        skills = query.order_by(Skill.created_at.desc()).limit(min(max(limit, 1), 5000) * 5).all()
        mapping_counts = dict(
            db.query(SkillMapping.skill_id, func.count(SkillMapping.mapping_id))
            .filter(SkillMapping.source_domain == "labour_market")
            .group_by(SkillMapping.skill_id)
            .all()
        )
        rows: List[Dict[str, Any]] = []
        for skill in skills:
            reasons = self.skill_noise_reasons(skill)
            if not reasons:
                continue
            rows.append(
                {
                    "skill_id": str(skill.skill_id),
                    "skill_key": skill.skill_key,
                    "name": skill.name,
                    "status": skill.status,
                    "category": skill.category,
                    "mapping_count": int(mapping_counts.get(skill.skill_id, 0) or 0),
                    "reasons": reasons,
                    "suggested_action": "mark_needs_review",
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def review_noisy_job_skills(
        self,
        db: Session,
        reviewer_id: str,
        decision: str = "needs_review",
        limit: int = 100,
        dry_run: bool = True,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        if decision not in {"needs_review", "rejected"}:
            raise ValueError("Noisy skill decision must be needs_review or rejected")
        queue = self.noisy_job_skill_queue(db=db, limit=limit)
        if dry_run:
            return {"dry_run": True, "decision": decision, "matched": len(queue), "sample": queue[:50]}
        updated_skills = 0
        updated_mappings = 0
        updated_aliases = 0
        now = datetime.now(timezone.utc)
        for item in queue:
            skill = db.query(Skill).filter(Skill.skill_id == item["skill_id"]).first()
            if not skill:
                continue
            skill.status = decision
            skill.skill_metadata = {
                **(skill.skill_metadata or {}),
                "quality_review": {
                    "decision": decision,
                    "reviewed_by": reviewer_id,
                    "reviewed_at": now.isoformat(),
                    "reasons": item["reasons"],
                    "note": note,
                },
            }
            mappings = db.query(SkillMapping).filter(
                SkillMapping.skill_id == skill.skill_id,
                SkillMapping.source_domain == "labour_market",
                SkillMapping.mapping_status.in_(["candidate", "needs_review"]),
            ).all()
            for mapping in mappings:
                mapping.mapping_status = decision
                mapping.reviewed_by = reviewer_id
                mapping.reviewed_at = now
                mapping.review_note = note or "Queued by job skill data-quality refinement."
                mapping.mapping_metadata = {
                    **(mapping.mapping_metadata or {}),
                    "quality_review": {
                        "decision": decision,
                        "reasons": item["reasons"],
                        "reviewed_by": reviewer_id,
                    },
                }
                db.add(mapping)
                updated_mappings += 1
            aliases = db.query(SkillAlias).filter(SkillAlias.skill_id == skill.skill_id, SkillAlias.is_active.is_(True)).all()
            for alias in aliases:
                alias.is_active = False
                alias.confidence_weight = min(float(alias.confidence_weight or 0.0), 0.10)
                db.add(alias)
                updated_aliases += 1
            db.add(skill)
            updated_skills += 1
        db.commit()
        return {
            "dry_run": False,
            "decision": decision,
            "updated_skills": updated_skills,
            "updated_mappings": updated_mappings,
            "deactivated_aliases": updated_aliases,
        }

    def low_confidence_mapping_queue(
        self,
        db: Session,
        threshold: float = 0.50,
        source_domain: Optional[str] = None,
        limit: int = 100,
    ) -> List[SkillMapping]:
        query = db.query(SkillMapping).filter(
            SkillMapping.mapping_status == "candidate",
            SkillMapping.confidence_score <= threshold,
        )
        if source_domain:
            query = query.filter(SkillMapping.source_domain == source_domain)
        return (
            query.order_by(SkillMapping.confidence_score.asc(), SkillMapping.created_at.desc())
            .limit(min(max(limit, 1), 5000))
            .all()
        )

    def review_low_confidence_mappings(
        self,
        db: Session,
        reviewer_id: str,
        threshold: float = 0.50,
        source_domain: Optional[str] = None,
        decision: str = "needs_review",
        limit: int = 100,
        dry_run: bool = True,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        if decision not in {"needs_review", "rejected"}:
            raise ValueError("Low-confidence decision must be needs_review or rejected")
        mappings = self.low_confidence_mapping_queue(
            db=db,
            threshold=threshold,
            source_domain=source_domain,
            limit=limit,
        )
        if dry_run:
            return {
                "dry_run": True,
                "decision": decision,
                "threshold": threshold,
                "source_domain": source_domain,
                "matched": len(mappings),
                "sample": mappings[:50],
            }
        now = datetime.now(timezone.utc)
        for mapping in mappings:
            mapping.mapping_status = decision
            mapping.reviewed_by = reviewer_id
            mapping.reviewed_at = now
            mapping.review_note = note or f"Queued by confidence threshold <= {threshold}."
            mapping.mapping_metadata = {
                **(mapping.mapping_metadata or {}),
                "low_confidence_review": {
                    "decision": decision,
                    "threshold": threshold,
                    "source_domain": source_domain,
                    "reviewed_by": reviewer_id,
                },
            }
            db.add(mapping)
        db.commit()
        return {
            "dry_run": False,
            "decision": decision,
            "threshold": threshold,
            "source_domain": source_domain,
            "updated": len(mappings),
        }

    def alias_quality_queue(self, db: Session, limit: int = 100) -> List[Dict[str, Any]]:
        aliases = (
            db.query(SkillAlias)
            .filter(SkillAlias.is_active.is_(True))
            .order_by(SkillAlias.created_at.desc())
            .limit(min(max(limit, 1), 5000) * 5)
            .all()
        )
        rows: List[Dict[str, Any]] = []
        for alias in aliases:
            reasons = self.alias_quality_reasons(alias)
            if not reasons:
                continue
            rows.append(
                {
                    "alias_id": str(alias.alias_id),
                    "skill_id": str(alias.skill_id),
                    "alias": alias.alias,
                    "normalised_alias": alias.normalised_alias,
                    "source": alias.source,
                    "confidence_weight": alias.confidence_weight,
                    "reasons": reasons,
                    "suggested_action": "deactivate_or_reduce_weight",
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def review_alias_quality(
        self,
        db: Session,
        limit: int = 100,
        dry_run: bool = True,
        deactivate: bool = True,
    ) -> Dict[str, Any]:
        queue = self.alias_quality_queue(db=db, limit=limit)
        if dry_run:
            return {"dry_run": True, "matched": len(queue), "deactivate": deactivate, "sample": queue[:50]}
        updated = 0
        for item in queue:
            alias = db.query(SkillAlias).filter(SkillAlias.alias_id == item["alias_id"]).first()
            if not alias:
                continue
            if deactivate:
                alias.is_active = False
            alias.confidence_weight = min(float(alias.confidence_weight or 0.0), 0.20)
            db.add(alias)
            updated += 1
        db.commit()
        return {"dry_run": False, "updated_aliases": updated, "deactivate": deactivate}

    def duplicate_quality_review(
        self,
        db: Session,
        actor_id: str,
        limit: int = 50,
        min_score: float = 0.97,
        dry_run: bool = True,
        auto_merge: bool = False,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        candidates = self.duplicate_candidates(db=db, limit=limit, min_score=min_score)
        if dry_run or not auto_merge:
            return {
                "dry_run": dry_run,
                "auto_merge": auto_merge,
                "min_score": min_score,
                "matched": len(candidates),
                "sample": candidates[:50],
            }
        merged: List[Dict[str, Any]] = []
        for candidate in candidates:
            if float(candidate.get("score") or 0.0) < min_score:
                continue
            merged.append(
                self.merge_duplicate_candidate(
                    db=db,
                    source_skill_id=candidate["source_skill_id"],
                    target_skill_id=candidate["target_skill_id"],
                    actor_id=actor_id,
                    note=note or "Auto-merged exact/near-exact duplicate during skill quality refinement.",
                )
            )
        return {
            "dry_run": False,
            "auto_merge": True,
            "min_score": min_score,
            "merged_count": len(merged),
            "merged": merged,
        }
    def auto_approve_high_confidence_mappings(
        self,
        db: Session,
        reviewer_id: Optional[str] = None,
        min_confidence: float = 0.90,
        source_domain: Optional[str] = None,
        limit: int = 10000,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approve obvious high-confidence candidate mappings and leave uncertain cases for humans."""
        query = db.query(SkillMapping).filter(
            SkillMapping.mapping_status == "candidate",
            SkillMapping.confidence_score >= min_confidence,
        )
        if source_domain:
            query = query.filter(SkillMapping.source_domain == source_domain)
        candidates = (
            query.order_by(SkillMapping.confidence_score.desc(), SkillMapping.created_at.asc())
            .limit(limit)
            .all()
        )
        now = datetime.now(timezone.utc)
        review_note = note or (
            f"Auto-approved by system because confidence >= {min_confidence:.2f}; "
            "low/medium confidence mappings remain for human review."
        )
        updated = 0
        by_domain: Dict[str, int] = {}
        for mapping in candidates:
            mapping.mapping_status = "approved"
            mapping.reviewed_by = reviewer_id
            mapping.reviewed_at = now
            mapping.review_note = review_note
            mapping.mapping_metadata = {
                **(mapping.mapping_metadata or {}),
                "auto_review": {
                    "decision": "approved",
                    "threshold": min_confidence,
                    "reviewed_by": reviewer_id,
                    "system_actor": "system:auto_high_confidence",
                    "reviewed_at": now.isoformat(),
                    "reason": "high_confidence_candidate_mapping",
                    "human_review_required": False,
                },
            }
            db.add(mapping)
            log_audit_event(
                db=db,
                event_layer="application",
                event_type="mapping_review_auto_approved",
                actor_type="system",
                actor_id=reviewer_id or "system:auto_high_confidence",
                token_id=None,
                source_component="skill_harmonisation_service",
                action="mapping_review_auto_approved",
                result="success",
                metadata={
                    "mapping_id": str(mapping.mapping_id),
                    "decision": "approved",
                    "resulting_status": "approved",
                    "previous_status": "candidate",
                    "source_domain": mapping.source_domain,
                    "threshold": min_confidence,
                    "system_actor": "system:auto_high_confidence",
                    "note_preview": review_note[:200],
                },
            )
            updated += 1
            by_domain[mapping.source_domain] = by_domain.get(mapping.source_domain, 0) + 1
        db.commit()
        return {
            "auto_approved": updated,
            "threshold": min_confidence,
            "source_domain": source_domain,
            "by_domain": by_domain,
            "review_note": review_note,
        }

    def review_mapping(
        self,
        db: Session,
        mapping_id: UUID,
        decision: str,
        reviewer_id: str,
        note: Optional[str] = None,
        skill_id: Optional[UUID] = None,
    ) -> SkillMapping:
        mapping = db.query(SkillMapping).filter(SkillMapping.mapping_id == mapping_id).first()
        if not mapping:
            raise ValueError("Skill mapping not found")
        if decision not in {"approved", "rejected", "merged", "needs_review", "deferred", "disagreement", "resolved"}:
            raise ValueError("Unsupported mapping review decision")
        if decision == "merged" and not skill_id:
            raise ValueError("A merged decision requires a replacement skill_id")
        previous_status = mapping.mapping_status
        previous_skill_id = mapping.skill_id
        if not note or len(note.strip()) < 10:
            raise ValueError("A review note of at least 10 characters is required")
        if skill_id:
            skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
            if not skill:
                raise ValueError("Replacement skill not found")
            mapping.skill_id = skill_id

        resulting_status = {
            "approved": "approved",
            "rejected": "rejected",
            "merged": "merged",
            "needs_review": "needs_review",
            "deferred": "deferred",
            "disagreement": "needs_review",
            "resolved": "approved",
        }[decision]
        mapping.mapping_status = resulting_status
        mapping.reviewed_by = reviewer_id
        mapping.reviewed_at = datetime.now(timezone.utc)
        mapping.review_note = note
        mapping.mapping_metadata = {
            **(mapping.mapping_metadata or {}),
            "review": {
                "decision": decision,
                "resulting_status": resulting_status,
                "reviewed_by": reviewer_id,
                "note": note,
                "replacement_skill_id": str(skill_id) if skill_id else None,
            },
        }
        db.add(
            SkillMappingReviewEvent(
                mapping_id=mapping.mapping_id,
                previous_status=previous_status,
                decision=decision,
                previous_skill_id=previous_skill_id,
                selected_skill_id=mapping.skill_id,
                reviewer_id=reviewer_id,
                note=note.strip(),
            )
        )
        log_audit_event(
            db=db,
            event_layer="application",
            event_type=f"mapping_review_{decision}",
            actor_type="human",
            actor_id=reviewer_id,
            token_id=None,
            source_component="skill_harmonisation_service",
            action=f"mapping_review_{decision}",
            result="success",
            metadata={
                "mapping_id": str(mapping.mapping_id),
                "decision": decision,
                "resulting_status": resulting_status,
                "previous_status": previous_status,
                "previous_skill_id": str(previous_skill_id),
                "selected_skill_id": str(mapping.skill_id),
                "note_preview": note.strip()[:200] if note else None,
            },
        )
        db.commit()
        db.refresh(mapping)
        log_structured(
            logger,
            "mapping_review",
            action="mapping_review_decided",
            decision=decision,
            resulting_status=resulting_status,
            mapping_id=str(mapping.mapping_id),
            previous_status=previous_status,
            current_status=mapping.mapping_status,
            reviewer_id=reviewer_id,
            replacement_skill_id=str(skill_id) if skill_id else None,
        )
        return mapping

    def merge_skills(
        self,
        db: Session,
        source_skill_id: UUID,
        target_skill_id: UUID,
        actor_id: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        if source_skill_id == target_skill_id:
            raise ValueError("Source and target skills must be different")
        source = db.query(Skill).filter(Skill.skill_id == source_skill_id).first()
        target = db.query(Skill).filter(Skill.skill_id == target_skill_id).first()
        if not source or not target:
            raise ValueError("Source or target skill not found")

        alias_count = db.query(SkillAlias).filter(SkillAlias.skill_id == source_skill_id).update(
            {SkillAlias.skill_id: target_skill_id},
            synchronize_session=False,
        )
        mapping_count = db.query(SkillMapping).filter(SkillMapping.skill_id == source_skill_id).update(
            {
                SkillMapping.skill_id: target_skill_id,
                SkillMapping.mapping_status: "merged",
                SkillMapping.reviewed_by: actor_id,
                SkillMapping.reviewed_at: datetime.now(timezone.utc),
                SkillMapping.review_note: note,
            },
            synchronize_session=False,
        )
        esco_count = db.query(ESCOSkill).filter(ESCOSkill.skill_id == source_skill_id).update(
            {ESCOSkill.skill_id: target_skill_id},
            synchronize_session=False,
        )
        evidence_count = db.query(SkillDemandEvidence).filter(SkillDemandEvidence.skill_id == source_skill_id).update(
            {SkillDemandEvidence.skill_id: target_skill_id},
            synchronize_session=False,
        )
        signal_count = 0
        for signal in (
            db.query(LabourMarketSignal)
            .filter(LabourMarketSignal.signal_metadata["skill_id"].astext == str(source_skill_id))
            .all()
        ):
            signal.signal_metadata = {
                **(signal.signal_metadata or {}),
                "superseded_by_skill_id": str(target_skill_id),
                "superseded_reason": "skill_merged",
            }
            signal.confidence_score = min(float(signal.confidence_score or 0.0), 0.05)
            db.add(signal)
            signal_count += 1
        source.status = "merged"
        source.skill_metadata = {
            **(source.skill_metadata or {}),
            "merged_into_skill_id": str(target_skill_id),
            "merged_by": actor_id,
            "merge_note": note,
        }
        db.commit()
        return {
            "source_skill_id": str(source_skill_id),
            "target_skill_id": str(target_skill_id),
            "aliases_moved": alias_count,
            "mappings_moved": mapping_count,
            "esco_records_moved": esco_count,
            "evidence_moved": evidence_count,
            "signals_superseded": signal_count,
        }

    @staticmethod
    def mapping_exists(
        db: Session,
        source_domain: str,
        source_entity_type: str,
        source_entity_id: Optional[UUID],
        source_record_id: str,
        skill_id: UUID,
        source_text_hash: str,
        matched_text: str,
    ) -> bool:
        query = db.query(SkillMapping).filter(
            SkillMapping.source_domain == source_domain,
            SkillMapping.source_entity_type == source_entity_type,
            SkillMapping.source_record_id == source_record_id,
            SkillMapping.skill_id == skill_id,
            SkillMapping.source_text_hash == source_text_hash,
            SkillMapping.matched_text == matched_text,
        )
        if source_entity_id:
            query = query.filter(SkillMapping.source_entity_id == source_entity_id)
        return db.query(query.exists()).scalar()

    @staticmethod
    def match_signal_to_skill(signal: LabourMarketSignal, skill: Skill) -> Optional[Dict[str, Any]]:
        skill_text = " ".join(
            filter(None, [skill.skill_key, skill.name, skill.category, skill.description])
        ).lower()
        signal_text = " ".join(
            filter(None, [signal.canonical_key, signal.canonical_name, signal.dimension_type, signal.dimension_value])
        ).lower()

        strong_terms = {
            "labour-market-analysis",
            "statistics",
            "research",
            "data-analysis",
            "business-intelligence",
            "data-visualisation",
        }
        digital_terms = {
            "machine-learning",
            "python",
            "sql",
            "database-management",
            "software-development",
            "cloud-computing",
        }
        planning_terms = {
            "project-management",
            "quality-assurance",
            "communication",
            "problem-solving",
            "curriculum-design",
        }

        if skill.skill_key in strong_terms:
            weight = {
                "labour-market-analysis": 1.0,
                "statistics": 0.92,
                "research": 0.88,
                "data-analysis": 0.86,
                "business-intelligence": 0.78,
                "data-visualisation": 0.74,
            }[skill.skill_key]
            return {
                "method": "canonical_signal_skill_family_v1",
                "matched_context": f"{signal.canonical_name} -> {skill.name}",
                "weight": weight,
                "confidence": 0.95,
                "rationale": (
                    f"{skill.name} is analytically connected to {signal.canonical_name} "
                    "because this skill supports interpreting labour-market indicators."
                ),
            }

        if skill.skill_key in digital_terms and any(
            term in signal_text
            for term in ("employment", "labour force", "unemployment")
        ):
            return {
                "method": "digital_signal_support_v1",
                "matched_context": f"{signal.canonical_name} -> {skill.name}",
                "weight": 0.50,
                "confidence": 0.72,
                "rationale": (
                    f"{skill.name} is indirectly linked to {signal.canonical_name} "
                    "as a supporting digital capability for labour-market analytics."
                ),
            }

        if skill.skill_key in planning_terms and signal.dimension_type in {"industry", "occupation", "province"}:
            return {
                "method": "planning_context_signal_v1",
                "matched_context": f"{signal.dimension_type}:{signal.dimension_value} -> {skill.name}",
                "weight": 0.42,
                "confidence": 0.66,
                "rationale": (
                    f"{skill.name} is contextually relevant where labour-market signals vary by "
                    f"{signal.dimension_type}."
                ),
            }

        if skill.name.lower() in signal_text or skill.skill_key.replace("-", " ") in signal_text or skill_text in signal_text:
            return {
                "method": "direct_text_signal_match_v1",
                "matched_context": f"{signal_text} -> {skill.name}",
                "weight": 0.90,
                "confidence": 0.90,
                "rationale": f"{skill.name} was directly mentioned in the canonical labour-market signal context.",
            }

        return None

    @staticmethod
    def skill_demand_hash(signal_id: UUID, skill_id: UUID, method: str) -> str:
        return content_hash(
            json.dumps(
                {
                    "signal_id": str(signal_id),
                    "skill_id": str(skill_id),
                    "method": method,
                },
                sort_keys=True,
            )
        )

    @staticmethod
    def evidence_window(source_text: str, start: int, end: int, radius: int = 140) -> str:
        start = start or 0
        end = end or start
        left = max(0, start - radius)
        right = min(len(source_text), end + radius)
        return source_text[left:right].strip()

    @staticmethod
    def first_value(row: Dict[str, Any], *keys: str) -> Optional[str]:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    @staticmethod
    def esco_aliases(row: Dict[str, Any], preferred_label: str) -> List[str]:
        values = [preferred_label]
        for key in ("altLabels", "alternativeLabels", "hiddenLabels", "alt_label", "aliases"):
            value = row.get(key)
            if not value:
                continue
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            else:
                values.extend(re.split(r"\n|,|;", str(value)))
        cleaned = []
        seen = set()
        for value in values:
            alias = re.sub(r"\s+", " ", str(value).strip())
            key = normalise_text(alias)
            if alias and key not in seen:
                cleaned.append(alias)
                seen.add(key)
        return cleaned

    @staticmethod
    def create_alias_if_missing(
        db: Session,
        skill_id: UUID,
        alias: str,
        source: str,
        confidence_weight: float,
    ) -> bool:
        normalised = normalise_text(alias)
        existing = (
            db.query(SkillAlias)
            .filter(SkillAlias.skill_id == skill_id, SkillAlias.normalised_alias == normalised)
            .first()
        )
        if existing:
            return False
        db.add(
            SkillAlias(
                skill_id=skill_id,
                alias=alias[:255],
                normalised_alias=normalised[:255],
                language="en",
                source=source,
                confidence_weight=confidence_weight,
                is_active=True,
            )
        )
        return True


def slugify_skill(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return key[:150] or "skill"


skill_harmonisation_service = SkillHarmonisationService()








