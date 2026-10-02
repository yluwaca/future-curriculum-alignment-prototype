"""Deterministic labour-workflow recommendation builder.

Consumes only *approved* curriculum and labour-market mappings, labour demand
signals and demand evidence, plus curriculum coverage/gap indicators, and
produces governance-pending recommendations with full traceability back to the
evidence (postings and curriculum records).

Guarantees:

* rejected and unreviewed (candidate/needs_review) mappings are never used;
* every recommendation is created with review status ``pending_review`` and can
  only move through the existing human governance workflow afterwards;
* duplicates are suppressed through a stable ``dedup_key`` in metadata;
* the compute layer is a pure function of plain dictionaries, so it is fully
  testable without a database and is deterministic for identical inputs.

Outputs are technical UAT evidence for decision-support readiness; they are not
curriculum or labour policy decisions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.models.recommendation import Recommendation
from app.models.recommendation_explanation import RecommendationExplanation

RECOMMENDATION_TYPE = "labour_demand_curriculum"
REVIEW_STATUS = "pending_review"
APPROVED_STATUS = "approved"

DEMAND_THRESHOLD_DEFAULT = 0.15

GAP_RECOMMENDATION = "curriculum_gap"
COVERAGE_RECOMMENDATION = "curriculum_coverage"

REQUIRED_FIELDS = (
    "recommendation_text",
    "priority",
    "confidence",
    "evidence_ids",
    "source_period",
    "explanation",
    "created_at",
    "review_status",
)


class RecommendationBuildError(Exception):
    """Raised when a recommendation cannot be built safely."""


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_approved(mapping: Mapping[str, Any]) -> None:
    status = str(mapping.get("mapping_status") or mapping.get("status") or "unknown").lower()
    if status != APPROVED_STATUS:
        raise RecommendationBuildError(
            "refusing to build recommendations from a "
            f"{status!r} mapping (only approved mappings are usable)"
        )


def _period_bucket(signals: Sequence[Mapping[str, Any]]) -> str:
    periods = sorted(
        {
            f"{int(signal['year'])}-{str(signal['quarter']).upper()}"
            for signal in signals
            if signal.get("year") is not None
        }
    )
    return "|".join(periods) if periods else "unknown-period"


def _source_list(signals: Sequence[Mapping[str, Any]], mappings: Sequence[Mapping[str, Any]]) -> List[str]:
    sources = set()
    for signal in signals:
        for source in (signal.get("source_summary") or "").split(","):
            label = source.strip().split(":")[0].strip()
            if label:
                sources.add(label)
    for mapping in mappings:
        if mapping.get("source"):
            sources.add(str(mapping["source"]))
    return sorted(sources)


class LabourRecommendationBuilder:
    """Deterministic demand-gap / curriculum-coverage recommendation builder."""

    def compute_recommendations(
        self,
        approved_labour_mappings: Sequence[Mapping[str, Any]],
        approved_curriculum_mappings: Sequence[Mapping[str, Any]],
        demand_signals: Sequence[Mapping[str, Any]],
        demand_evidence: Sequence[Mapping[str, Any]],
        demand_threshold: float = DEMAND_THRESHOLD_DEFAULT,
        allow_unapproved: bool = False,
    ) -> List[Dict[str, Any]]:
        """Pure, deterministic recommendation computation.

        ``allow_unapproved`` exists only for defensive validation tests; the
        real path always passes pre-filtered approved mappings. When False
        (default), any non-approved mapping in the inputs raises immediately.
        """
        for mapping in list(approved_labour_mappings) + list(approved_curriculum_mappings):
            if not allow_unapproved:
                _require_approved(mapping)

        approved_curriculum = self._approved_only(approved_curriculum_mappings)
        approved_labour = self._approved_only(approved_labour_mappings)

        curriculum_skills = {
            str(mapping.get("skill_id"))
            for mapping in approved_curriculum
            if mapping.get("skill_id")
        }
        labour_skills = {
            str(mapping.get("skill_id"))
            for mapping in approved_labour
            if mapping.get("skill_id")
        }

        evidence_by_skill: Dict[str, List[Mapping[str, Any]]] = {}
        for evidence in demand_evidence:
            skill_id = str(evidence.get("skill_id"))
            if skill_id:
                evidence_by_skill.setdefault(skill_id, []).append(evidence)

        signal_by_skill: Dict[str, List[Mapping[str, Any]]] = {}
        for signal in demand_signals:
            skill_id = str(signal.get("skill_id"))
            if skill_id:
                signal_by_skill.setdefault(skill_id, []).append(signal)

        mapping_by_skill: Dict[str, List[Mapping[str, Any]]] = {}
        for mapping in approved_labour:
            skill_id = str(mapping.get("skill_id"))
            if skill_id:
                mapping_by_skill.setdefault(skill_id, []).append(mapping)

        recommendations: List[Dict[str, Any]] = []
        candidate_skills = sorted(set(signal_by_skill) | set(evidence_by_skill))

        for skill_id in candidate_skills:
            skill_signals = signal_by_skill.get(skill_id, [])
            skill_evidence = evidence_by_skill.get(skill_id, [])
            skill_mappings = mapping_by_skill.get(skill_id, [])

            overall_demand, overall_confidence = self._aggregate(
                skill_signals, skill_evidence
            )
            if overall_demand < demand_threshold:
                continue

            skill_name = self._skill_name(skill_signals, skill_evidence, skill_mappings)
            covered = skill_id in curriculum_skills or skill_id in labour_skills
            kind = COVERAGE_RECOMMENDATION if covered else GAP_RECOMMENDATION
            priority = "medium" if kind == COVERAGE_RECOMMENDATION else "high"
            priority_score = 0.60 if kind == COVERAGE_RECOMMENDATION else 0.90

            explanation = self._explanation(
                skill_name=skill_name,
                skill_id=skill_id,
                kind=kind,
                demand=overall_demand,
                confidence=overall_confidence,
                n_signals=len(skill_signals),
                n_evidence=len(skill_evidence),
                n_labour_mappings=len(skill_mappings),
                n_curriculum_mappings=len(curriculum_skills & {skill_id}),
            )
            recommendation_text = self._recommendation_text(skill_name, kind)

            evidence_ids = {
                "demand_signal_ids": [str(item.get("signal_id")) for item in skill_signals if item.get("signal_id")],
                "demand_evidence_ids": [str(item.get("evidence_id")) for item in skill_evidence if item.get("evidence_id")],
                "labour_mapping_ids": [str(item.get("mapping_id")) for item in skill_mappings if item.get("mapping_id")],
                "curriculum_mapping_ids": [
                    str(item.get("mapping_id")) for item in approved_curriculum
                    if str(item.get("skill_id")) == skill_id and item.get("mapping_id")
                ],
            }

            created_at = _utcnow_iso()
            recommendation = {
                "dedup_key": stable_hash(
                    json.dumps(
                        {
                            "type": RECOMMENDATION_TYPE,
                            "kind": kind,
                            "skill_id": skill_id,
                            "period": _period_bucket(skill_signals),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ),
                "kind": kind,
                "skill_id": skill_id,
                "skill_name": skill_name,
                "recommendation_text": recommendation_text,
                "priority": priority,
                "priority_score": priority_score,
                "confidence": round(overall_confidence, 6),
                "evidence_ids": evidence_ids,
                "source_period": {
                    "sources": _source_list(skill_signals, skill_mappings),
                    "periods": _period_bucket([signal for signal in skill_signals if signal.get("year") is not None]).split("|"),
                },
                "explanation": explanation,
                "created_at": created_at,
                "review_status": REVIEW_STATUS,
                "demand_score": round(overall_demand, 6),
            }
            if not self._has_all_required_fields(recommendation):
                raise RecommendationBuildError(
                    f"recommendation for skill {skill_id} is missing a required field"
                )
            recommendations.append(recommendation)

        return self.deduplicate(recommendations)

    # ------------------------------------------------------------------
    # Aggregation helpers (deterministic)
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        signals: Sequence[Mapping[str, Any]],
        evidence: Sequence[Mapping[str, Any]],
    ) -> tuple[float, float]:
        demand = _num(0.0)
        signals_used = 0
        for signal in signals:
            demand += _num(signal.get("demand_score"))
            signals_used += 1
        for item in evidence:
            demand += _num(item.get("demand_score"))
            signals_used += 1
        n_signals = max(1, signals_used)
        aggregate_demand = demand / n_signals

        confidence = _num(0.0)
        confidence_items = 0
        for signal in signals:
            confidence += _num(signal.get("confidence_score"))
            confidence_items += 1
        for item in evidence:
            confidence += _num(item.get("confidence_score"))
            confidence_items += 1
        aggregate_confidence = confidence / max(1, confidence_items)

        return round(aggregate_demand, 6), round(min(0.95, aggregate_confidence), 6)

    def _skill_name(
        self,
        signals: Sequence[Mapping[str, Any]],
        evidence: Sequence[Mapping[str, Any]],
        mappings: Sequence[Mapping[str, Any]],
    ) -> str:
        for source in (signals, evidence, mappings):
            for item in source:
                name = item.get("skill_name") or item.get("canonical_name") or item.get("dimension_value")
                if name:
                    return str(name).strip()[:255]
        return "the skill"

    def _explanation(
        self,
        skill_name: str,
        skill_id: str,
        kind: str,
        demand: float,
        confidence: float,
        n_signals: int,
        n_evidence: int,
        n_labour_mappings: int,
        n_curriculum_mappings: int,
    ) -> str:
        if kind == GAP_RECOMMENDATION:
            return (
                f"Labour demand evidence for '{skill_name}' (demand {demand:.2f}, "
                f"confidence {confidence:.2f}) is not covered by any approved curriculum "
                f"mapping. Signals: {n_signals}, demand-evidence rows: {n_evidence}, "
                f"approved labour mappings: {n_labour_mappings}, approved curriculum "
                f"mappings: {n_curriculum_mappings}. Recommendation is pending human review."
            )
        return (
            f"Labour demand evidence for '{skill_name}' (demand {demand:.2f}, "
            f"confidence {confidence:.2f}) is already reflected in approved mappings "
            f"({n_labour_mappings} labour, {n_curriculum_mappings} curriculum). "
            f"Recommendation confirms coverage and is pending human review."
        )

    def _recommendation_text(self, skill_name: str, kind: str) -> str:
        if kind == GAP_RECOMMENDATION:
            return (
                f"Add curriculum coverage for {skill_name} to close an identified "
                f"labour-demand gap."
            )
        return (
            f"Retain and strengthen curriculum coverage for {skill_name} to align "
            f"with sustained labour demand."
        )

    def deduplicate(self, recommendations: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        for recommendation in recommendations:
            key = str(recommendation["dedup_key"])
            existing = seen.get(key)
            if existing is None or _num(recommendation.get("confidence")) > _num(existing.get("confidence")):
                seen[key] = dict(recommendation)
        return list(seen.values())

    @staticmethod
    def _approved_only(mappings: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return [
            mapping
            for mapping in mappings
            if str(mapping.get("mapping_status") or mapping.get("status") or "").lower()
            == APPROVED_STATUS
        ]

    @staticmethod
    def _has_all_required_fields(recommendation: Mapping[str, Any]) -> bool:
        for required in REQUIRED_FIELDS:
            if not recommendation.get(required):
                return False
        return True

    # ------------------------------------------------------------------
    # Database loader / persistence (read-only inputs, write outputs)
    # ------------------------------------------------------------------

    def load_and_build(
        self,
        db,
        demand_threshold: float = DEMAND_THRESHOLD_DEFAULT,
        actor_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load approved evidence from the DB, compute, and persist pending-recommendations.

        Returns per-recommendation rows plus a summary of what was created or
        skipped. Existing recommendations with the same stable dedup_key are
        never duplicated.
        """
        from app.models.labour_market_signal import LabourMarketSignal
        from app.models.skill import Skill
        from app.models.skill_demand_evidence import SkillDemandEvidence
        from app.models.skill_mapping import SkillMapping

        approved_curriculum = self._load_approved_mappings(db, SkillMapping, Skill, "curriculum")
        approved_labour = self._load_approved_mappings(db, SkillMapping, Skill, "labour_market")

        evidence_rows = (
            db.query(SkillDemandEvidence, LabourMarketSignal, Skill)
            .join(LabourMarketSignal, LabourMarketSignal.signal_id == SkillDemandEvidence.signal_id)
            .join(Skill, Skill.skill_id == SkillDemandEvidence.skill_id)
            .all()
        )
        demand_evidence = []
        demand_signals = []
        consumed_signal_ids = set()
        for evidence, signal, skill in evidence_rows:
            demand_evidence.append(
                {
                    "evidence_id": str(evidence.evidence_id),
                    "skill_id": str(skill.skill_id),
                    "skill_name": skill.name,
                    "signal_id": str(signal.signal_id),
                    "demand_score": evidence.demand_score,
                    "confidence_score": evidence.confidence_score,
                }
            )
            if str(signal.signal_id) not in consumed_signal_ids:
                demand_signals.append(
                    {
                        "signal_id": str(signal.signal_id),
                        "skill_id": str(skill.skill_id),
                        "skill_name": skill.name,
                        "canonical_name": signal.canonical_name,
                        "dimension_value": signal.dimension_value,
                        "year": signal.year,
                        "quarter": signal.quarter,
                        "demand_score": signal.demand_score,
                        "confidence_score": signal.confidence_score,
                        "evidence_count": signal.evidence_count,
                        "source_summary": signal.source_summary,
                    }
                )
                consumed_signal_ids.add(str(signal.signal_id))

        recommendations = self.compute_recommendations(
            approved_labour_mappings=approved_labour,
            approved_curriculum_mappings=approved_curriculum,
            demand_signals=demand_signals,
            demand_evidence=demand_evidence,
            demand_threshold=demand_threshold,
        )

        created = 0
        skipped = 0
        for recommendation in recommendations:
            if self._exists(db, recommendation["dedup_key"]):
                skipped += 1
                continue
            record = Recommendation(
                skill_id=self._uuid_or_none(recommendation.get("skill_id")),
                recommendation_type=RECOMMENDATION_TYPE,
                title=recommendation["recommendation_text"],
                description=recommendation["explanation"],
                priority=recommendation["priority"],
                priority_score=recommendation["priority_score"],
                confidence_score=recommendation["confidence"],
                status=REVIEW_STATUS,
                recommendation_metadata={
                    "builder": "labour_recommendation_builder_v1",
                    "dedup_key": recommendation["dedup_key"],
                    "kind": recommendation["kind"],
                    "skill_name": recommendation["skill_name"],
                    "evidence_ids": recommendation["evidence_ids"],
                    "source_period": recommendation["source_period"],
                    "governance": "pending_human_review",
                    "actor_label": actor_label,
                },
            )
            db.add(record)
            db.flush()
            db.add(
                RecommendationExplanation(
                    recommendation_id=record.recommendation_id,
                    explanation_type="labour_demand_evidence",
                    explanation_text=recommendation["explanation"],
                    confidence_score=recommendation["confidence"],
                    evidence={
                        "skill_id": recommendation["skill_id"],
                        "skill_name": recommendation["skill_name"],
                        "kind": recommendation["kind"],
                        "evidence_ids": recommendation["evidence_ids"],
                        "source_period": recommendation["source_period"],
                        "demand_score": recommendation["demand_score"],
                        "builder": "labour_recommendation_builder_v1",
                    },
                )
            )
            created += 1
        db.commit()

        return {
            "created": created,
            "skipped": skipped,
            "total": len(recommendations),
            "approved_curriculum_mappings_loaded": len(approved_curriculum),
            "approved_labour_mappings_loaded": len(approved_labour),
            "demand_signals_used": len(demand_signals),
            "demand_evidence_used": len(demand_evidence),
            "review_status": REVIEW_STATUS,
            "recommendations": recommendations,
        }

    def _load_approved_mappings(self, db, MappingModel, SkillModel, source_domain: str) -> List[Dict[str, Any]]:
        rows = (
            db.query(MappingModel, SkillModel)
            .join(SkillModel, SkillModel.skill_id == MappingModel.skill_id)
            .filter(
                MappingModel.source_domain == source_domain,
                MappingModel.mapping_status == APPROVED_STATUS,
            )
            .all()
        )
        mappings = []
        for mapping, skill in rows:
            mappings.append(
                {
                    "mapping_id": str(mapping.mapping_id),
                    "skill_id": str(skill.skill_id),
                    "skill_key": skill.skill_key,
                    "skill_name": skill.name,
                    "mapping_status": mapping.mapping_status,
                    "source": (mapping.mapping_metadata or {}).get("source"),
                    "source_url": (mapping.mapping_metadata or {}).get("source_url"),
                    "posting_id": (mapping.mapping_metadata or {}).get("posting_id"),
                    "job_id": (mapping.mapping_metadata or {}).get("job_id"),
                    "confidence": mapping.confidence_score,
                    "reviewed_by": mapping.reviewed_by,
                }
            )
        return mappings

    def _exists(self, db, dedup_key: str) -> bool:
        row = (
            db.query(Recommendation)
            .filter(
                Recommendation.recommendation_type == RECOMMENDATION_TYPE,
                Recommendation.recommendation_metadata["dedup_key"].astext == dedup_key,
            )
            .first()
        )
        return row is not None

    @staticmethod
    def _uuid_or_none(value: Optional[str]):
        if not value:
            return None
        import uuid as _uuid
        try:
            return _uuid.UUID(str(value))
        except (ValueError, AttributeError):
            return None


def _num(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


labour_recommendation_builder = LabourRecommendationBuilder()