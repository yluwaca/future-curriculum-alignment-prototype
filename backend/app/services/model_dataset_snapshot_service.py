"""
Reproducible model dataset preparation service.

Phase 3 creates versioned metadata snapshots before model training/evaluation.
The snapshot is intentionally metadata-only: it records what would be extracted,
how it is filtered/split, and the checksum of that preparation state without
copying raw rows into another table.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from importlib import metadata as package_metadata
from typing import Any
from typing import Dict
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alignment_score import AlignmentScore
from app.models.cleaned_ingestion_record import CleanedIngestionRecord
from app.models.curriculum_module import CurriculumModule
from app.models.forecast import Forecast
from app.models.ingestion_job import IngestionJob
from app.models.job_posting import JobPosting
from app.models.labour_market_signal import LabourMarketSignal
from app.models.labour_market_trend import LabourMarketTrend
from app.models.model_dataset_snapshot import ModelDatasetSnapshot
from app.models.raw_ingestion_record import RawIngestionRecord
from app.models.skill_demand_evidence import SkillDemandEvidence


class ModelDatasetSnapshotService:
    """
    Build and persist reproducible dataset snapshots for model workflows.
    """

    DEFAULT_RANDOM_SEEDS = {
        "python_hash_seed": "not forced by application",
        "numpy": 42,
        "xgboost": 42,
        "tensorflow": 42,
        "train_split": "chronological_no_shuffle",
    }

    def latest_snapshot(self, db: Session, model_type: Optional[str] = None) -> Optional[ModelDatasetSnapshot]:
        query = db.query(ModelDatasetSnapshot)
        if model_type:
            query = query.filter(ModelDatasetSnapshot.model_type == model_type)
        return query.order_by(ModelDatasetSnapshot.created_at.desc()).first()

    def list_snapshots(self, db: Session, model_type: Optional[str] = None, limit: int = 25) -> list[ModelDatasetSnapshot]:
        query = db.query(ModelDatasetSnapshot)
        if model_type:
            query = query.filter(ModelDatasetSnapshot.model_type == model_type)
        return query.order_by(ModelDatasetSnapshot.created_at.desc()).limit(max(1, min(limit, 100))).all()

    def create_snapshot(
        self,
        db: Session,
        model_type: str,
        actor_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        feature_schema: Optional[Dict[str, Any]] = None,
        target_construction: Optional[Dict[str, Any]] = None,
        model_config: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        commit: bool = True,
    ) -> ModelDatasetSnapshot:
        model_type = (model_type or "general").lower().strip()
        extraction_timestamp = datetime.now(timezone.utc)
        filters_payload = self._default_filters(model_type)
        if filters:
            filters_payload.update(filters)

        record_counts = self._record_counts(db)
        curriculum_summary = self._curriculum_summary(db)
        labour_summary = self._labour_market_summary(db)
        date_min, date_max = self._observation_window(db)
        duplicate_count, duplicate_details = self._duplicate_summary(db)
        simulated_count, empirical_count, simulated_details = self._simulation_summary(db)
        exclusion_reasons = self._exclusion_reasons(db)
        split_policy = self._split_policy(model_type)
        leakage_checks = self._leakage_checks(
            record_counts=record_counts,
            duplicate_count=duplicate_count,
            simulated_count=simulated_count,
            curriculum_summary=curriculum_summary,
            labour_summary=labour_summary,
        )
        feature_payload = feature_schema or self._feature_schema(model_type)
        target_payload = target_construction or self._target_construction(model_type)
        software_config = self._software_config(model_config or {})

        fingerprint_payload = {
            "model_type": model_type,
            "source_tables": self._source_tables(),
            "filters": filters_payload,
            "record_counts": record_counts,
            "duplicate_details": duplicate_details,
            "simulation_details": simulated_details,
            "curriculum_summary": curriculum_summary,
            "labour_market_summary": labour_summary,
            "min_observation_date": self._iso(date_min),
            "max_observation_date": self._iso(date_max),
            "feature_schema": feature_payload,
            "target_construction": target_payload,
            "split_policy": split_policy,
            "random_seeds": self.DEFAULT_RANDOM_SEEDS,
            "software_config": software_config,
        }
        fingerprint = self._fingerprint(fingerprint_payload)
        snapshot_version = f"{model_type}_{extraction_timestamp.strftime('%Y%m%d_%H%M%S_%f')}"

        snapshot = ModelDatasetSnapshot(
            model_type=model_type,
            snapshot_version=snapshot_version,
            dataset_fingerprint=fingerprint,
            extraction_timestamp=extraction_timestamp,
            min_observation_date=date_min,
            max_observation_date=date_max,
            raw_records_count=int(record_counts.get("raw_ingestion_records", 0) + record_counts.get("job_postings", 0)),
            cleaned_records_count=int(record_counts.get("cleaned_ingestion_records", 0)),
            excluded_records_count=int(sum(exclusion_reasons.values())),
            duplicate_records_count=int(duplicate_count),
            empirical_records_count=int(empirical_count),
            simulated_records_count=int(simulated_count),
            source_tables=self._source_tables(),
            filters=filters_payload,
            exclusion_reasons=exclusion_reasons,
            curriculum_summary=curriculum_summary,
            labour_market_summary=labour_summary,
            feature_schema=feature_payload,
            target_construction=target_payload,
            split_policy=split_policy,
            leakage_checks=leakage_checks,
            random_seeds=self.DEFAULT_RANDOM_SEEDS,
            software_config=software_config,
            record_counts=record_counts,
            snapshot_metadata={
                "duplicate_details": duplicate_details,
                "simulation_details": simulated_details,
                "fingerprint_payload_schema": "future_dataset_snapshot_v1",
                "fingerprint_excludes": ["snapshot_id", "snapshot_version", "extraction_timestamp", "created_at"],
            },
            created_by=actor_id,
            notes=notes,
        )
        db.add(snapshot)
        db.flush()
        if commit:
            db.commit()
            db.refresh(snapshot)
        return snapshot

    def to_dict(self, snapshot: ModelDatasetSnapshot) -> Dict[str, Any]:
        return {
            "snapshot_id": str(snapshot.snapshot_id),
            "model_type": snapshot.model_type,
            "snapshot_version": snapshot.snapshot_version,
            "dataset_fingerprint": snapshot.dataset_fingerprint,
            "extraction_timestamp": self._iso(snapshot.extraction_timestamp),
            "min_observation_date": self._iso(snapshot.min_observation_date),
            "max_observation_date": self._iso(snapshot.max_observation_date),
            "raw_records_count": snapshot.raw_records_count,
            "cleaned_records_count": snapshot.cleaned_records_count,
            "excluded_records_count": snapshot.excluded_records_count,
            "duplicate_records_count": snapshot.duplicate_records_count,
            "empirical_records_count": snapshot.empirical_records_count,
            "simulated_records_count": snapshot.simulated_records_count,
            "source_tables": snapshot.source_tables,
            "filters": snapshot.filters,
            "exclusion_reasons": snapshot.exclusion_reasons,
            "curriculum_summary": snapshot.curriculum_summary,
            "labour_market_summary": snapshot.labour_market_summary,
            "feature_schema": snapshot.feature_schema,
            "target_construction": snapshot.target_construction,
            "split_policy": snapshot.split_policy,
            "leakage_checks": snapshot.leakage_checks,
            "random_seeds": snapshot.random_seeds,
            "software_config": snapshot.software_config,
            "record_counts": snapshot.record_counts,
            "snapshot_metadata": snapshot.snapshot_metadata,
            "created_by": snapshot.created_by,
            "created_at": self._iso(snapshot.created_at),
            "updated_at": self._iso(snapshot.updated_at),
            "notes": snapshot.notes,
        }

    def _record_counts(self, db: Session) -> Dict[str, int]:
        return {
            "curriculum_modules": self._count(db, CurriculumModule),
            "active_curriculum_modules": db.query(func.count(CurriculumModule.module_id)).filter(CurriculumModule.is_active.is_(True)).scalar() or 0,
            "job_postings": self._count(db, JobPosting),
            "raw_ingestion_records": self._count(db, RawIngestionRecord),
            "cleaned_ingestion_records": self._count(db, CleanedIngestionRecord),
            "ingestion_jobs": self._count(db, IngestionJob),
            "labour_market_trends": self._count(db, LabourMarketTrend),
            "labour_market_signals": self._count(db, LabourMarketSignal),
            "skill_demand_evidence": self._count(db, SkillDemandEvidence),
            "alignment_scores": self._count(db, AlignmentScore),
            "forecasts": self._count(db, Forecast),
        }

    def _curriculum_summary(self, db: Session) -> Dict[str, Any]:
        faculties = [r[0] for r in db.query(CurriculumModule.faculty).filter(CurriculumModule.faculty.isnot(None)).distinct().limit(50).all()]
        programmes = [r[0] for r in db.query(CurriculumModule.programme).filter(CurriculumModule.programme.isnot(None)).distinct().limit(50).all()]
        synthetic = db.query(func.count(CurriculumModule.module_id)).filter(CurriculumModule.data_source.ilike("%synthetic%")).scalar() or 0
        return {
            "included_table": "curriculum_module",
            "active_filter": "is_active = true",
            "programmes_included_count": len(programmes),
            "modules_included_count": db.query(func.count(CurriculumModule.module_id)).filter(CurriculumModule.is_active.is_(True)).scalar() or 0,
            "faculties_sample": faculties,
            "programmes_sample": programmes,
            "synthetic_module_count": synthetic,
        }

    def _labour_market_summary(self, db: Session) -> Dict[str, Any]:
        sources = [r[0] for r in db.query(JobPosting.source).filter(JobPosting.source.isnot(None)).distinct().limit(50).all()]
        signal_years = db.query(func.min(LabourMarketSignal.year), func.max(LabourMarketSignal.year)).one()
        trend_years = db.query(func.min(LabourMarketTrend.year), func.max(LabourMarketTrend.year)).one()
        return {
            "job_posting_sources": sources,
            "job_postings_count": self._count(db, JobPosting),
            "trend_facts_count": self._count(db, LabourMarketTrend),
            "canonical_signals_count": self._count(db, LabourMarketSignal),
            "skill_demand_evidence_count": self._count(db, SkillDemandEvidence),
            "signal_year_min": signal_years[0],
            "signal_year_max": signal_years[1],
            "trend_year_min": trend_years[0],
            "trend_year_max": trend_years[1],
        }

    def _observation_window(self, db: Session) -> tuple[Any, Any]:
        dates = []
        for query in [
            db.query(func.min(JobPosting.posted_date), func.max(JobPosting.posted_date)).one(),
            db.query(func.min(RawIngestionRecord.created_at), func.max(RawIngestionRecord.created_at)).one(),
            db.query(func.min(CleanedIngestionRecord.created_at), func.max(CleanedIngestionRecord.created_at)).one(),
            db.query(func.min(AlignmentScore.created_at), func.max(AlignmentScore.created_at)).one(),
            db.query(func.min(Forecast.created_at), func.max(Forecast.created_at)).one(),
        ]:
            dates.extend([item for item in query if item is not None])
        if not dates:
            return None, None
        return min(dates), max(dates)

    def _duplicate_summary(self, db: Session) -> tuple[int, Dict[str, Any]]:
        raw_duplicate_groups = db.query(RawIngestionRecord.content_hash, func.count(RawIngestionRecord.record_id)).filter(RawIngestionRecord.content_hash.isnot(None)).group_by(RawIngestionRecord.content_hash).having(func.count(RawIngestionRecord.record_id) > 1).count()
        cleaned_duplicate_groups = db.query(CleanedIngestionRecord.content_hash, func.count(CleanedIngestionRecord.cleaned_record_id)).group_by(CleanedIngestionRecord.content_hash).having(func.count(CleanedIngestionRecord.cleaned_record_id) > 1).count()
        job_duplicate_groups = db.query(JobPosting.job_title, JobPosting.source, JobPosting.posted_date, func.count(JobPosting.posting_id)).group_by(JobPosting.job_title, JobPosting.source, JobPosting.posted_date).having(func.count(JobPosting.posting_id) > 1).count()
        total = int(raw_duplicate_groups + cleaned_duplicate_groups + job_duplicate_groups)
        return total, {
            "raw_content_hash_duplicate_groups": int(raw_duplicate_groups),
            "cleaned_content_hash_duplicate_groups": int(cleaned_duplicate_groups),
            "job_title_source_date_duplicate_groups": int(job_duplicate_groups),
            "fold_policy": "duplicate groups must remain in the same chronological/group fold",
        }

    def _simulation_summary(self, db: Session) -> tuple[int, int, Dict[str, Any]]:
        synthetic_modules = db.query(func.count(CurriculumModule.module_id)).filter(CurriculumModule.data_source.ilike("%synthetic%")).scalar() or 0
        synthetic_jobs = db.query(func.count(JobPosting.posting_id)).filter(JobPosting.source.ilike("%synthetic%")).scalar() or 0
        mock_jobs = db.query(func.count(JobPosting.posting_id)).filter(JobPosting.source.ilike("%mock%")).scalar() or 0
        simulated = int(synthetic_modules + synthetic_jobs + mock_jobs)
        empirical = max(0, self._count(db, CurriculumModule) + self._count(db, JobPosting) + self._count(db, LabourMarketSignal) - simulated)
        return simulated, empirical, {
            "synthetic_curriculum_modules": int(synthetic_modules),
            "synthetic_job_postings": int(synthetic_jobs),
            "mock_job_postings": int(mock_jobs),
            "policy": "mock/synthetic records must be excluded from empirical model claims or labelled simulation-only",
        }

    def _exclusion_reasons(self, db: Session) -> Dict[str, int]:
        inactive_modules = db.query(func.count(CurriculumModule.module_id)).filter(CurriculumModule.is_active.is_(False)).scalar() or 0
        synthetic_modules = db.query(func.count(CurriculumModule.module_id)).filter(CurriculumModule.data_source.ilike("%synthetic%")).scalar() or 0
        invalid_raw = db.query(func.count(RawIngestionRecord.record_id)).filter(RawIngestionRecord.validation_status.notin_(["valid", "passed", "cleaned", "pending"])).scalar() or 0
        rejected_cleaned = db.query(func.count(CleanedIngestionRecord.cleaned_record_id)).filter(CleanedIngestionRecord.cleaning_status.notin_(["cleaned", "imported", "normalised"])).scalar() or 0
        return {
            "inactive_curriculum_modules": int(inactive_modules),
            "synthetic_curriculum_modules": int(synthetic_modules),
            "invalid_raw_ingestion_records": int(invalid_raw),
            "rejected_or_non_cleaned_records": int(rejected_cleaned),
        }

    def _leakage_checks(self, record_counts: Dict[str, int], duplicate_count: int, simulated_count: int, curriculum_summary: Dict[str, Any], labour_summary: Dict[str, Any]) -> Dict[str, Any]:
        warnings = []
        if duplicate_count:
            warnings.append("Duplicate source/content groups exist; grouped split isolation is required.")
        if simulated_count:
            warnings.append("Mock or synthetic records exist; empirical evaluation must exclude or clearly label them.")
        if labour_summary.get("signal_year_min") == labour_summary.get("signal_year_max") and labour_summary.get("signal_year_min") is not None:
            warnings.append("Labour-market signal window covers one year only; temporal validation may be weak.")
        if record_counts.get("active_curriculum_modules", 0) < 10:
            warnings.append("Fewer than 10 active curriculum modules; alignment model training is not reliable.")
        if record_counts.get("job_postings", 0) < 1000 and record_counts.get("labour_market_signals", 0) < 500:
            warnings.append("Labour-market evidence is shallow for advanced forecasting.")
        return {
            "chronological_split_required": True,
            "preprocessing_fit_scope": "fit transformers/scalers/vectorisers inside each training fold only",
            "duplicate_job_isolation_required": True,
            "curriculum_module_group_isolation_required": True,
            "final_test_period_untouched": True,
            "mock_synthetic_separated": simulated_count == 0,
            "warnings": warnings,
            "status": "warning" if warnings else "ready_for_preparation",
        }

    def _source_tables(self) -> Dict[str, str]:
        return {
            "curriculum": "curriculum_module, academic_programme, curriculum_document, curriculum_document_version, document_chunk",
            "labour_market": "job_posting, raw_ingestion_record, cleaned_ingestion_record, labour_market_trend, labour_market_signal, skill_demand_evidence",
            "outcomes": "alignment_score, forecast, recommendation_review",
        }

    def _default_filters(self, model_type: str) -> Dict[str, Any]:
        return {
            "curriculum_modules": {"is_active": True, "exclude_data_source": "synthetic_training"},
            "job_postings": {"posted_date": "not null", "deduplicate_by": ["job_id", "job_title", "source", "posted_date"]},
            "cleaned_ingestion_records": {"cleaning_status_in": ["cleaned", "imported", "normalised"]},
            "model_type": model_type,
        }

    def _feature_schema(self, model_type: str) -> Dict[str, Any]:
        if model_type == "xgboost":
            return {
                "schema_name": "xgboost_alignment_features_v1",
                "feature_sources": ["curriculum_module", "skill_mapping", "skill_demand_evidence", "labour_market_signal"],
                "feature_groups": ["curriculum_metadata", "skill_overlap", "demand_pressure", "mapping_confidence", "faculty_programme_context"],
                "preprocessing_policy": "derive/fill/select features on training folds only; no statistics from validation/test folds",
            }
        if model_type == "lstm":
            return {
                "schema_name": "lstm_forecast_sequence_v1",
                "feature_sources": ["labour_market_signal", "skill_demand_evidence", "forecast"],
                "feature_groups": ["canonical_signal_time_series", "demand_score_history", "confidence_history"],
                "sequence_policy": "chronological sequences only; no future periods in scaler or sequence construction",
            }
        return {"schema_name": "general_model_dataset_v1"}

    def _target_construction(self, model_type: str) -> Dict[str, Any]:
        if model_type == "xgboost":
            return {
                "target_name": "alignment_label_or_score",
                "current_implementation": "derived from curriculum alignment_score when present; otherwise 1 - gap_score heuristic",
                "phase3_warning": "binary threshold must be validated in Phase 4 before scientific claims or promotion",
            }
        if model_type == "lstm":
            return {
                "target_name": "next_period_demand_value",
                "current_implementation": "last value of chronological signal sequence",
                "phase3_warning": "forecast horizon/window must remain stored with every candidate and evaluated in Phase 5",
            }
        return {"target_name": "not specified"}

    def _split_policy(self, model_type: str) -> Dict[str, Any]:
        return {
            "split_strategy": "chronological_time_series_split_plus_final_holdout",
            "shuffle": False,
            "final_test_period": "reserved and untouched until final evaluation",
            "preprocessing": "fit only on training fold/window",
            "duplicate_isolation": "same job/content hash group must not cross folds",
            "curriculum_group_isolation": "same curriculum module/version should not cross folds where target leakage is possible",
            "model_type": model_type,
        }

    def _software_config(self, extra: Dict[str, Any]) -> Dict[str, Any]:
        packages = {}
        for name in ["numpy", "pandas", "scikit-learn", "xgboost", "tensorflow", "sqlalchemy", "fastapi"]:
            try:
                packages[name] = package_metadata.version(name)
            except package_metadata.PackageNotFoundError:
                packages[name] = None
        return {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "packages": packages,
            "extra_model_config": extra,
        }

    def _count(self, db: Session, model: Any) -> int:
        return int(db.query(func.count()).select_from(model).scalar() or 0)

    def _fingerprint(self, payload: Dict[str, Any]) -> str:
        serialised = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(serialised.encode("utf-8")).hexdigest()

    def _iso(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


model_dataset_snapshot_service = ModelDatasetSnapshotService()
