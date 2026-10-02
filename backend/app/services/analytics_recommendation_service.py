"""
Analytics and recommendation generation service.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

logger = logging.getLogger(__name__)

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.alignment_score import AlignmentScore
from app.models.curriculum_document import CurriculumDocument
from app.models.curriculum_document_version import CurriculumDocumentVersion
from app.models.curriculum_module import CurriculumModule
from app.models.document_chunk import DocumentChunk
from app.models.forecast import Forecast
from app.models.ingestion_job import IngestionJob
from app.models.job_posting import JobPosting
from app.models.labour_market_signal import LabourMarketSignal
from app.models.recommendation import Recommendation
from app.models.recommendation_explanation import RecommendationExplanation
from app.models.skill import Skill
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.skill_mapping import SkillMapping

from app.core.config import settings
from app.services.fairness_audit_service import (
    FairnessAuditService,
)
from app.services.model_dataset_snapshot_service import model_dataset_snapshot_service


class AnalyticsRecommendationService:
    """
    Generates alignment scores, forecasts, gaps, and recommendations.
    """

    USABLE_MAPPING_STATUSES = ("candidate", "approved", "needs_review")
    GAP_ALIGNMENT_THRESHOLD = 0.30
    REGIONAL_JOB_PATTERNS = ("%Western Cape%", "%Cape Town%", "%South Africa%")
    ICT_RELEVANCE_TERMS = (
        "ict", "information technology", "computing", "computer", "software", "programming",
        "developer", "software development", "applications development", "mobile application", "web", "database", "data",
        "analytics", "data analysis", "network", "cyber", "security", "cloud", "information systems",
        "multimedia", "communication networks", "artificial intelligence", "machine learning",
        "python", "java", "javascript", "sql", "linux", "devops", "api", "digital",
    )
    ICT_ALLOWED_CATEGORIES = {"digital", "analytical", "business", "transversal"}
    ICT_HIGH_VALUE_TERMS = {
        "software development": 1.00,
        "programming": 0.96,
        "python": 0.95,
        "java": 0.90,
        "javascript": 0.88,
        "sql": 0.94,
        "database": 0.92,
        "data analysis": 0.94,
        "machine learning": 0.92,
        "artificial intelligence": 0.90,
        "cloud": 0.88,
        "cybersecurity": 0.90,
        "network": 0.84,
        "api": 0.82,
        "devops": 0.84,
        "business intelligence": 0.86,
        "data visualisation": 0.82,
    }

    def generate_all(
        self,
        db: Session,
        version_id: Optional[UUID] = None,
        horizon_periods: int = 4,
    ) -> Dict[str, Any]:
        alignments = self.generate_alignment_scores(db, version_id=version_id)
        forecasts = self.generate_forecasts(db, horizon_periods=horizon_periods)
        recommendations = self.generate_recommendations(db, version_id=version_id)

        # Fairness audit (paper: demographic parity <= 0.1)
        audit = {}
        if settings.ENABLE_FAIRNESS_AUDIT:
            try:
                audit_service = FairnessAuditService(db)
                # Gather alignment scores for audit
                scores = (
                    db.query(AlignmentScore)
                    .order_by(AlignmentScore.created_at.desc())
                    .limit(200)
                    .all()
                )
                score_dicts = []
                for s in scores:
                    meta = s.score_metadata or {}
                    score_dicts.append({
                        "alignment_score": s.alignment_score,
                        "faculty": meta.get("faculty", "unknown"),
                    })
                audit = audit_service.audit_alignment_predictions(score_dicts)
                if audit.get("status") == "flagged":
                    logger.warning(
                        "[FAIRNESS] Alignment audit flagged: %s",
                        [c for c in audit.get("checks", []) if not c.get("passed")],
                    )
            except Exception as exc:
                logger.warning("[FAIRNESS] Audit failed: %s", exc)

        return {
            "alignments_created": alignments["alignments_created"],
            "forecasts_created": forecasts["forecasts_created"],
            "recommendations_created": recommendations["recommendations_created"],
            "fairness_audit": audit,
        }

    def generate_alignment_scores(
        self,
        db: Session,
        version_id: Optional[UUID] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        version_query = db.query(CurriculumDocumentVersion)
        if version_id:
            version_query = version_query.filter(CurriculumDocumentVersion.version_id == version_id)
        versions = version_query.order_by(CurriculumDocumentVersion.created_at.desc()).limit(100).all()

        all_labour_skill_ids = self.skill_ids_for_domain(db, "labour_market")

        # Pre-compute relevance contexts and labour skill IDs once.
        # For ICT profile, the filtered result is identical across all versions,
        # so we compute it once instead of per-version (avoids 39x multiplier).
        relevance_contexts = {v.version_id: self.alignment_relevance_context(db, v) for v in versions}
        ict_labour_ids: Optional[Set[UUID]] = None
        general_labour_ids: Optional[Set[UUID]] = None

        context_labour_ids: Dict[UUID, Set[UUID]] = {}
        for vid, ctx in relevance_contexts.items():
            if ctx.get("profile") == "ict":
                if ict_labour_ids is None:
                    ict_labour_ids = self.relevant_skill_ids_for_context(db, all_labour_skill_ids, ctx)
                context_labour_ids[vid] = ict_labour_ids
            else:
                if general_labour_ids is None:
                    general_labour_ids = self.relevant_skill_ids_for_context(db, all_labour_skill_ids, ctx)
                context_labour_ids[vid] = general_labour_ids

        created = 0

        for version in versions:
            relevance_context = relevance_contexts[version.version_id]
            labour_skill_ids = context_labour_ids[version.version_id]
            curriculum_skill_ids = self.curriculum_skill_ids_for_version(db, version.version_id)
            overlap = curriculum_skill_ids & labour_skill_ids
            missing = labour_skill_ids - curriculum_skill_ids
            union = curriculum_skill_ids | labour_skill_ids
            demand_weights = self.skill_demand_weights(db, union)
            weighted_overlap = sum(demand_weights.get(item, 1.0) for item in overlap)
            weighted_union = sum(demand_weights.get(item, 1.0) for item in union)
            alignment = weighted_overlap / weighted_union if weighted_union else 0.0
            gap = 1.0 - alignment if union else 1.0
            coverage_ratio = len(overlap) / max(len(labour_skill_ids), 1)
            evidence_volume = sum(1 for item in union if demand_weights.get(item, 1.0) > 1.0)
            confidence = min(0.96, 0.42 + (min(len(union), 50) / 100) + (min(evidence_volume, 25) / 100) + (coverage_ratio * 0.12))

            record = AlignmentScore(
                document_id=version.document_id,
                version_id=version.version_id,
                score_type="weighted_skill_overlap",
                alignment_score=round(alignment, 4),
                gap_score=round(gap, 4),
                curriculum_skill_count=len(curriculum_skill_ids),
                labour_market_skill_count=len(labour_skill_ids),
                overlapping_skill_count=len(overlap),
                missing_skill_count=len(missing),
                confidence_score=round(confidence, 4),
                model_version="weighted_jaccard_baseline_v2",
                status="generated",
                score_metadata={
                    "overlapping_skill_ids": [str(item) for item in overlap],
                    "missing_skill_ids": [str(item) for item in missing],
                    "method": "weighted_jaccard_overlap",
                    "model_family": "transparent_statistical_baseline",
                    "candidate_successor_models": ["xgboost_alignment_classifier"],
                    "weighted_overlap": round(weighted_overlap, 4),
                    "weighted_union": round(weighted_union, 4),
                    "coverage_ratio": round(coverage_ratio, 4),
                    "evidence_weighted_skill_count": evidence_volume,
                    "mapping_statuses_used": list(self.USABLE_MAPPING_STATUSES),
                    "relevance_profile": relevance_context["profile"],
                    "relevance_terms": relevance_context["matched_terms"],
                },
            )
            db.add(record)
            created += 1

        if commit:
            db.commit()
        return {"alignments_created": created}

    def skill_demand_weights(self, db: Session, skill_ids: Set[UUID]) -> Dict[UUID, float]:
        if not skill_ids:
            return {}
        rows = (
            db.query(
                SkillDemandEvidence.skill_id,
                func.count(SkillDemandEvidence.evidence_id),
                func.avg(SkillDemandEvidence.demand_score),
                func.avg(SkillDemandEvidence.confidence_score),
            )
            .filter(SkillDemandEvidence.skill_id.in_(list(skill_ids)))
            .group_by(SkillDemandEvidence.skill_id)
            .all()
        )
        weights = {skill_id: 1.0 for skill_id in skill_ids}
        for skill_id, count, avg_demand, avg_confidence in rows:
            weights[skill_id] = round(
                1.0
                + min(float(count or 0) / 25.0, 1.0)
                + (float(avg_demand or 0.0) * 0.75)
                + (float(avg_confidence or 0.0) * 0.35),
                4,
            )
        return weights

    def _forecast_provenance_dossier(self, db: Session) -> Dict[str, Any]:
        """Assemble the source/provenance dossier required in every forecast explanation.

        Computed once per generation run (not per skill) and merged into each
        forecast_payload so the explanation carries: query/source, ingestion job IDs,
        observation date range, record counts, deduplication rule, snapshot fingerprint,
        method, baselines, metric values, uncertainty and known limitations. Read-only:
        it never mutates signals, postings, jobs or snapshots.
        """
        # Ingestion job lineage feeding the labour-market evidence.
        ingestion_rows = (
            db.query(IngestionJob.job_id, IngestionJob.job_type, IngestionJob.status,
                     IngestionJob.records_loaded, IngestionJob.created_at)
            .filter(
                or_(
                    IngestionJob.job_type.like("adzuna%"),
                    IngestionJob.job_type.like("%labour%"),
                    IngestionJob.job_type.like("%job%"),
                )
            )
            .order_by(IngestionJob.created_at.desc())
            .limit(25)
            .all()
        )
        ingestion_job_ids = [str(row.job_id) for row in ingestion_rows]

        # Observation window + record counts from the job-posting evidence base.
        posting_agg = db.query(
            func.count(JobPosting.posting_id),
            func.min(JobPosting.posted_date),
            func.max(JobPosting.posted_date),
        ).first()
        posting_count = int(posting_agg[0] or 0) if posting_agg else 0
        posted_min = posting_agg[1] if posting_agg else None
        posted_max = posting_agg[2] if posting_agg else None
        source_rows = (
            db.query(JobPosting.source, func.count(JobPosting.posting_id))
            .filter(JobPosting.source.isnot(None))
            .group_by(JobPosting.source)
            .order_by(func.count(JobPosting.posting_id).desc())
            .limit(20)
            .all()
        )
        source_counts = {str(src): int(cnt) for src, cnt in source_rows if src}

        signal_count = db.query(func.count(LabourMarketSignal.signal_id)).scalar() or 0
        mapping_count = (
            db.query(func.count(SkillMapping.mapping_id))
            .filter(SkillMapping.source_domain == "labour_market")
            .filter(SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES))
            .scalar()
            or 0
        )

        # Reproducible dataset snapshot fingerprint (latest prepared snapshot).
        snapshot = model_dataset_snapshot_service.latest_snapshot(db)
        snapshot_fingerprint = snapshot.dataset_fingerprint if snapshot else None
        snapshot_id = str(snapshot.snapshot_id) if snapshot else None

        return {
            "query_source": {
                "description": (
                    "Canonical labour-demand signals derived from approved labour-market "
                    "skill mappings over imported job-posting evidence; curriculum coverage "
                    "from curriculum-domain mappings on active canonical skills."
                ),
                "job_posting_sources": source_counts,
                "primary_source_label": next(iter(source_counts), "unspecified"),
            },
            "ingestion_job_ids": ingestion_job_ids,
            "observation_window": {
                "earliest_posted_date": posted_min.isoformat() if posted_min else None,
                "latest_posted_date": posted_max.isoformat() if posted_max else None,
            },
            "record_counts": {
                "job_postings": posting_count,
                "labour_market_signals": int(signal_count),
                "usable_labour_mappings": int(mapping_count),
                "ingestion_jobs_referenced": len(ingestion_job_ids),
            },
            "deduplication_rule": (
                "Job postings are deduplicated on source+external job identifier at ingestion; "
                "canonical signals are deduplicated on signal_hash (skill_key|year|quarter); "
                "forecasts are unique per skill (latest generated row supersedes prior rows for "
                "display via uniqueForecastsBySkill, prior rows are retained append-only)."
            ),
            "dataset_snapshot_fingerprint": snapshot_fingerprint,
            "dataset_snapshot_id": snapshot_id,
            "method": "canonical_signal_weighted_baseline_v2",
            "baselines": {
                "model_family": "transparent_statistical_baseline",
                "naive_last_value": "previous forecast_value for the same skill (exponential smoothing anchor)",
                "candidate_successor_models": ["lstm_sequence_forecaster"],
            },
            "uncertainty": {
                "confidence_basis": (
                    "confidence_score blends labour-mapping volume and canonical-signal evidence "
                    "count; it is a transparent heuristic, not a calibrated predictive interval."
                ),
                "backtest_status": "pending_longer_history",
            },
            "known_limitations": [
                "Transparent statistical baseline only; not an empirically validated ML forecaster.",
                "Adzuna trial/UAT and DPSA public-service vacancy evidence is not representative of the whole Western Cape or private-sector labour market.",
                "Backtesting is pending longer forecast history; no calibrated prediction intervals are published.",
                "Projections are decision-support evidence and require human curriculum review before action.",
            ],
        }

    def generate_forecasts(
        self,
        db: Session,
        horizon_periods: int = 4,
        commit: bool = True,
    ) -> Dict[str, Any]:
        labour_counts = Counter()
        curriculum_counts = Counter()
        signal_summary = self.labour_signal_summary(db)
        provenance_dossier = self._forecast_provenance_dossier(db)

        top_evidence_skill_ids = {
            row[0]
            for row in (
                db.query(SkillDemandEvidence.skill_id)
                .join(Skill, SkillDemandEvidence.skill_id == Skill.skill_id)
                .filter(Skill.status == "active")
                .group_by(SkillDemandEvidence.skill_id)
                .order_by(func.count(SkillDemandEvidence.evidence_id).desc())
                .limit(500)
                .all()
            )
        }

        for mapping in (
            db.query(SkillMapping)
            .join(Skill, SkillMapping.skill_id == Skill.skill_id)
            .filter(
                SkillMapping.source_domain == "labour_market",
                SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES),
                Skill.status == "active",
            )
            .limit(50000)
            .all()
        ):
            labour_counts[mapping.skill_id] += 1

        for mapping in (
            db.query(SkillMapping)
            .filter(
                SkillMapping.source_domain == "curriculum",
                SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES),
            )
            .all()
        ):
            curriculum_counts[mapping.skill_id] += 1

        created = 0
        all_skill_ids = (set(labour_counts.keys()) | set(curriculum_counts.keys()) | top_evidence_skill_ids)
        if len(all_skill_ids) > 1000:
            ranked = Counter({skill_id: labour_counts.get(skill_id, 0) + (10 if skill_id in top_evidence_skill_ids else 0) for skill_id in all_skill_ids})
            all_skill_ids = {skill_id for skill_id, _ in ranked.most_common(1000)}

        for skill_id in all_skill_ids:
            labour_value = float(labour_counts.get(skill_id, 0))
            curriculum_value = float(curriculum_counts.get(skill_id, 0))
            signal_evidence = self.skill_demand_evidence_for_skill(db, skill_id, signal_summary)
            signal_pressure = float(signal_evidence["demand_score"])
            gap_pressure = max(0.0, labour_value - curriculum_value)
            baseline_value = max(labour_value, signal_evidence["evidence_count"] * signal_pressure)
            previous_forecasts = (
                db.query(Forecast)
                .filter(Forecast.skill_id == skill_id, Forecast.forecast_type == "skill_demand")
                .order_by(Forecast.created_at.desc())
                .limit(5)
                .all()
            )
            historical_values = [float(row.forecast_value or 0.0) for row in reversed(previous_forecasts)]
            smoothed_baseline = baseline_value
            alpha = 0.35
            for value in historical_values:
                smoothed_baseline = (alpha * value) + ((1 - alpha) * smoothed_baseline)
            growth_factor = 1.0 + min(
                0.45,
                ((gap_pressure / max(labour_value, 1.0)) * 0.18)
                + (signal_pressure * 0.22)
                + (min(len(historical_values), 5) / 5 * 0.05),
            )
            forecast_value = smoothed_baseline * growth_factor

            observed_trend = self.observed_skill_trend(db, skill_id)
            if observed_trend.get("available"):
                direction = observed_trend["direction"]
                change_rate = max(-0.45, min(0.45, observed_trend["qoq_growth_percent"] / 100.0))
                forecast_value = max(0.0, baseline_value * (1.0 + change_rate))
            elif forecast_value > baseline_value * 1.05:
                direction = "increasing"
            elif forecast_value < baseline_value * 0.95:
                direction = "decreasing"
            else:
                direction = "stable"

            confidence = min(
                0.94,
                0.45
                + min(labour_value, 20.0) / 60.0
                + min(signal_evidence["evidence_count"], 25) / 100.0,
            )
            explanation_fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "skill_id": str(skill_id),
                        "baseline_value": round(baseline_value, 4),
                        "forecast_value": round(forecast_value, 4),
                        "method": "canonical_signal_weighted_baseline_v2",
                        "canonical_signal_keys": signal_evidence["canonical_keys"],
                        "signal_ids": signal_evidence.get("signal_ids", []),
                        "evidence_ids": signal_evidence.get("evidence_ids", []),
                        "historical_forecast_points": len(historical_values),
                        "observed_trend": observed_trend,
                        "horizon_periods": horizon_periods,
                    },
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            signal_window = signal_evidence.get("observation_window")
            window_text = (
                f"observation window {signal_window['year_range'][0]}-{signal_window['year_range'][1]} "
                f"across {signal_window['count']} signal records"
                if signal_window and signal_window.get("year_range")
                else "no canonical signal window available"
            )
            forecast = Forecast(
                skill_id=skill_id,
                forecast_type="skill_demand",
                horizon_periods=horizon_periods,
                baseline_value=round(baseline_value, 4),
                forecast_value=round(forecast_value, 4),
                trend_direction=direction,
                confidence_score=round(confidence, 4),
                method="canonical_signal_weighted_baseline_v2",
                forecast_payload={
                    "labour_mapping_count": labour_value,
                    "curriculum_mapping_count": curriculum_value,
                    "canonical_signal_count": signal_evidence["evidence_count"],
                    "canonical_signal_score": round(signal_pressure, 4),
                    "canonical_signal_keys": signal_evidence["canonical_keys"],
                    "evidence_record_ids": signal_evidence.get("evidence_ids", []),
                    "signal_record_ids": signal_evidence.get("signal_ids", []),
                    "observation_window": signal_window,
                    "explanation_fingerprint": explanation_fingerprint,
                    "gap_pressure": gap_pressure,
                    "smoothed_baseline": round(smoothed_baseline, 4),
                    "smoothing_alpha": alpha,
                    "historical_forecast_points": len(historical_values),
                    "observed_demand_trend": observed_trend,
                    "model_family": "transparent_statistical_baseline",
                    "candidate_successor_models": ["lstm_sequence_forecaster"],
                    "backtest_status": "pending_longer_history" if len(historical_values) < 4 else "history_available",
                    "provenance": provenance_dossier,
                    "trajectory": [
                        {
                            "period": index,
                            "value": round(
                                smoothed_baseline
                                + ((forecast_value - smoothed_baseline) * index / horizon_periods),
                                4,
                            ),
                        }
                        for index in range(1, horizon_periods + 1)
                    ],
                },
                explanation=(
                    f"Forecast is based on labour-market skill evidence, curriculum coverage, canonical demand "
                    f"signals ({signal_evidence['evidence_count']}; {window_text}), and exponential-smoothing "
                    f"history where available. Method canonical_signal_weighted_baseline_v2 "
                    f"(transparent_statistical_baseline); sources "
                    f"{', '.join(list(provenance_dossier['query_source']['job_posting_sources'].keys())[:3]) or 'unspecified'} "
                    f"over {provenance_dossier['record_counts']['job_postings']} job postings and "
                    f"{provenance_dossier['record_counts']['labour_market_signals']} canonical signals; "
                    f"observation window "
                    f"{provenance_dossier['observation_window']['earliest_posted_date'] or 'n/a'} to "
                    f"{provenance_dossier['observation_window']['latest_posted_date'] or 'n/a'}; "
                    f"ingestion jobs {', '.join(provenance_dossier['ingestion_job_ids'][:3]) or 'n/a'}; "
                    f"dataset snapshot fingerprint "
                    f"{(provenance_dossier['dataset_snapshot_fingerprint'] or 'n/a')[:16]}; "
                    f"confidence {round(confidence, 4)} (heuristic, not a calibrated interval); "
                    f"backtest pending longer history. Supporting evidence record IDs, deduplication rule, "
                    f"baselines, uncertainty and known limitations are in the forecast payload with "
                    f"explanation fingerprint {explanation_fingerprint}."
                ),
                status="generated",
            )
            db.add(forecast)
            created += 1

        if commit:
            db.commit()
        return {"forecasts_created": created}


    def recommendation_scope_context(self, db: Session, alignment: AlignmentScore) -> Dict[str, Any]:
        document = None
        version = None
        if alignment.document_id:
            document = db.query(CurriculumDocument).filter(CurriculumDocument.document_id == alignment.document_id).first()
        if alignment.version_id:
            version = db.query(CurriculumDocumentVersion).filter(CurriculumDocumentVersion.version_id == alignment.version_id).first()

        chunk_rows = []
        if alignment.version_id:
            chunk_rows = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.version_id == alignment.version_id)
                .order_by(DocumentChunk.chunk_index.asc())
                .limit(500)
                .all()
            )
        module_ids = {chunk.module_id for chunk in chunk_rows if chunk.module_id}
        module_by_id = {}
        if module_ids:
            module_by_id = {
                module.module_id: module
                for module in db.query(CurriculumModule).filter(CurriculumModule.module_id.in_(list(module_ids))).all()
            }
        module_counts: Counter[str] = Counter()
        module_names: Dict[str, str] = {}
        for chunk in chunk_rows:
            metadata = chunk.chunk_metadata or {}
            module_code = metadata.get("module_code")
            module_name = metadata.get("module_name")
            if chunk.module_id and chunk.module_id in module_by_id:
                module = module_by_id[chunk.module_id]
                module_code = module.module_code or module_code
                module_name = module.module_name or module_name
            if not module_code:
                continue
            module_counts[module_code] += 1
            if module_name:
                module_names[module_code] = module_name

        modules = [
            {"module_code": code, "module_name": module_names.get(code), "chunk_count": count}
            for code, count in module_counts.most_common(8)
        ]
        module_scope = modules[0]["module_code"] if len(modules) == 1 else "programme_level"
        module_label = (
            f"{modules[0]['module_code']} - {modules[0].get('module_name') or modules[0]['module_code']}"
            if len(modules) == 1
            else "Programme-level / multiple modules"
        )
        programme = document.programme if document else None
        department = document.department if document else None
        faculty = document.faculty if document else None
        document_title = document.title if document else None
        evidence_type = None
        if version and version.extraction_metadata:
            evidence_type = (version.extraction_metadata.get("structure_summary") or {}).get("document_evidence_type")
        return {
            "faculty": faculty,
            "department": department,
            "programme": programme or "Unassigned programme",
            "module_scope": module_scope,
            "module_label": module_label,
            "modules": modules,
            "document_title": document_title,
            "document_key": document.document_key if document else None,
            "version_number": version.version_number if version else None,
            "document_evidence_type": evidence_type,
        }

    def recommendation_group_key(
        self,
        scope: Dict[str, Any],
        skill: Skill,
        recommendation_type: str,
    ) -> str:
        parts = [
            scope.get("programme") or "unassigned-programme",
            scope.get("module_scope") or "programme_level",
            skill.skill_key or str(skill.skill_id),
            recommendation_type,
        ]
        return "|".join(re.sub(r"[^a-z0-9]+", "-", str(part).lower()).strip("-") or "unknown" for part in parts)

    def ict_value_score(self, skill: Skill, relevance_context: Optional[Dict[str, Any]] = None) -> float:
        text = " ".join(filter(None, [skill.skill_key, skill.name, skill.category, skill.description])).lower()
        score = 0.0
        for term, weight in self.ICT_HIGH_VALUE_TERMS.items():
            if self.text_has_relevance_term(text, term):
                score = max(score, float(weight))
        if skill.category in {"digital", "analytical"}:
            score = max(score, 0.72)
        if relevance_context and relevance_context.get("profile") == "ict" and score:
            score = min(1.0, score + 0.05)
        return round(score, 4)

    def recommendation_priority_score(
        self,
        alignment: AlignmentScore,
        skill: Skill,
        labour_evidence_count: int,
        demand_evidence: Dict[str, Any],
        latest_forecast: Optional[Forecast],
        relevance_context: Optional[Dict[str, Any]],
    ) -> float:
        demand_score = float(demand_evidence["average_demand_score"] or 0.0)
        demand_count = int(demand_evidence["evidence_count"] or 0)
        evidence_strength = min(max(labour_evidence_count, demand_count), 40) / 40
        forecast_confidence = latest_forecast.confidence_score if latest_forecast else 0.45
        ict_score = self.ict_value_score(skill, relevance_context)
        score = min(
            1.0,
            (float(alignment.gap_score or 0.0) * 0.34)
            + (evidence_strength * 0.20)
            + (demand_score * 0.20)
            + (float(forecast_confidence or 0.0) * 0.10)
            + (ict_score * 0.16),
        )
        return round(score, 4)

    def grouped_recommendations(
        self,
        db: Session,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        query = db.query(Recommendation)
        if status:
            query = query.filter(Recommendation.status == status)
        rows = (
            query.order_by(Recommendation.priority_score.desc(), Recommendation.created_at.desc())
            .limit(min(max(limit, 1), 500) * 3)
            .all()
        )
        groups: Dict[str, Dict[str, Any]] = {}
        for recommendation in rows:
            metadata = dict(recommendation.recommendation_metadata or {})
            if not metadata.get("programme") and recommendation.alignment_id:
                alignment = db.query(AlignmentScore).filter(AlignmentScore.alignment_id == recommendation.alignment_id).first()
                skill = db.query(Skill).filter(Skill.skill_id == recommendation.skill_id).first() if recommendation.skill_id else None
                if alignment and skill:
                    scope = self.recommendation_scope_context(db, alignment)
                    metadata.update(
                        {
                            "programme": scope.get("programme"),
                            "department": scope.get("department"),
                            "faculty": scope.get("faculty"),
                            "module_scope": scope.get("module_scope"),
                            "module_label": scope.get("module_label"),
                            "affected_modules": scope.get("modules"),
                            "document_title": scope.get("document_title"),
                            "document_evidence_type": scope.get("document_evidence_type"),
                            "skill_name": skill.name,
                            "skill_key": skill.skill_key,
                        }
                    )
                    metadata["group_key"] = metadata.get("group_key") or self.recommendation_group_key(scope, skill, recommendation.recommendation_type)
                    recommendation.recommendation_metadata = metadata
            group_key = metadata.get("group_key") or "|".join(
                [
                    str(metadata.get("programme") or recommendation.document_id or "unassigned"),
                    str(metadata.get("module_scope") or "programme_level"),
                    str(metadata.get("skill_key") or recommendation.skill_id or "unknown"),
                    str(recommendation.recommendation_type),
                ]
            )
            group = groups.setdefault(
                group_key,
                {
                    "group_key": group_key,
                    "programme": metadata.get("programme") or "Unassigned programme",
                    "department": metadata.get("department"),
                    "faculty": metadata.get("faculty"),
                    "module_scope": metadata.get("module_scope") or "programme_level",
                    "module_label": metadata.get("module_label") or "Programme-level / multiple modules",
                    "skill_key": metadata.get("skill_key"),
                    "skill_name": metadata.get("skill_name"),
                    "recommendation_type": recommendation.recommendation_type,
                    "recommendation_count": 0,
                    "version_count": 0,
                    "document_count": 0,
                    "highest_priority_score": 0.0,
                    "priority": recommendation.priority,
                    "status_counts": {},
                    "versions": set(),
                    "documents": set(),
                    "recommendations": [],
                    "representative": recommendation,
                },
            )
            group["recommendation_count"] += 1
            group["highest_priority_score"] = max(group["highest_priority_score"], float(recommendation.priority_score or 0.0))
            group["status_counts"][recommendation.status] = group["status_counts"].get(recommendation.status, 0) + 1
            if recommendation.version_id:
                group["versions"].add(str(recommendation.version_id))
            if recommendation.document_id:
                group["documents"].add(str(recommendation.document_id))
            if float(recommendation.priority_score or 0.0) > float(group["representative"].priority_score or 0.0):
                group["representative"] = recommendation
                group["priority"] = recommendation.priority
            if len(group["recommendations"]) < 8:
                group["recommendations"].append(recommendation)

        result_groups = []
        for group in groups.values():
            group["version_count"] = len(group.pop("versions"))
            group["document_count"] = len(group.pop("documents"))
            result_groups.append(group)
        result_groups.sort(key=lambda item: (item["highest_priority_score"], item["recommendation_count"]), reverse=True)
        return {
            "total_recommendations_considered": len(rows),
            "group_count": len(result_groups),
            "groups": result_groups[: min(max(limit, 1), 500)],
        }

    def generate_recommendations(
        self,
        db: Session,
        version_id: Optional[UUID] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        alignment_query = db.query(AlignmentScore)
        if version_id:
            alignment_query = alignment_query.filter(AlignmentScore.version_id == version_id)
        alignment_rows = alignment_query.order_by(AlignmentScore.created_at.desc()).limit(100).all()
        latest_by_version: Dict[str, AlignmentScore] = {}
        for alignment in alignment_rows:
            key = str(alignment.version_id or alignment.document_id or alignment.alignment_id)
            if key not in latest_by_version:
                latest_by_version[key] = alignment
        alignments = list(latest_by_version.values())

        created = 0
        superseded_stale = 0
        for alignment in alignments:
            if not self.alignment_is_actionable_curriculum(db, alignment):
                superseded_stale += self.supersede_all_pending_recommendations_for_alignment(
                    db=db,
                    alignment=alignment,
                    reason="Broad prospectus or all-programme source is not actionable curriculum for recommendation approval.",
                )
                continue
            scope_context = self.recommendation_scope_context(db, alignment)
            relevance_context = self.alignment_context_from_score(db, alignment)
            missing_ids = [UUID(item) for item in alignment.score_metadata.get("missing_skill_ids", [])]
            candidate_ids = missing_ids
            if not candidate_ids and alignment.gap_score >= 0.35:
                candidate_ids = [
                    UUID(item)
                    for item in alignment.score_metadata.get("overlapping_skill_ids", [])
                ]
            superseded_stale += self.supersede_stale_pending_recommendations(
                db=db,
                alignment=alignment,
                current_candidate_ids=set(candidate_ids),
            )

            for skill_id in candidate_ids[:10]:
                skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
                if not skill:
                    continue
                demand_evidence = self.demand_evidence_summary_for_skill(db, skill_id)

                recommendation_type = (
                    "add_skill" if skill_id in missing_ids else "strengthen_skill"
                )
                group_key = self.recommendation_group_key(scope_context, skill, recommendation_type)
                existing_pending = (
                    db.query(Recommendation)
                    .filter(
                        Recommendation.status == "pending_review",
                        Recommendation.skill_id == skill_id,
                        Recommendation.recommendation_type == recommendation_type,
                        Recommendation.recommendation_metadata["group_key"].astext == group_key,
                    )
                    .order_by(Recommendation.priority_score.desc(), Recommendation.created_at.desc())
                    .first()
                )
                if existing_pending:
                    self.refresh_recommendation_evidence(
                        db=db,
                        recommendation=existing_pending,
                        alignment=alignment,
                        skill=skill,
                        demand_evidence=demand_evidence,
                        scope_context=scope_context,
                        group_key=group_key,
                    )
                    continue

                latest_forecast = (
                    db.query(Forecast)
                    .filter(Forecast.skill_id == skill_id, Forecast.forecast_type == "skill_demand")
                    .order_by(Forecast.created_at.desc())
                    .first()
                )
                labour_evidence_count = self.mapping_count(db, "labour_market", skill_id)
                demand_score = demand_evidence["average_demand_score"]
                demand_count = demand_evidence["evidence_count"]
                zero_evidence = (
                    demand_count == 0 and labour_evidence_count == 0 and not demand_evidence.get("top_evidence")
                )
                evidence_status = "insufficient_evidence" if zero_evidence else "supported"
                ict_value_score = self.ict_value_score(skill, relevance_context)
                priority_score = self.recommendation_priority_score(
                    alignment=alignment,
                    skill=skill,
                    labour_evidence_count=labour_evidence_count,
                    demand_evidence=demand_evidence,
                    latest_forecast=latest_forecast,
                    relevance_context=relevance_context,
                )
                priority = "high" if priority_score >= 0.7 else "medium" if priority_score >= 0.4 else "low"
                evidence_status_note = (
                    "No available labour-market source records, demand rows, or canonical signals could be "
                    "resolved for this skill at generation time; do not represent this as strong evidence."
                    if zero_evidence
                    else "Recommendation is connected to labour-market evidence records captured at generation time."
                )

                recommendation = Recommendation(
                    alignment_id=alignment.alignment_id,
                    forecast_id=latest_forecast.forecast_id if latest_forecast else None,
                    skill_id=skill.skill_id,
                    document_id=alignment.document_id,
                    version_id=alignment.version_id,
                    recommendation_type=recommendation_type,
                    title=(
                        f"Add curriculum coverage for {skill.name}"
                        if skill_id in missing_ids
                        else f"Strengthen labour-market alignment for {skill.name}"
                    ),
                    description=(
                        f"Add, strengthen, or make explicit curriculum outcomes related to {skill.name} "
                        "because alignment analysis and labour-market demand evidence indicate a material "
                        "curriculum-labour gap. "
                        + ("Evidence basis is insufficient; treat as a curriculum-gap observation only." if zero_evidence else "")
                    ),
                    priority=priority,
                    priority_score=round(priority_score, 4),
                    confidence_score=round(
                        min(0.96, alignment.confidence_score + 0.05 + (demand_evidence["average_confidence"] * 0.10)),
                        4,
                    ),
                    status="pending_review",
                    recommendation_metadata={
                        "skill_key": skill.skill_key,
                        "gap_type": "missing" if skill_id in missing_ids else "weak_alignment",
                        "gap_score": alignment.gap_score,
                        "labour_evidence_count": labour_evidence_count,
                        "skill_demand_evidence_count": demand_count,
                        "skill_demand_score": round(demand_score, 4),
                        "canonical_signal_keys": demand_evidence["canonical_signal_keys"],
                        "top_demand_evidence": demand_evidence["top_evidence"],
                        "evidence_status": evidence_status,
                        "evidence_status_note": evidence_status_note,
                        "actionable": not zero_evidence,
                        "non_actionable_reason": (
                            "Zero resolvable labour-market evidence at generation time; approval "
                            "is blocked until demand-evidence generation re-supports this "
                            "recommendation. Retained non-actionable, never deleted."
                            if zero_evidence else None
                        ),
                        "group_key": group_key,
                        "programme": scope_context.get("programme"),
                        "department": scope_context.get("department"),
                        "faculty": scope_context.get("faculty"),
                        "module_scope": scope_context.get("module_scope"),
                        "module_label": scope_context.get("module_label"),
                        "affected_modules": scope_context.get("modules"),
                        "document_title": scope_context.get("document_title"),
                        "document_evidence_type": scope_context.get("document_evidence_type"),
                        "skill_name": skill.name,
                        "ict_value_score": ict_value_score,
                        "priority_components": {
                            "gap_score": alignment.gap_score,
                            "labour_evidence_count": labour_evidence_count,
                            "skill_demand_evidence_count": demand_count,
                            "skill_demand_score": round(demand_score, 4),
                            "forecast_confidence": latest_forecast.confidence_score if latest_forecast else None,
                            "ict_value_score": ict_value_score,
                        },
                    },
                )
                db.add(recommendation)
                db.flush()

                db.add(
                    RecommendationExplanation(
                        recommendation_id=recommendation.recommendation_id,
                        explanation_type="rationale",
                        explanation_text=(
                            f"{skill.name} is connected to labour-market demand evidence and this curriculum "
                            "version shows a measurable alignment gap. Human reviewers should confirm whether "
                            "the skill is sufficiently explicit in outcomes, assessments, or module content."
                            if evidence_status == "supported"
                            else (
                                f"{skill.name} appears in curriculum alignment analysis for this version, but no "
                                "labour-market source records, demand rows, or canonical signals could be resolved. "
                                "Evidence status: insufficient_evidence. Re-run demand evidence generation before "
                                "using this recommendation as evidence-backed."
                            )
                        ),
                        evidence={
                            "alignment_id": str(alignment.alignment_id),
                            "forecast_id": str(latest_forecast.forecast_id) if latest_forecast else None,
                            "labour_evidence_count": labour_evidence_count,
                            "skill_demand_evidence_count": demand_count,
                            "skill_demand_score": round(demand_score, 4),
                            "canonical_signal_keys": demand_evidence["canonical_signal_keys"],
                            "top_demand_evidence": demand_evidence["top_evidence"],
                            "evidence_status": evidence_status,
                            "evidence_status_note": evidence_status_note,
                            "alignment_score": alignment.alignment_score,
                            "gap_score": alignment.gap_score,
                        },
                        confidence_score=recommendation.confidence_score,
                    )
                )
                created += 1

        superseded = self.supersede_duplicate_pending_recommendations(db) + superseded_stale
        self.remove_duplicate_recommendation_explanations(db)
        if commit:
            db.commit()
        return {"recommendations_created": created, "recommendations_superseded": superseded}

    @classmethod
    def classify_skill_alignment(cls, curriculum_count: int, labour_count: int) -> tuple[str, float]:
        """Classify evidence coverage without relying on stale alignment metadata."""
        if curriculum_count <= 0:
            return "missing", 0.0
        coverage = min(1.0, curriculum_count / max(labour_count, 1))
        if coverage < cls.GAP_ALIGNMENT_THRESHOLD:
            return "weak_alignment", coverage
        return "aligned", coverage

    @classmethod
    def regional_job_filter(cls):
        """Use explicit location text because legacy global rows defaulted country to ZA."""
        return or_(*(JobPosting.region.ilike(pattern) for pattern in cls.REGIONAL_JOB_PATTERNS))

    def observed_skill_trend(self, db: Session, skill_id: UUID) -> Dict[str, Any]:
        """Calculate direction from chronological demand evidence, not a fixed growth label."""
        rows = (
            db.query(
                LabourMarketSignal.year,
                LabourMarketSignal.quarter,
                func.avg(SkillDemandEvidence.demand_score),
            )
            .join(SkillDemandEvidence, SkillDemandEvidence.signal_id == LabourMarketSignal.signal_id)
            .filter(SkillDemandEvidence.skill_id == skill_id)
            .filter(func.coalesce(LabourMarketSignal.signal_metadata["superseded_reason"].astext, "") == "")
            .group_by(LabourMarketSignal.year, LabourMarketSignal.quarter)
            .all()
        )
        periods = []
        for year, quarter, score in rows:
            match = re.search(r"(\d+)", str(quarter or ""))
            quarter_number = int(match.group(1)) if match else 0
            periods.append((int(year or 0), quarter_number, float(score or 0.0)))
        periods.sort(key=lambda item: (item[0], item[1]))
        if len(periods) < 2:
            return {"available": False, "direction": None, "qoq_growth_percent": None, "periods": len(periods)}
        previous, current = periods[-2], periods[-1]
        change_rate = (current[2] - previous[2]) / max(abs(previous[2]), 1e-9)
        direction = "increasing" if change_rate > 0.05 else "decreasing" if change_rate < -0.05 else "stable"
        return {
            "available": True,
            "direction": direction,
            "qoq_growth_percent": round(change_rate * 100, 2),
            "previous_period": f"{previous[0]} Q{previous[1]}",
            "current_period": f"{current[0]} Q{current[1]}",
            "previous_score": round(previous[2], 4),
            "current_score": round(current[2], 4),
            "periods": len(periods),
        }

    @staticmethod
    def employer_name(posting: JobPosting, mapping: SkillMapping) -> Optional[str]:
        metadata = mapping.mapping_metadata or {}
        for key in ("company", "employer", "organisation", "organization", "sector", "industry"):
            value = metadata.get(key)
            if value:
                return str(value).strip()
        skills_payload = posting.required_skills if isinstance(posting.required_skills, dict) else {}
        for key in ("company", "employer", "sector", "industry"):
            value = skills_payload.get(key)
            if value:
                return str(value).strip()
        url = posting.source_url or ""
        match = re.search(r"-at-([a-z0-9%-]+?)-(?:\d{7,})(?:[/?]|$)", url, flags=re.IGNORECASE)
        if match:
            return re.sub(r"[-_]+", " ", match.group(1)).strip().title()
        return None

    def regional_job_insights(self, rows: List[tuple[SkillMapping, JobPosting]]) -> Dict[str, Any]:
        posting_by_id = {posting.posting_id: (mapping, posting) for mapping, posting in rows}
        postings = [pair[1] for pair in posting_by_id.values()]
        period_counts = Counter((posting.posting_year, posting.posting_quarter) for posting in postings)
        periods = sorted(period_counts)
        qoq_growth = None
        if len(periods) >= 2:
            previous, current = periods[-2], periods[-1]
            previous_count = period_counts[previous]
            current_count = period_counts[current]
            qoq_growth = round(((current_count - previous_count) / max(previous_count, 1)) * 100, 2)
        employers = Counter(
            name for mapping, posting in posting_by_id.values()
            if (name := self.employer_name(posting, mapping))
        )
        return {
            "job_count": len(postings),
            "qoq_growth_percent": qoq_growth,
            "periods_available": len(periods),
            "latest_period": f"{periods[-1][0]} Q{periods[-1][1]}" if periods else None,
            "top_employers_or_sectors": [name for name, _ in employers.most_common(3)],
            "regional_scope": "Western Cape and explicitly South African locations",
        }

    def dynamic_skill_why_text(
        self,
        skill_name: str,
        gap_type: str,
        curriculum_count: int,
        regional_insights: Dict[str, Any],
        observed_trend: Dict[str, Any],
    ) -> str:
        job_count = int(regional_insights.get("job_count") or 0)
        qoq = regional_insights.get("qoq_growth_percent")
        employers = regional_insights.get("top_employers_or_sectors") or []
        coverage_text = {
            "missing": "has no validated curriculum mapping",
            "weak_alignment": f"has only {curriculum_count} curriculum mapping(s) relative to labour evidence",
            "aligned": f"has {curriculum_count} curriculum mapping(s) and meets the 30% evidence-coverage threshold",
        }.get(gap_type, f"has {curriculum_count} curriculum mapping(s)")
        if job_count == 0:
            labour_text = "No mapped Western Cape or explicitly South African job record is currently available for this skill"
        else:
            labour_text = f"{job_count} mapped regional job record(s) are available"
        if qoq is not None:
            labour_text += f", with quarter-on-quarter volume changing by {qoq:+.1f}%"
        elif observed_trend.get("qoq_growth_percent") is not None:
            labour_text += f", while the linked demand-signal score changed by {observed_trend['qoq_growth_percent']:+.1f}% quarter on quarter"
        else:
            labour_text += "; there is not yet enough regional quarterly history to calculate growth"
        employer_text = f" Top represented employers or sectors are {', '.join(employers)}." if employers else " Employer or sector metadata is not available in the retained regional records."
        return f"{skill_name} {coverage_text}. {labour_text}.{employer_text}"

    def skill_gap_summary(
        self,
        db: Session,
        version_id: Optional[UUID] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        alignment_query = db.query(AlignmentScore)
        if version_id:
            alignment_query = alignment_query.filter(AlignmentScore.version_id == version_id)
        max_alignment_versions = min(max(limit, 1), 3)
        alignment_rows = (
            alignment_query
            .order_by(AlignmentScore.created_at.desc())
            .limit(max_alignment_versions)
            .all()
        )

        latest_by_version: Dict[str, AlignmentScore] = {}
        for alignment in alignment_rows:
            key = str(alignment.version_id or alignment.document_id or alignment.alignment_id)
            if key not in latest_by_version:
                latest_by_version[key] = alignment

        gaps: List[Dict[str, Any]] = []
        total_candidate_count = 0
        candidate_window_size = min(max(limit * 2, 5), 15)
        max_alignment_versions = min(max(limit, 1), 3)
        target_enriched_candidates = min(max(limit * 2, 5), 12)
        for alignment in list(latest_by_version.values())[:max_alignment_versions]:
            relevance_context = self.alignment_context_from_score(db, alignment)
            raw_missing_ids = [UUID(item) for item in alignment.score_metadata.get("missing_skill_ids", [])]
            raw_weak_ids = [UUID(item) for item in alignment.score_metadata.get("overlapping_skill_ids", [])]
            if (alignment.score_metadata or {}).get("relevance_profile"):
                missing_ids = raw_missing_ids
                weak_ids = raw_weak_ids
            else:
                missing_ids = list(self.relevant_skill_ids_for_context(db, set(raw_missing_ids), relevance_context))
                weak_ids = list(self.relevant_skill_ids_for_context(db, set(raw_weak_ids), relevance_context))
            candidates = [(skill_id, "unclassified") for skill_id in missing_ids[:candidate_window_size]]
            candidates.extend((skill_id, "unclassified") for skill_id in weak_ids[:min(25, candidate_window_size)])

            candidate_skill_ids = [skill_id for skill_id, _ in candidates]
            candidate_context = self.skill_gap_candidate_context(db, alignment, candidate_skill_ids)

            for skill_id, _ in candidates:
                skill = candidate_context["skills"].get(skill_id)
                if not skill:
                    continue
                demand = candidate_context["demand_summaries"].get(skill_id, self.empty_demand_summary())
                forecast = candidate_context["forecasts"].get(skill_id)
                pending_recommendations = candidate_context["pending_counts"].get(skill_id, 0)
                labour_count = max(candidate_context["mapping_counts"].get(("labour_market", skill_id), 0), demand["evidence_count"])
                curriculum_count = candidate_context["mapping_counts"].get(("curriculum", skill_id), 0)
                gap_type, coverage = self.classify_skill_alignment(curriculum_count, labour_count)
                if gap_type != "aligned":
                    total_candidate_count += 1
                demand_score = float(demand["average_demand_score"] or 0.0)
                observed_trend = self.observed_skill_trend(db, skill_id)
                forecast_trend = observed_trend.get("direction") or (forecast.trend_direction if forecast else None)
                why_text = self.skill_gap_why_text(
                    skill_name=skill.name,
                    gap_type=gap_type,
                    labour_count=labour_count,
                    curriculum_count=curriculum_count,
                    demand_score=demand_score,
                    evidence_count=demand["evidence_count"],
                    forecast_trend=forecast_trend,
                )
                priority_score = min(
                    1.0,
                    (float(alignment.gap_score or 0.0) * 0.40)
                    + (min(max(labour_count, demand["evidence_count"]), 25) / 25 * 0.25)
                    + (demand_score * 0.25)
                    + ((forecast.confidence_score if forecast else 0.4) * 0.10),
                )
                gaps.append(
                    {
                        "alignment_id": str(alignment.alignment_id),
                        "document_id": str(alignment.document_id) if alignment.document_id else None,
                        "version_id": str(alignment.version_id) if alignment.version_id else None,
                        "skill_id": str(skill.skill_id),
                        "skill_key": skill.skill_key,
                        "skill_name": skill.name,
                        "gap_type": gap_type,
                        "alignment_score": alignment.alignment_score,
                        "gap_score": alignment.gap_score,
                        "coverage_ratio": round(coverage, 4),
                        "coverage_threshold": self.GAP_ALIGNMENT_THRESHOLD,
                        "priority_score": round(priority_score, 4),
                        "labour_mapping_count": labour_count,
                        "curriculum_mapping_count": curriculum_count,
                        "skill_demand_evidence_count": demand["evidence_count"],
                        "skill_demand_score": round(demand_score, 4),
                        "forecast_trend": forecast_trend,
                        "forecast_value": forecast.forecast_value if forecast else None,
                        "observed_trend": observed_trend,
                        "pending_recommendations": pending_recommendations,
                        "canonical_signal_keys": demand["canonical_signal_keys"],
                        "top_demand_evidence": demand["top_evidence"][:3],
                        "why_this_skill_matters": why_text,
                    }
                )
                if len(gaps) >= target_enriched_candidates:
                    break
            if len(gaps) >= target_enriched_candidates:
                break

        gaps.sort(key=lambda item: item["priority_score"], reverse=True)
        return {
            "alignment_versions_considered": len(latest_by_version),
            "gaps_returned": min(len(gaps), limit),
            "total_gap_candidates": total_candidate_count,
            "enriched_gap_candidates": len(gaps),
            "mapping_statuses_used": list(self.USABLE_MAPPING_STATUSES),
            "gaps": gaps[:limit],
        }

    def skill_gap_why_text(
        self,
        skill_name: str,
        gap_type: str,
        labour_count: int,
        curriculum_count: int,
        demand_score: float,
        evidence_count: int,
        forecast_trend: Optional[str],
    ) -> str:
        demand_label = "strong" if demand_score >= 0.70 else "moderate" if demand_score >= 0.40 else "emerging"
        curriculum_label = "not yet visible in curriculum evidence" if curriculum_count == 0 else "weakly represented in curriculum evidence"
        trend = f" and forecasts are {forecast_trend}" if forecast_trend else ""
        if gap_type == "missing":
            return (
                f"{skill_name} matters because labour-market evidence shows {demand_label} demand "
                f"({labour_count} mappings, {evidence_count} demand records{trend}) while it is {curriculum_label}."
            )
        if gap_type == "aligned":
            return (
                f"{skill_name} is represented in curriculum and labour evidence "
                f"({curriculum_count} curriculum mappings and {labour_count} labour mappings{trend})."
            )
        return (
            f"{skill_name} appears in both curriculum and labour-market data, but curriculum coverage "
            f"is below the {self.GAP_ALIGNMENT_THRESHOLD:.0%} evidence threshold ({labour_count} labour mappings, "
            f"{curriculum_count} curriculum mappings, {demand_label} demand{trend})."
        )

    def skill_gap_evidence_detail(
        self,
        db: Session,
        skill_id: UUID,
        version_id: Optional[UUID] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        if not skill:
            return {"skill_id": str(skill_id), "found": False, "message": "Skill not found"}

        curriculum_query = (
            db.query(SkillMapping)
            .filter(SkillMapping.skill_id == skill_id)
            .filter(SkillMapping.source_domain == "curriculum")
            .filter(SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES))
            .order_by(SkillMapping.confidence_score.desc(), SkillMapping.created_at.desc())
        )
        all_curriculum_query = curriculum_query
        curriculum_scope = "all validated curriculum evidence"
        if version_id:
            version_chunk_ids = db.query(DocumentChunk.chunk_id).filter(DocumentChunk.version_id == version_id)
            scoped_query = curriculum_query.filter(
                or_(
                    SkillMapping.mapping_metadata["version_id"].astext == str(version_id),
                    SkillMapping.source_entity_id == version_id,
                    SkillMapping.source_entity_id.in_(version_chunk_ids),
                )
            )
            scoped_total = scoped_query.count()
            if scoped_total:
                curriculum_query = scoped_query
                curriculum_scope = "selected curriculum version"
            else:
                curriculum_query = all_curriculum_query
                curriculum_scope = "all validated curriculum evidence (no mapping existed in the selected version)"
        curriculum_total = curriculum_query.count()
        curriculum_mappings = curriculum_query.limit(limit).all()

        chunk_ids = []
        for mapping in curriculum_mappings:
            metadata = mapping.mapping_metadata or {}
            if mapping.source_entity_type in {"document_chunk", "chunk"} and mapping.source_entity_id:
                chunk_ids.append(mapping.source_entity_id)
            if metadata.get("chunk_id"):
                try:
                    chunk_ids.append(UUID(str(metadata.get("chunk_id"))))
                except ValueError:
                    pass
        chunks = {
            chunk.chunk_id: chunk
            for chunk in db.query(DocumentChunk).filter(DocumentChunk.chunk_id.in_(chunk_ids)).all()
        } if chunk_ids else {}

        curriculum_evidence: List[Dict[str, Any]] = []
        for mapping in curriculum_mappings:
            metadata = mapping.mapping_metadata or {}
            chunk = chunks.get(mapping.source_entity_id)
            if not chunk and metadata.get("chunk_id"):
                try:
                    chunk = chunks.get(UUID(str(metadata.get("chunk_id"))))
                except ValueError:
                    chunk = None
            version = chunk.version if chunk else None
            document = version.document if version else None
            curriculum_evidence.append(
                {
                    "source_category": "curriculum",
                    "mapping_id": str(mapping.mapping_id),
                    "confidence_score": mapping.confidence_score,
                    "matched_text": mapping.matched_text,
                    "evidence_text": mapping.evidence_text or (chunk.content[:500] if chunk else ""),
                    "source_entity_type": mapping.source_entity_type,
                    "source_entity_id": str(mapping.source_entity_id) if mapping.source_entity_id else None,
                    "document_title": document.title if document else None,
                    "programme": document.programme if document else None,
                    "module": metadata.get("module_code") or ((chunk.chunk_metadata or {}).get("module_code") if chunk else None),
                    "page_start": chunk.page_start if chunk else None,
                    "chunk_id": str(chunk.chunk_id) if chunk else None,
                    "version_id": str(version.version_id) if version else None,
                }
            )

        regional_job_query = (
            db.query(SkillMapping, JobPosting)
            .join(
                JobPosting,
                and_(
                    SkillMapping.source_entity_type.in_(["job_posting", "posting"]),
                    SkillMapping.source_entity_id == JobPosting.posting_id,
                ),
            )
            .filter(SkillMapping.skill_id == skill_id)
            .filter(SkillMapping.source_domain.in_(["labour_market", "job_board", "jobs"]))
            .filter(SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES))
            .filter(self.regional_job_filter())
            .order_by(JobPosting.posted_date.desc(), SkillMapping.confidence_score.desc())
        )
        regional_job_total = regional_job_query.count()
        all_regional_job_rows = regional_job_query.all()
        regional_insights = self.regional_job_insights(all_regional_job_rows)
        regional_job_rows = all_regional_job_rows[:limit]
        current_job_evidence = []
        for mapping, posting in regional_job_rows:
            employer = self.employer_name(posting, mapping)
            current_job_evidence.append(
                {
                    "source_category": "current_jobs",
                    "mapping_id": str(mapping.mapping_id),
                    "confidence_score": mapping.confidence_score,
                    "matched_text": mapping.matched_text,
                    "evidence_text": mapping.evidence_text or "",
                    "job_title": posting.job_title,
                    "company_or_source": employer or "Employer not retained",
                    "region": posting.region,
                    "country": posting.country,
                    "posted_date": posting.posted_date.isoformat() if posting.posted_date else None,
                    "source_url": posting.source_url,
                    "posting_id": str(posting.posting_id),
                }
            )

        demand_evidence_rows = (
            db.query(SkillDemandEvidence)
            .filter(SkillDemandEvidence.skill_id == skill_id)
            .order_by(SkillDemandEvidence.demand_score.desc(), SkillDemandEvidence.confidence_score.desc())
            .limit(limit)
            .all()
        )
        signal_ids = [row.signal_id for row in demand_evidence_rows]
        signals = {
            signal.signal_id: signal
            for signal in db.query(LabourMarketSignal).filter(LabourMarketSignal.signal_id.in_(signal_ids)).all()
        } if signal_ids else {}
        job_trend_evidence = []
        for evidence in demand_evidence_rows:
            signal = signals.get(evidence.signal_id)
            job_trend_evidence.append(
                {
                    "source_category": "job_trends",
                    "evidence_id": str(evidence.evidence_id),
                    "evidence_type": evidence.evidence_type,
                    "matched_context": evidence.matched_context,
                    "demand_score": evidence.demand_score,
                    "confidence_score": evidence.confidence_score,
                    "rationale": evidence.rationale,
                    "canonical_key": signal.canonical_key if signal else None,
                    "canonical_name": signal.canonical_name if signal else None,
                    "dimension": f"{signal.dimension_type}: {signal.dimension_value}" if signal else None,
                    "period": f"{signal.year} {signal.quarter}" if signal else None,
                    "source_summary": signal.source_summary if signal else None,
                }
            )

        latest_forecast = (
            db.query(Forecast)
            .filter(Forecast.skill_id == skill_id)
            .order_by(Forecast.created_at.desc())
            .first()
        )
        # Alignment coverage is based on all usable labour mappings. Regional job rows
        # are a presentation/evidence scope and must not change the analytical denominator.
        labour_count = int(
            db.query(func.count(SkillMapping.mapping_id))
            .filter(
                SkillMapping.skill_id == skill_id,
                SkillMapping.source_domain.in_(["labour_market", "job_board", "jobs"]),
                SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES),
            )
            .scalar()
            or 0
        )
        curriculum_count = curriculum_total
        gap_type, coverage = self.classify_skill_alignment(curriculum_count, labour_count)
        observed_trend = self.observed_skill_trend(db, skill_id)
        why_text = self.dynamic_skill_why_text(
            skill_name=skill.name,
            gap_type=gap_type,
            curriculum_count=curriculum_count,
            regional_insights=regional_insights,
            observed_trend=observed_trend,
        )
        return {
            "found": True,
            "skill": {
                "skill_id": str(skill.skill_id),
                "skill_key": skill.skill_key,
                "name": skill.name,
                "category": skill.category,
            },
            "gap_type": gap_type,
            "coverage_ratio": round(coverage, 4),
            "coverage_threshold": self.GAP_ALIGNMENT_THRESHOLD,
            "curriculum_scope": curriculum_scope,
            "regional_job_insights": regional_insights,
            "observed_trend": observed_trend,
            "why_this_skill_matters": why_text,
            "source_groups": {
                "curriculum": curriculum_evidence,
                "job_trends": job_trend_evidence,
                "current_jobs": current_job_evidence,
            },
            "counts": {
                "curriculum": curriculum_total,
                "curriculum_displayed": len(curriculum_evidence),
                "job_trends": len(job_trend_evidence),
                "labour_mappings_total": labour_count,
                "current_jobs": regional_job_total,
                "current_jobs_displayed": len(current_job_evidence),
            },
        }

    def alignment_relevance_context(
        self,
        db: Session,
        version: CurriculumDocumentVersion,
    ) -> Dict[str, Any]:
        document = (
            db.query(CurriculumDocument)
            .filter(CurriculumDocument.document_id == version.document_id)
            .first()
        )
        text_parts = []
        if document:
            text_parts.extend([
                document.title or "",
                document.faculty or "",
                document.department or "",
                document.programme or "",
                document.description or "",
            ])
            if document.document_metadata:
                text_parts.append(" ".join(str(value) for value in document.document_metadata.values()))
        if version.extraction_metadata:
            text_parts.append(" ".join(str(value) for value in version.extraction_metadata.values()))
        context_text = " ".join(text_parts).lower()
        matched_terms = [term.strip() for term in self.ICT_RELEVANCE_TERMS if self.text_has_relevance_term(context_text, term)]
        if matched_terms:
            return {"profile": "ict", "matched_terms": sorted(set(matched_terms)), "context_text": context_text}
        return {"profile": "general", "matched_terms": [], "context_text": context_text}

    def alignment_context_from_score(self, db: Session, alignment: AlignmentScore) -> Dict[str, Any]:
        metadata = alignment.score_metadata or {}
        profile = metadata.get("relevance_profile")
        if profile:
            return {
                "profile": profile,
                "matched_terms": metadata.get("relevance_terms") or [],
                "context_text": " ".join(metadata.get("relevance_terms") or []).lower(),
            }
        if alignment.version_id:
            version = db.query(CurriculumDocumentVersion).filter(CurriculumDocumentVersion.version_id == alignment.version_id).first()
            if version:
                return self.alignment_relevance_context(db, version)
        return {"profile": "general", "matched_terms": [], "context_text": ""}

    def relevant_skill_ids_for_context(
        self,
        db: Session,
        skill_ids: Set[UUID],
        relevance_context: Dict[str, Any],
    ) -> Set[UUID]:
        if relevance_context.get("profile") == "general":
            return skill_ids
        rows = db.query(Skill).filter(Skill.skill_id.in_(list(skill_ids)), Skill.status == "active").all()
        return {skill.skill_id for skill in rows if self.skill_matches_context(skill, relevance_context)}

    def skill_id_matches_context(self, db: Session, skill_id: UUID, relevance_context: Dict[str, Any]) -> bool:
        if relevance_context.get("profile") == "general":
            return True
        skill = db.query(Skill).filter(Skill.skill_id == skill_id, Skill.status == "active").first()
        return self.skill_matches_context(skill, relevance_context) if skill else False

    def skill_matches_context(self, skill: Skill, relevance_context: Dict[str, Any]) -> bool:
        if relevance_context.get("profile") == "general":
            return True
        if relevance_context.get("profile") != "ict":
            return True
        if skill.category in self.ICT_ALLOWED_CATEGORIES:
            return True
        skill_text = " ".join(
            filter(None, [skill.skill_key, skill.name, skill.category, skill.description])
        ).lower()
        return any(self.text_has_relevance_term(skill_text, term) for term in self.ICT_RELEVANCE_TERMS)

    @staticmethod
    def text_has_relevance_term(text: str, term: str) -> bool:
        cleaned_term = term.strip().lower()
        if not cleaned_term:
            return False
        if " " in cleaned_term:
            return cleaned_term in text
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(cleaned_term) + r"(?![a-z0-9])", text))
    def skill_gap_candidate_context(
        self,
        db: Session,
        alignment: AlignmentScore,
        skill_ids: List[UUID],
    ) -> Dict[str, Any]:
        if not skill_ids:
            return {"skills": {}, "forecasts": {}, "pending_counts": {}, "mapping_counts": {}, "demand_summaries": {}}

        skills = {
            skill.skill_id: skill
            for skill in (
                db.query(Skill)
                .filter(Skill.skill_id.in_(skill_ids), Skill.status == "active")
                .all()
            )
        }

        mapping_counts = {
            (source_domain, skill_id): int(count or 0)
            for source_domain, skill_id, count in (
                db.query(
                    SkillMapping.source_domain,
                    SkillMapping.skill_id,
                    func.count(SkillMapping.mapping_id),
                )
                .filter(
                    SkillMapping.skill_id.in_(skill_ids),
                    SkillMapping.source_domain.in_(["curriculum", "labour_market"]),
                    SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES),
                )
                .group_by(SkillMapping.source_domain, SkillMapping.skill_id)
                .all()
            )
        }

        forecasts = {}
        for forecast in (
            db.query(Forecast)
            .filter(Forecast.skill_id.in_(skill_ids), Forecast.forecast_type == "skill_demand")
            .order_by(Forecast.created_at.desc())
            .all()
        ):
            if forecast.skill_id not in forecasts:
                forecasts[forecast.skill_id] = forecast

        pending_counts = {}
        if alignment.version_id:
            for skill_id, count in (
                db.query(Recommendation.skill_id, func.count(Recommendation.recommendation_id))
                .filter(
                    Recommendation.version_id == alignment.version_id,
                    Recommendation.skill_id.in_(skill_ids),
                    Recommendation.status == "pending_review",
                )
                .group_by(Recommendation.skill_id)
                .all()
            ):
                pending_counts[skill_id] = int(count or 0)

        demand_summaries = {skill_id: self.empty_demand_summary() for skill_id in skill_ids}
        for skill_id, count, average_demand, average_confidence in (
            db.query(
                SkillDemandEvidence.skill_id,
                func.count(SkillDemandEvidence.evidence_id),
                func.avg(SkillDemandEvidence.demand_score),
                func.avg(SkillDemandEvidence.confidence_score),
            )
            .filter(SkillDemandEvidence.skill_id.in_(skill_ids))
            .group_by(SkillDemandEvidence.skill_id)
            .all()
        ):
            demand_summaries[skill_id].update(
                {
                    "evidence_count": int(count or 0),
                    "average_demand_score": float(average_demand or 0.0),
                    "average_confidence": float(average_confidence or 0.0),
                }
            )

        for evidence in (
            db.query(SkillDemandEvidence)
            .filter(SkillDemandEvidence.skill_id.in_(skill_ids))
            .order_by(SkillDemandEvidence.demand_score.desc(), SkillDemandEvidence.confidence_score.desc())
            .limit(max(len(skill_ids) * 6, 20))
            .all()
        ):
            summary = demand_summaries.setdefault(evidence.skill_id, self.empty_demand_summary())
            canonical_key = (evidence.evidence_metadata or {}).get("canonical_key")
            if canonical_key and canonical_key not in summary["canonical_signal_keys"]:
                summary["canonical_signal_keys"].append(canonical_key)
            if len(summary["top_evidence"]) < 3:
                summary["top_evidence"].append(
                    {
                        "evidence_id": str(evidence.evidence_id),
                        "signal_id": str(evidence.signal_id),
                        "matched_context": evidence.matched_context,
                        "demand_score": evidence.demand_score,
                        "confidence_score": evidence.confidence_score,
                        "rationale": evidence.rationale,
                        "canonical_key": canonical_key,
                        "dimension_type": (evidence.evidence_metadata or {}).get("dimension_type"),
                        "dimension_value": (evidence.evidence_metadata or {}).get("dimension_value"),
                    }
                )

        return {
            "skills": skills,
            "forecasts": forecasts,
            "pending_counts": pending_counts,
            "mapping_counts": mapping_counts,
            "demand_summaries": demand_summaries,
        }

    @staticmethod
    def empty_demand_summary() -> Dict[str, Any]:
        return {
            "evidence_count": 0,
            "average_demand_score": 0.0,
            "average_confidence": 0.0,
            "canonical_signal_keys": [],
            "top_evidence": [],
        }

    def summary(self, db: Session) -> Dict[str, Any]:
        return {
            "alignment_scores": db.query(func.count(AlignmentScore.alignment_id)).scalar() or 0,
            "forecasts": db.query(func.count(Forecast.forecast_id)).scalar() or 0,
            "recommendations": db.query(func.count(Recommendation.recommendation_id)).scalar() or 0,
            "labour_market_signals": db.query(func.count(LabourMarketSignal.signal_id)).scalar() or 0,
            "skill_demand_evidence": db.query(func.count(SkillDemandEvidence.evidence_id)).scalar() or 0,
            "recommendation_explanations": (
                db.query(func.count(RecommendationExplanation.explanation_id)).scalar() or 0
            ),
        }

    def skill_ids_for_domain(self, db: Session, source_domain: str) -> Set[UUID]:
        rows = (
            db.query(SkillMapping.skill_id)
            .join(Skill, SkillMapping.skill_id == Skill.skill_id)
            .filter(
                SkillMapping.source_domain == source_domain,
                SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES),
            )
            .filter(Skill.status == "active")
            .distinct()
            .all()
        )
        skill_ids = {row[0] for row in rows}
        if source_domain == "labour_market":
            evidence_rows = (
                db.query(SkillDemandEvidence.skill_id)
                .join(Skill, SkillDemandEvidence.skill_id == Skill.skill_id)
                .filter(Skill.status == "active")
                .distinct()
                .all()
            )
            skill_ids.update(row[0] for row in evidence_rows)
        return skill_ids

    def curriculum_skill_ids_for_version(self, db: Session, version_id: UUID) -> Set[UUID]:
        rows = (
            db.query(SkillMapping.skill_id)
            .join(Skill, SkillMapping.skill_id == Skill.skill_id)
            .filter(
                SkillMapping.source_domain == "curriculum",
                SkillMapping.mapping_metadata["version_id"].astext == str(version_id),
                SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES),
                Skill.status == "active",
            )
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    def mapping_count(self, db: Session, source_domain: str, skill_id: UUID) -> int:
        return (
            db.query(func.count(SkillMapping.mapping_id))
            .filter(
                SkillMapping.source_domain == source_domain,
                SkillMapping.skill_id == skill_id,
                SkillMapping.mapping_status.in_(self.USABLE_MAPPING_STATUSES),
            )
            .scalar()
            or 0
        )

    def labour_signal_summary(self, db: Session) -> Dict[str, Any]:
        signals = (
            db.query(LabourMarketSignal)
            .filter(func.coalesce(LabourMarketSignal.signal_metadata["superseded_reason"].astext, "") == "")
            .all()
        )
        if not signals:
            return {
                "average_demand_score": 0.0,
                "average_confidence": 0.0,
                "count": 0,
                "canonical_keys": [],
                "by_dimension": {},
            }

        by_dimension: Dict[str, List[LabourMarketSignal]] = {}
        for signal in signals:
            by_dimension.setdefault(signal.dimension_type or "category", []).append(signal)

        return {
            "average_demand_score": sum(signal.demand_score for signal in signals) / len(signals),
            "average_confidence": sum(signal.confidence_score for signal in signals) / len(signals),
            "count": len(signals),
            "canonical_keys": sorted({signal.canonical_key for signal in signals}),
            "by_dimension": {
                key: sum(signal.demand_score for signal in values) / len(values)
                for key, values in by_dimension.items()
            },
        }

    def skill_demand_evidence_for_skill(
        self,
        db: Session,
        skill_id: UUID,
        signal_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        demand_rows = (
            db.query(SkillDemandEvidence)
            .join(Skill, SkillDemandEvidence.skill_id == Skill.skill_id)
            .filter(SkillDemandEvidence.skill_id == skill_id)
            .filter(Skill.status == "active")
            .order_by(SkillDemandEvidence.demand_score.desc())
            .limit(100)
            .all()
        )
        if demand_rows:
            total_weight = sum(max(row.evidence_weight, 0.01) for row in demand_rows)
            weighted_score = (
                sum(row.demand_score * max(row.evidence_weight, 0.01) for row in demand_rows)
                / total_weight
            )
            signal_ids = sorted({str(row.signal_id) for row in demand_rows})
            return {
                "demand_score": weighted_score,
                "evidence_count": len(demand_rows),
                "evidence_ids": [str(row.evidence_id) for row in demand_rows],
                "signal_ids": signal_ids,
                "observation_window": self._signal_window(db, signal_ids),
                "canonical_keys": sorted({
                    row.evidence_metadata.get("canonical_key")
                    for row in demand_rows
                    if row.evidence_metadata.get("canonical_key")
                }),
            }

        if not signal_summary.get("count"):
            return {
                "demand_score": 0.0,
                "evidence_count": 0,
                "evidence_ids": [],
                "signal_ids": [],
                "observation_window": None,
                "canonical_keys": [],
            }

        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        skill_text = " ".join(
            [
                skill.name if skill else "",
                skill.description if skill and skill.description else "",
                skill.skill_key if skill else "",
            ]
        ).lower()

        matched_signals = []
        if any(term in skill_text for term in ("data", "analysis", "analytics", "research", "statistics")):
            matched_signals = (
                db.query(LabourMarketSignal)
                .filter(LabourMarketSignal.canonical_key.in_(["employment_count", "labour_force"]))
                .filter(func.coalesce(LabourMarketSignal.signal_metadata["superseded_reason"].astext, "") == "")
                .all()
            )
        elif any(term in skill_text for term in ("management", "planning", "strategy", "policy")):
            matched_signals = (
                db.query(LabourMarketSignal)
                .filter(LabourMarketSignal.dimension_type.in_(["industry", "occupation"]))
                .filter(func.coalesce(LabourMarketSignal.signal_metadata["superseded_reason"].astext, "") == "")
                .all()
            )

        if not matched_signals:
            return {
                "demand_score": float(signal_summary["average_demand_score"]),
                "evidence_count": int(signal_summary["count"]),
                "evidence_ids": [],
                "signal_ids": [],
                "observation_window": None,
                "canonical_keys": signal_summary["canonical_keys"],
            }

        signal_ids = sorted({str(signal.signal_id) for signal in matched_signals})
        return {
            "demand_score": sum(signal.demand_score for signal in matched_signals) / len(matched_signals),
            "evidence_count": len(matched_signals),
            "evidence_ids": [],
            "signal_ids": signal_ids,
            "observation_window": self._signal_window(db, signal_ids),
            "canonical_keys": sorted({signal.canonical_key for signal in matched_signals}),
        }

    def _signal_window(self, db: Session, signal_ids: List[str]) -> Optional[Dict[str, Any]]:
        if not signal_ids:
            return None
        signal_rows = (
            db.query(LabourMarketSignal)
            .filter(LabourMarketSignal.signal_id.in_(signal_ids))
            .all()
        )
        if not signal_rows:
            return {
                "signal_ids": signal_ids,
                "count": 0,
                "note": "Referenced signals not resolvable in current database.",
            }
        years = sorted({signal.year for signal in signal_rows if signal.year})
        observed = sorted(
            {
                signal.observed_at
                for signal in signal_rows
                if getattr(signal, "observed_at", None) is not None
            }
        )
        source_keys = set()
        for signal in signal_rows:
            metadata = signal.signal_metadata or {}
            explicit_key = metadata.get("source_key")
            if explicit_key:
                source_keys.add(str(explicit_key))
            source_keys.update(str(key) for key in (metadata.get("source_counts") or {}).keys())
            if not explicit_key and not metadata.get("source_counts") and signal.source_summary:
                source_keys.add(str(signal.source_summary)[:200])
        return {
            "signal_ids": signal_ids,
            "count": len(signal_rows),
            "year_range": [years[0], years[-1]] if years else None,
            "observed_range": [
                observed[0].isoformat(),
                observed[-1].isoformat(),
            ] if observed else None,
            "source_keys": sorted(source_keys)[:20],
        }

    def demand_evidence_summary_for_skill(self, db: Session, skill_id: UUID) -> Dict[str, Any]:
        rows = (
            db.query(SkillDemandEvidence)
            .join(Skill, SkillDemandEvidence.skill_id == Skill.skill_id)
            .filter(SkillDemandEvidence.skill_id == skill_id)
            .filter(Skill.status == "active")
            .order_by(SkillDemandEvidence.demand_score.desc(), SkillDemandEvidence.confidence_score.desc())
            .limit(100)
            .all()
        )
        if not rows:
            return {
                "evidence_count": 0,
                "average_demand_score": 0.0,
                "average_confidence": 0.0,
                "canonical_signal_keys": [],
                "top_evidence": [],
            }

        return {
            "evidence_count": len(rows),
            "average_demand_score": sum(row.demand_score for row in rows) / len(rows),
            "average_confidence": sum(row.confidence_score for row in rows) / len(rows),
            "canonical_signal_keys": sorted({
                row.evidence_metadata.get("canonical_key")
                for row in rows
                if row.evidence_metadata.get("canonical_key")
            }),
            "top_evidence": [
                {
                    "evidence_id": str(row.evidence_id),
                    "signal_id": str(row.signal_id),
                    "matched_context": row.matched_context,
                    "demand_score": row.demand_score,
                    "confidence_score": row.confidence_score,
                    "rationale": row.rationale,
                    "canonical_key": row.evidence_metadata.get("canonical_key"),
                    "dimension_type": row.evidence_metadata.get("dimension_type"),
                    "dimension_value": row.evidence_metadata.get("dimension_value"),
                }
                for row in rows[:5]
            ],
        }

    def refresh_recommendation_evidence(
        self,
        db: Session,
        recommendation: Recommendation,
        alignment: AlignmentScore,
        skill: Skill,
        demand_evidence: Dict[str, Any],
        scope_context: Optional[Dict[str, Any]] = None,
        group_key: Optional[str] = None,
    ) -> None:
        metadata = dict(recommendation.recommendation_metadata or {})
        metadata.update(
            {
                "skill_demand_evidence_count": demand_evidence["evidence_count"],
                "skill_demand_score": round(demand_evidence["average_demand_score"], 4),
                "canonical_signal_keys": demand_evidence["canonical_signal_keys"],
                "top_demand_evidence": demand_evidence["top_evidence"],
                "evidence_refresh_method": "demand_evidence_v1",
                "group_key": group_key or metadata.get("group_key"),
            }
        )
        if scope_context:
            metadata.update(
                {
                    "programme": scope_context.get("programme"),
                    "department": scope_context.get("department"),
                    "faculty": scope_context.get("faculty"),
                    "module_scope": scope_context.get("module_scope"),
                    "module_label": scope_context.get("module_label"),
                    "affected_modules": scope_context.get("modules"),
                    "document_title": scope_context.get("document_title"),
                    "document_evidence_type": scope_context.get("document_evidence_type"),
                    "skill_name": skill.name,
                }
            )
        recommendation.recommendation_metadata = metadata

        exists = (
            db.query(RecommendationExplanation)
            .filter(
                RecommendationExplanation.recommendation_id == recommendation.recommendation_id,
                RecommendationExplanation.explanation_type == "demand_evidence",
            )
            .first()
        )
        if exists:
            exists.evidence = {
                "alignment_id": str(alignment.alignment_id),
                "skill_id": str(skill.skill_id),
                "skill_key": skill.skill_key,
                "skill_demand_evidence_count": demand_evidence["evidence_count"],
                "skill_demand_score": round(demand_evidence["average_demand_score"], 4),
                "canonical_signal_keys": demand_evidence["canonical_signal_keys"],
                "top_demand_evidence": demand_evidence["top_evidence"],
            }
            exists.confidence_score = round(min(0.96, recommendation.confidence_score + 0.03), 4)
            return

        db.add(
            RecommendationExplanation(
                recommendation_id=recommendation.recommendation_id,
                explanation_type="demand_evidence",
                explanation_text=(
                    f"{skill.name} has {demand_evidence['evidence_count']} linked labour-market "
                    "demand evidence records derived from canonical StatsSA signals."
                ),
                evidence={
                    "alignment_id": str(alignment.alignment_id),
                    "skill_id": str(skill.skill_id),
                    "skill_key": skill.skill_key,
                    "skill_demand_evidence_count": demand_evidence["evidence_count"],
                    "skill_demand_score": round(demand_evidence["average_demand_score"], 4),
                    "canonical_signal_keys": demand_evidence["canonical_signal_keys"],
                    "top_demand_evidence": demand_evidence["top_evidence"],
                },
                confidence_score=round(min(0.96, recommendation.confidence_score + 0.03), 4),
            )
        )

    def alignment_is_actionable_curriculum(self, db: Session, alignment: AlignmentScore) -> bool:
        if not alignment.version_id:
            return True
        version = db.query(CurriculumDocumentVersion).filter(CurriculumDocumentVersion.version_id == alignment.version_id).first()
        if not version:
            return True
        document = db.query(CurriculumDocument).filter(CurriculumDocument.document_id == version.document_id).first()
        if not document:
            return True
        context = " ".join(filter(None, [document.title, document.programme, document.department, document.faculty])).lower()
        if "all programmes" in context or "all faculties" in context:
            return False
        if "prospectus" in context and not any(term in context for term in ("ict", "information technology", "computing", "computer")):
            return False
        return True

    def supersede_all_pending_recommendations_for_alignment(
        self,
        db: Session,
        alignment: AlignmentScore,
        reason: str,
    ) -> int:
        if not alignment.version_id:
            return 0
        pending = (
            db.query(Recommendation)
            .filter(
                Recommendation.version_id == alignment.version_id,
                Recommendation.status == "pending_review",
            )
            .all()
        )
        superseded = 0
        for recommendation in pending:
            recommendation.status = "superseded"
            metadata = dict(recommendation.recommendation_metadata or {})
            metadata.update(
                {
                    "superseded_reason": reason,
                    "superseded_by_alignment_id": str(alignment.alignment_id),
                }
            )
            recommendation.recommendation_metadata = metadata
            superseded += 1
        return superseded
    def supersede_stale_pending_recommendations(
        self,
        db: Session,
        alignment: AlignmentScore,
        current_candidate_ids: Set[UUID],
    ) -> int:
        if not alignment.version_id:
            return 0
        pending = (
            db.query(Recommendation)
            .filter(
                Recommendation.version_id == alignment.version_id,
                Recommendation.status == "pending_review",
            )
            .all()
        )
        superseded = 0
        for recommendation in pending:
            if recommendation.skill_id in current_candidate_ids:
                continue
            recommendation.status = "superseded"
            metadata = dict(recommendation.recommendation_metadata or {})
            metadata.update(
                {
                    "superseded_reason": "Pending recommendation is no longer in the latest relevance-filtered alignment candidate set.",
                    "superseded_by_alignment_id": str(alignment.alignment_id),
                    "latest_relevance_profile": (alignment.score_metadata or {}).get("relevance_profile"),
                }
            )
            recommendation.recommendation_metadata = metadata
            superseded += 1
        return superseded
    def supersede_duplicate_pending_recommendations(self, db: Session) -> int:
        pending = (
            db.query(Recommendation)
            .filter(Recommendation.status == "pending_review")
            .order_by(Recommendation.priority_score.desc(), Recommendation.created_at.desc())
            .all()
        )
        seen = set()
        superseded = 0
        for recommendation in pending:
            metadata = recommendation.recommendation_metadata or {}
            key = metadata.get("group_key")
            if not key:
                key = "|".join(
                    [
                        str(metadata.get("programme") or recommendation.document_id or recommendation.version_id or ""),
                        str(metadata.get("module_scope") or "programme_level"),
                        str(metadata.get("skill_key") or recommendation.skill_id or ""),
                        str(recommendation.recommendation_type),
                    ]
                )
            if key not in seen:
                seen.add(key)
                if metadata.get("group_key") != key:
                    metadata["group_key"] = key
                    recommendation.recommendation_metadata = metadata
                continue
            recommendation.status = "superseded"
            metadata = dict(recommendation.recommendation_metadata or {})
            metadata["superseded_reason"] = "Duplicate grouped recommendation replaced by the highest-priority recommendation for the same programme/module/skill."
            metadata["duplicate_group_key"] = key
            recommendation.recommendation_metadata = metadata
            superseded += 1
        return superseded

    def remove_duplicate_recommendation_explanations(self, db: Session) -> int:
        explanations = (
            db.query(RecommendationExplanation)
            .order_by(RecommendationExplanation.created_at.desc())
            .all()
        )
        seen = set()
        removed = 0
        for explanation in explanations:
            key = (str(explanation.recommendation_id), explanation.explanation_type)
            if key not in seen:
                seen.add(key)
                continue
            db.delete(explanation)
            removed += 1
        return removed


analytics_recommendation_service = AnalyticsRecommendationService()





























