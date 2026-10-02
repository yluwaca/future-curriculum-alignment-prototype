"""
Labour-market cleaning and canonical job skill pipeline.

This service turns ingested job postings into model-ready records, canonical
skills, skill mappings, aggregate job-skill signals, and demand evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.cleaned_ingestion_record import CleanedIngestionRecord
from app.models.esco_skill import ESCOSkill
from app.models.job_posting import JobPosting
from app.models.labour_market_signal import LabourMarketSignal
from app.models.raw_ingestion_record import RawIngestionRecord
from app.models.skill import Skill
from app.models.skill_alias import SkillAlias
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.skill_mapping import SkillMapping
from app.services.ingestion.adzuna_governance import (
    ADZUNA_ATTRIBUTION_NOTE,
    ADZUNA_PERMISSION,
)
from app.services.ingestion.job_advert_file_connector import clean_text
from app.services.skill_harmonisation_service import content_hash, normalise_text, slugify_skill


GENERIC_SKILL_TERMS = {
    "n/a",
    "none",
    "not specified",
    "communication",
    "teamwork",
    "skills",
    "training",
    "management",
    "supervision",
    "customer service",
}

EMPLOYMENT_TYPE_MAP = {
    "full_time": "full_time",
    "full-time": "full_time",
    "full time": "full_time",
    "part_time": "part_time",
    "part-time": "part_time",
    "part time": "part_time",
    "contract": "contract",
    "temporary": "temporary",
    "internship": "internship",
    "volunteer": "volunteer",
}


CURATED_TEXT_SKILLS = {
    "python": ["python"],
    "sql": ["sql", "structured query language"],
    "data-analysis": ["data analysis", "data analyst", "analytics"],
    "machine-learning": ["machine learning", "ml model", "predictive model"],
    "business-intelligence": ["business intelligence", "power bi", "tableau"],
    "data-visualisation": ["data visualization", "data visualisation", "dashboard"],
    "software-development": ["software development", "developer", "programming"],
    "database-management": ["database", "postgresql", "mysql", "sql server"],
    "cloud-computing": ["cloud", "aws", "azure", "google cloud"],
    "project-management": ["project management", "scrum", "agile"],
    "cybersecurity": ["cybersecurity", "information security", "network security"],
    "statistics": ["statistics", "statistical", "regression"],
}


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class JobSkillCandidate:
    text: str
    method: str
    confidence: float
    source: str


class LabourMarketSkillPipelineService:
    def run(
        self,
        db: Session,
        limit: int = 10000,
        offset: int = 0,
        actor_id: Optional[str] = None,
        sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        cleaned = self.clean_job_postings(db, limit=limit, offset=offset, sources=sources)
        db.commit()
        mappings = self.extract_and_map_job_skills(db, limit=limit, offset=offset, sources=sources)
        db.commit()
        signals = self.generate_job_skill_signals(db, limit=limit, sources=sources)
        db.commit()
        evidence = self.generate_job_skill_demand_evidence(db, limit=limit, sources=sources)
        db.commit()
        return {
            "actor_id": actor_id,
            "offset": offset,
            "limit": limit,
            "sources": list(sources) if sources else None,
            "cleaned": cleaned,
            "mappings": mappings,
            "signals": signals,
            "evidence": evidence,
        }

    def clean_job_postings(
        self, db: Session, limit: int = 10000, offset: int = 0, sources: Optional[List[str]] = None
    ) -> Dict[str, int]:
        postings = db.query(JobPosting).order_by(JobPosting.created_at.asc(), JobPosting.posting_id.asc())
        if sources:
            postings = postings.filter(JobPosting.source.in_(list(sources)))
        postings = postings.offset(offset).limit(limit).all()
        raw_by_source_record = self.raw_records_for_postings(db, [posting.job_id for posting in postings])
        existing_cleaned: Dict[Any, CleanedIngestionRecord] = {}
        raw_ids = [raw.record_id for raw in raw_by_source_record.values()]
        if raw_ids:
            for row in (
                db.query(CleanedIngestionRecord)
                .filter(CleanedIngestionRecord.raw_record_id.in_(raw_ids))
                .all()
            ):
                existing_cleaned[row.raw_record_id] = row

        created = 0
        updated = 0
        skipped = 0

        for posting in postings:
            raw = raw_by_source_record.get(posting.job_id)
            if not raw:
                skipped += 1
                continue
            payload = self.cleaned_payload(posting)
            payload_hash = stable_hash(json.dumps(payload, sort_keys=True, default=str))
            existing = existing_cleaned.get(raw.record_id)
            if existing:
                if existing.content_hash == payload_hash:
                    skipped += 1
                    continue
                existing.content_hash = payload_hash
                existing.cleaned_payload = payload
                existing.quality_score = self.quality_score(posting)
                existing.cleaning_metadata = self.cleaning_metadata(posting)
                existing.cleaning_status = "cleaned"
                updated += 1
            else:
                record = CleanedIngestionRecord(
                    raw_record_id=raw.record_id,
                    job_id=raw.job_id,
                    source_id=raw.source_id,
                    tenant_id=raw.tenant_id,
                    normaliser_key="job_advert_v1",
                    normaliser_version="1.0",
                    cleaning_status="cleaned",
                    content_hash=payload_hash,
                    quality_score=self.quality_score(posting),
                    cleaned_payload=payload,
                    cleaning_metadata=self.cleaning_metadata(posting),
                )
                db.add(record)
                existing_cleaned[raw.record_id] = record
                created += 1
            if (created + updated) % 500 == 0:
                db.flush()

        db.flush()
        return {
            "postings_seen": len(postings),
            "cleaned_created": created,
            "cleaned_updated": updated,
            "cleaned_skipped": skipped,
        }

    def extract_and_map_job_skills(
        self, db: Session, limit: int = 10000, offset: int = 0, sources: Optional[List[str]] = None
    ) -> Dict[str, int]:
        postings = db.query(JobPosting).order_by(JobPosting.created_at.asc(), JobPosting.posting_id.asc())
        if sources:
            postings = postings.filter(JobPosting.source.in_(list(sources)))
        postings = postings.offset(offset).limit(limit).all()

        skills_created = 0
        aliases_created = 0
        mappings_created = 0
        mappings_skipped = 0

        skill_cache = {skill.skill_key: skill for skill in db.query(Skill).filter(Skill.status == "active").all()}
        esco_skill_cache = {
            str(row.skill_id): row.esco_skill_id
            for row in (
                db.query(ESCOSkill).filter(ESCOSkill.skill_id.isnot(None)).all()
            )
        }
        alias_cache = {
            (str(alias.skill_id), alias.normalised_alias)
            for alias in db.query(SkillAlias).filter(SkillAlias.is_active.is_(True)).all()
        }
        existing_mapping_hashes = {
            row[0]
            for row in (
                db.query(SkillMapping.source_text_hash)
                .filter(
                    SkillMapping.source_domain == "labour_market",
                    SkillMapping.source_entity_type == "job_posting",
                )
                .all()
            )
            if row[0]
        }

        for posting in postings:
            candidates = self.job_skill_candidates(posting)
            for candidate in candidates:
                skill_key = slugify_skill(candidate.text)
                skill = skill_cache.get(skill_key)
                if not skill:
                    skill = Skill(
                        skill_key=skill_key,
                        name=candidate.text[:255],
                        category="job_posting",
                        description=f"Canonical skill inferred from labour-market job postings: {candidate.text}",
                        status="active",
                        skill_metadata={
                            "source": "labour_market_job_pipeline",
                            "first_seen_job_id": posting.job_id,
                            "candidate_source": candidate.source,
                        },
                    )
                    db.add(skill)
                    db.flush()
                    skill_cache[skill_key] = skill
                    skills_created += 1

                alias_key = (str(skill.skill_id), normalise_text(candidate.text)[:255])
                if alias_key not in alias_cache:
                    db.add(
                        SkillAlias(
                            skill_id=skill.skill_id,
                            alias=candidate.text[:255],
                            normalised_alias=normalise_text(candidate.text)[:255],
                            language="en",
                            source="labour_market_job_pipeline",
                            confidence_weight=candidate.confidence,
                            is_active=True,
                        )
                    )
                    alias_cache.add(alias_key)
                    aliases_created += 1

                mapping_hash = stable_hash(
                    f"job_posting:{posting.posting_id}:{skill.skill_id}:{candidate.method}:{candidate.text.lower()}"
                )
                if mapping_hash in existing_mapping_hashes:
                    mappings_skipped += 1
                    continue

                evidence_text = self.mapping_evidence_text(posting, candidate.text)
                db.add(
                    SkillMapping(
                        skill_id=skill.skill_id,
                        esco_skill_id=esco_skill_cache.get(str(skill.skill_id)),
                        source_domain="labour_market",
                        source_entity_type="job_posting",
                        source_entity_id=posting.posting_id,
                        source_record_id=posting.job_id,
                        source_text_hash=mapping_hash,
                        matched_text=candidate.text[:255],
                        extraction_method=candidate.method,
                        confidence_score=candidate.confidence,
                        evidence_start=None,
                        evidence_end=None,
                        evidence_text=evidence_text,
                        mapping_status="candidate",
                        confidence_calibration={
                            "method": candidate.method,
                            "calibrated_score": candidate.confidence,
                            "calibration_version": "job_skill_pipeline_v1",
                        },
                        mapping_metadata={
                            "job_id": posting.job_id,
                            "posting_id": str(posting.posting_id),
                            "source": posting.source,
                            "source_url": posting.source_url,
                            "job_title": posting.job_title,
                            "posted_year": posting.posting_year,
                            "posted_quarter": posting.posting_quarter,
                            "candidate_source": candidate.source,
                        },
                    )
                )
                existing_mapping_hashes.add(mapping_hash)
                mappings_created += 1

            if mappings_created and mappings_created % 1000 == 0:
                db.commit()

        db.flush()
        return {
            "postings_seen": len(postings),
            "skills_created": skills_created,
            "aliases_created": aliases_created,
            "mappings_created": mappings_created,
            "mappings_skipped": mappings_skipped,
        }

    def generate_job_skill_signals(
        self, db: Session, limit: int = 10000, sources: Optional[List[str]] = None
    ) -> Dict[str, int]:
        rows_query = (
            db.query(SkillMapping, Skill, JobPosting)
            .join(Skill, SkillMapping.skill_id == Skill.skill_id)
            .join(JobPosting, SkillMapping.source_entity_id == JobPosting.posting_id)
            .filter(
                SkillMapping.source_domain == "labour_market",
                SkillMapping.source_entity_type == "job_posting",
                SkillMapping.mapping_status == "approved",
            )
        )
        if sources:
            rows_query = rows_query.filter(JobPosting.source.in_(list(sources)))
        rows = rows_query.order_by(SkillMapping.created_at.desc()).limit(limit).all()

        grouped: Dict[tuple[str, int, str], Dict[str, Any]] = {}
        for mapping, skill, posting in rows:
            quarter = f"Q{posting.posting_quarter}"
            key = (skill.skill_key, posting.posting_year, quarter)
            item = grouped.setdefault(
                key,
                {
                    "skill": skill,
                    "year": posting.posting_year,
                    "quarter": quarter,
                    "count": 0,
                    "sources": Counter(),
                    "titles": Counter(),
                    "confidence_total": 0.0,
                    "is_dpsa_public_service_proxy": True,
                    "is_trial_uat": False,
                },
            )
            item["count"] += 1
            item["sources"][posting.source or "unknown"] += 1
            item["titles"][posting.job_title] += 1
            item["confidence_total"] += float(mapping.confidence_score or 0.0)
            item["is_dpsa_public_service_proxy"] = item["is_dpsa_public_service_proxy"] and (
                (posting.source or "").strip().lower().startswith("dpsa")
            )
            item["is_trial_uat"] = item["is_trial_uat"] or "TRIAL_NOT_EMPIRICAL" in (posting.source or "").upper()

        existing_hashes = {
            row[0]
            for row in (
                db.query(LabourMarketSignal.signal_hash)
                .filter(LabourMarketSignal.method == "job_skill_demand_v1")
                .all()
            )
        }
        max_count = max((item["count"] for item in grouped.values()), default=1)
        created = 0
        updated = 0

        for item in grouped.values():
            skill = item["skill"]
            signal_hash = stable_hash(f"job_skill:{skill.skill_key}:{item['year']}:{item['quarter']}")
            demand_score = round(min(1.0, item["count"] / max_count), 4)
            confidence = round(min(0.98, item["confidence_total"] / max(item["count"], 1)), 4)
            proxy_scope = (
                "adzuna_trial_uat_not_empirical" if item["is_trial_uat"]
                else "public_service_vacancy_proxy" if item["is_dpsa_public_service_proxy"]
                else "job_vacancy_evidence"
            )
            representativeness_note = (
                "Adzuna South Africa vacancy data used under written academic research "
                "permission (2026-09-10); attribution to https://www.adzuna.co.za required "
                "in thesis, publication, research and examiner packages."
                if item["is_trial_uat"] else
                "DPSA public-service vacancy evidence only; not representative of the whole Western Cape or private-sector labour market."
                if item["is_dpsa_public_service_proxy"]
                else "Interpret within the scope and coverage of the contributing job-advert sources."
            )
            permission = ADZUNA_PERMISSION if item["is_trial_uat"] else {}
            payload = {
                "canonical_key": f"job_skill:{skill.skill_key}"[:120],
                "canonical_name": f"Job demand for {skill.name}"[:255],
                "signal_type": "job_skill_demand",
                "dimension_type": "skill",
                "dimension_value": skill.name[:255],
                "year": item["year"],
                "quarter": item["quarter"],
                "observed_value": float(item["count"]),
                "normalised_value": demand_score,
                "demand_score": demand_score,
                "confidence_score": confidence,
                "evidence_count": item["count"],
                "unit": "normalised_posting_count",
                "method": "job_skill_demand_v1",
                "source_summary": ", ".join(f"{source}: {count}" for source, count in item["sources"].most_common(5)),
                "signal_hash": signal_hash,
                "signal_metadata": {
                    "skill_id": str(skill.skill_id),
                    "skill_key": skill.skill_key,
                    "top_titles": item["titles"].most_common(5),
                    "source_counts": dict(item["sources"]),
                    "evidence_scope": proxy_scope,
                    "representativeness_note": representativeness_note,
                    "research_use": "academic_research_with_attribution" if item["is_trial_uat"]
                    else "technical_uat" if item["is_dpsa_public_service_proxy"]
                    else "empirical_subject_to_source_governance",
                    "empirical_use_permitted": not item["is_dpsa_public_service_proxy"],
                    "permission_status": permission.get("permission_status"),
                    "permission_received_at": permission.get("permission_received_at"),
                    "attribution_required": permission.get("attribution_required"),
                    "attribution_url": permission.get("attribution_url"),
                    "attribution_note": ADZUNA_ATTRIBUTION_NOTE if permission else None,
                    "evidence_path": permission.get("evidence_path"),
                },
            }
            existing = (
                db.query(LabourMarketSignal)
                .filter(LabourMarketSignal.signal_hash == signal_hash)
                .first()
            )
            if existing:
                for field, value in payload.items():
                    setattr(existing, field, value)
                updated += 1
            else:
                db.add(LabourMarketSignal(**payload))
                existing_hashes.add(signal_hash)
                created += 1

        db.flush()
        return {
            "mappings_seen": len(rows),
            "signals_seen": len(grouped),
            "signals_created": created,
            "signals_updated": updated,
            "promotion_gate": "approved_labour_mappings_only",
        }

    def generate_job_skill_demand_evidence(
        self, db: Session, limit: int = 10000, sources: Optional[List[str]] = None
    ) -> Dict[str, int]:
        signals_query = (
            db.query(LabourMarketSignal)
            .filter(LabourMarketSignal.method == "job_skill_demand_v1")
            .order_by(LabourMarketSignal.demand_score.desc(), LabourMarketSignal.evidence_count.desc())
            .limit(limit)
        )
        signals = signals_query.all()
        if sources:
            source_set = set(sources)
            signals = [
                signal for signal in signals
                if source_set & set((signal.signal_metadata or {}).get("source_counts", {}).keys())
            ]
        existing_hashes = {row[0] for row in db.query(SkillDemandEvidence.evidence_hash).all()}
        skills = {str(skill.skill_id): skill for skill in db.query(Skill).filter(Skill.status == "active").all()}

        created = 0
        skipped = 0
        for signal in signals:
            skill_id = (signal.signal_metadata or {}).get("skill_id")
            skill = skills.get(skill_id)
            if not skill:
                skipped += 1
                continue
            evidence_hash = stable_hash(f"job_skill_demand:{signal.signal_id}:{skill.skill_id}")
            if evidence_hash in existing_hashes:
                skipped += 1
                continue
            db.add(
                SkillDemandEvidence(
                    skill_id=skill.skill_id,
                    signal_id=signal.signal_id,
                    evidence_type="job_posting_skill_demand",
                    match_method="job_skill_demand_v1",
                    matched_context=f"{signal.canonical_name} ({signal.year} {signal.quarter})"[:255],
                    demand_score=signal.demand_score,
                    confidence_score=signal.confidence_score,
                    evidence_weight=min(1.0, max(0.1, signal.evidence_count / 100.0)),
                    rationale=(
                        f"{skill.name} appears in {signal.evidence_count} job posting skill mappings "
                        f"for {signal.year} {signal.quarter}."
                    ),
                    evidence_hash=evidence_hash,
                    evidence_metadata={
                        "skill_key": skill.skill_key,
                        "canonical_key": signal.canonical_key,
                        "canonical_name": signal.canonical_name,
                        "year": signal.year,
                        "quarter": signal.quarter,
                        "source_summary": signal.source_summary,
                        "job_skill_signal": True,
                        "evidence_scope": (signal.signal_metadata or {}).get("evidence_scope", "job_vacancy_evidence"),
                        "representativeness_note": (signal.signal_metadata or {}).get("representativeness_note"),
                        "research_use": (signal.signal_metadata or {}).get("research_use"),
                        "empirical_use_permitted": (signal.signal_metadata or {}).get(
                            "empirical_use_permitted", True
                        ),
                        "permission_status": (signal.signal_metadata or {}).get("permission_status"),
                        "permission_received_at": (signal.signal_metadata or {}).get("permission_received_at"),
                        "attribution_required": (signal.signal_metadata or {}).get("attribution_required"),
                        "attribution_url": (signal.signal_metadata or {}).get("attribution_url"),
                        "attribution_note": (signal.signal_metadata or {}).get("attribution_note"),
                        "evidence_path": (signal.signal_metadata or {}).get("evidence_path"),
                    },
                )
            )
            existing_hashes.add(evidence_hash)
            created += 1
        db.flush()
        return {
            "signals_seen": len(signals),
            "evidence_created": created,
            "evidence_skipped": skipped,
        }

    @staticmethod
    def raw_records_for_postings(db: Session, job_ids: Iterable[str]) -> Dict[str, RawIngestionRecord]:
        ids = list({job_id for job_id in job_ids if job_id})
        if not ids:
            return {}
        rows = (
            db.query(RawIngestionRecord)
            .filter(
                RawIngestionRecord.record_type == "job_advert_record",
                RawIngestionRecord.source_record_id.in_(ids),
            )
            .order_by(RawIngestionRecord.created_at.asc())
            .all()
        )
        result: Dict[str, RawIngestionRecord] = {}
        for row in rows:
            result.setdefault(row.source_record_id, row)
        return result

    @staticmethod
    def cleaned_payload(posting: JobPosting) -> Dict[str, Any]:
        skills = LabourMarketSkillPipelineService.skill_values(posting.required_skills)
        title = clean_text(posting.job_title)
        region = clean_text(posting.region)
        salary_min = float(posting.salary_min) if posting.salary_min is not None else None
        salary_max = float(posting.salary_max) if posting.salary_max is not None else None
        return {
            "job_id": posting.job_id,
            "job_title": title,
            "normalised_title": LabourMarketSkillPipelineService.normalise_job_title(title),
            "job_description": clean_text(posting.job_description),
            "skills": skills,
            "normalised_skills": [LabourMarketSkillPipelineService.normalise_skill_label(skill) for skill in skills],
            "region": region,
            "normalised_location": LabourMarketSkillPipelineService.normalise_location(region, posting.country),
            "country": posting.country,
            "employment_type": clean_text(posting.employment_type),
            "normalised_employment_type": LabourMarketSkillPipelineService.normalise_employment_type(posting.employment_type),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_midpoint": LabourMarketSkillPipelineService.salary_midpoint(salary_min, salary_max),
            "salary_band": LabourMarketSkillPipelineService.salary_band(salary_min, salary_max),
            "posted_date": posting.posted_date.isoformat() if posting.posted_date else None,
            "closed_date": posting.closed_date.isoformat() if posting.closed_date else None,
            "posting_year": posting.posting_year,
            "posting_quarter": posting.posting_quarter,
            "source": posting.source,
            "source_url": posting.source_url,
            "duplicate_fingerprint": LabourMarketSkillPipelineService.duplicate_fingerprint(posting),
        }

    @staticmethod
    def cleaning_metadata(posting: JobPosting) -> Dict[str, Any]:
        return {
            "normaliser": "job_advert_v1",
            "pipeline": "labour_market_skill_pipeline_v1",
            "has_description": bool(clean_text(posting.job_description)),
            "skill_count": len(LabourMarketSkillPipelineService.skill_values(posting.required_skills)),
            "normalisation_steps": [
                "job_title",
                "location",
                "employment_type",
                "salary",
                "skills",
                "duplicate_fingerprint",
            ],
        }

    @staticmethod
    def quality_score(posting: JobPosting) -> float:
        score = 0.35
        if clean_text(posting.job_title):
            score += 0.15
        if clean_text(posting.job_description):
            score += 0.20
        if LabourMarketSkillPipelineService.skill_values(posting.required_skills):
            score += 0.20
        if posting.source_url:
            score += 0.05
        if posting.posted_date:
            score += 0.05
        return round(min(score, 1.0), 4)

    @staticmethod
    def skill_values(required_skills: Optional[Dict[str, Any]]) -> List[str]:
        if not required_skills:
            return []
        values = required_skills.get("declared") if isinstance(required_skills, dict) else []
        if isinstance(values, str):
            values = re.split(r"[,;|]", values)
        if not isinstance(values, list):
            return []
        return [clean_text(value) for value in values if LabourMarketSkillPipelineService.is_valid_skill(value)]

    @staticmethod
    def is_valid_skill(value: Any) -> bool:
        text = clean_text(value)
        lowered = text.lower()
        return 2 < len(text) <= 80 and lowered not in GENERIC_SKILL_TERMS and not lowered.isdigit()

    def job_skill_candidates(self, posting: JobPosting) -> List[JobSkillCandidate]:
        candidates: Dict[str, JobSkillCandidate] = {}
        for value in self.skill_values(posting.required_skills)[:30]:
            key = normalise_text(value)
            candidates[key] = JobSkillCandidate(
                text=value,
                method="declared_job_skill",
                confidence=0.88,
                source="required_skills",
            )

        combined_text = normalise_text(f"{posting.job_title or ''} {posting.job_description or ''}")
        for skill_key, phrases in CURATED_TEXT_SKILLS.items():
            for phrase in phrases:
                if re.search(r"(?<![a-zA-Z0-9])" + re.escape(phrase) + r"(?![a-zA-Z0-9])", combined_text):
                    label = skill_key.replace("-", " ").title()
                    candidates.setdefault(
                        normalise_text(label),
                        JobSkillCandidate(
                            text=label,
                            method="curated_text_phrase",
                            confidence=0.72,
                            source="title_description",
                        ),
                    )
                    break
        return list(candidates.values())[:35]

    @staticmethod
    def mapping_evidence_text(posting: JobPosting, matched_text: str) -> str:
        title = clean_text(posting.job_title)
        description = clean_text(posting.job_description)
        if matched_text.lower() in description.lower():
            index = description.lower().find(matched_text.lower())
            return description[max(0, index - 120): index + len(matched_text) + 120]
        return title or description[:255]

    @staticmethod
    def normalise_job_title(value: str) -> str:
        text = normalise_text(value)
        text = re.sub(r"\b(senior|sr\.?|junior|jr\.?|lead|principal|remote|hybrid)\b", "", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def normalise_location(region: str, country: Optional[str]) -> Dict[str, Any]:
        text = clean_text(region)
        parts = [part.strip() for part in re.split(r"[,/|-]", text) if part.strip()]
        return {
            "raw": text,
            "city": parts[0] if parts else None,
            "region": parts[-1] if len(parts) > 1 else text or None,
            "country": (country or "").upper()[:2] or None,
        }

    @staticmethod
    def normalise_employment_type(value: Optional[str]) -> Optional[str]:
        text = normalise_text(value or "").replace(" ", "_")
        return EMPLOYMENT_TYPE_MAP.get(text, text or None)

    @staticmethod
    def salary_midpoint(min_value: Optional[float], max_value: Optional[float]) -> Optional[float]:
        if min_value is not None and max_value is not None:
            return round((min_value + max_value) / 2, 2)
        return min_value if min_value is not None else max_value

    @staticmethod
    def salary_band(min_value: Optional[float], max_value: Optional[float]) -> Optional[str]:
        midpoint = LabourMarketSkillPipelineService.salary_midpoint(min_value, max_value)
        if midpoint is None:
            return None
        if midpoint < 30000:
            return "low"
        if midpoint < 80000:
            return "medium"
        if midpoint < 150000:
            return "high"
        return "very_high"

    @staticmethod
    def normalise_skill_label(value: str) -> str:
        text = normalise_text(value)
        text = re.sub(r"\bskills?\b", "", text)
        text = re.sub(r"[^a-z0-9+#.]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def duplicate_fingerprint(posting: JobPosting) -> str:
        parts = [
            LabourMarketSkillPipelineService.normalise_job_title(posting.job_title or ""),
            normalise_text(posting.source or ""),
            normalise_text(posting.source_url or ""),
            normalise_text(posting.region or ""),
        ]
        return stable_hash("|".join(parts))


labour_market_skill_pipeline_service = LabourMarketSkillPipelineService()
