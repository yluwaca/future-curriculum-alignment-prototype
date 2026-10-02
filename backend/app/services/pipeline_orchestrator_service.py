"""
End-to-end pipeline orchestration for StatsSA-to-report execution.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models.cleaned_ingestion_record import CleanedIngestionRecord
from app.models.extracted_table import ExtractedTable
from app.models.extracted_table_row import ExtractedTableRow
from app.models.ingestion_job import IngestionJob
from app.models.pipeline_run import PipelineRun
from app.models.pipeline_stage_run import PipelineStageRun
from app.schemas.pipeline import PipelineRunRequest
from app.services.audit_service import log_audit_event
from app.services.ingestion.data_quality_service import data_quality_service
from app.services.ingestion.job_service import ingestion_job_service
from app.services.ingestion.statssa_connector import StatsSAQLFSConnector, run_statssa_job
from app.services.labour_market_trend_service import labour_market_trend_service


class PipelineOrchestratorService:
    """
    Composes the ingestion, quality, analytics, recommendation, and report services.
    """

    PIPELINE_KEY = "statssa_full_pipeline_v1"

    def run_statssa_full_pipeline(
        self,
        db: Session,
        request: PipelineRunRequest,
        actor_id: Optional[str] = None,
    ) -> PipelineRun:
        parameters = request.model_dump(mode="json")
        if request.existing_job_id:
            active_runs = (
                db.query(PipelineRun)
                .filter(
                    PipelineRun.pipeline_key == self.PIPELINE_KEY,
                    PipelineRun.status.in_(["queued", "running"]),
                )
                .order_by(PipelineRun.created_at.desc())
                .all()
            )
            requested_job_id = str(request.existing_job_id)
            for active_run in active_runs:
                if str((active_run.parameters or {}).get("existing_job_id")) == requested_job_id:
                    return self.get_run(db, active_run.pipeline_run_id) or active_run

        run = PipelineRun(
            pipeline_key=self.PIPELINE_KEY,
            tenant_id=request.tenant_id,
            run_scope="tenant" if request.tenant_id else "shared",
            status="running",
            triggered_by=actor_id,
            parameters=parameters,
            started_at=self.now(),
            summary={},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        context: Dict[str, Any] = {
            "actor_id": actor_id,
            "request": request,
            "pipeline_run_id": str(run.pipeline_run_id),
            "job_id": str(request.existing_job_id) if request.existing_job_id else None,
        }

        try:
            self.run_stage(db, run, 1, "statssa_ingestion", "StatsSA ingestion", context, self.stage_ingestion)
            self.run_stage(db, run, 2, "quality_checks", "Quality checks", context, self.stage_quality)
            self.run_stage(db, run, 3, "cleaned_records", "Cleaned records", context, self.stage_cleaned_records)
            self.run_stage(db, run, 4, "trend_facts", "Trend facts", context, self.stage_trend_facts)
            self.run_stage(db, run, 5, "canonical_signals", "Canonical signals", context, self.stage_canonical_signals)
            self.run_stage(db, run, 6, "skill_demand_evidence", "Skill demand evidence", context, self.stage_skill_demand_evidence)
            self.run_stage(db, run, 7, "forecasts_recommendations", "Forecasts and recommendations", context, self.stage_analytics)
            self.run_stage(db, run, 8, "reports", "Reports", context, self.stage_reports)
            run.status = "completed"
            run.completed_at = self.now()
            run.summary = self.build_run_summary(context)

            if context.get("job_id"):
                ingestion_job = db.query(IngestionJob).filter(
                    IngestionJob.job_id == UUID(context["job_id"])
                ).first()
                if ingestion_job:
                    ingestion_job.processed = True

            db.add(run)
            db.commit()
        except Exception as exc:
            run.status = "failed"
            run.completed_at = self.now()
            run.error_summary = str(exc)[:4000]
            run.summary = self.build_run_summary(context)
            db.add(run)
            db.commit()

        return self.get_run(db, run.pipeline_run_id) or run

    def run_stage(
        self,
        db: Session,
        run: PipelineRun,
        sequence: int,
        key: str,
        name: str,
        context: Dict[str, Any],
        handler: Callable[[Session, Dict[str, Any]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        stage = PipelineStageRun(
            pipeline_run_id=run.pipeline_run_id,
            stage_key=key,
            stage_name=name,
            sequence_number=sequence,
            status="running",
            started_at=self.now(),
            input_summary=self.stage_input_summary(key, context),
            output_summary={},
        )
        db.add(stage)
        db.commit()
        db.refresh(stage)

        try:
            output = handler(db, context)
            output = jsonable_encoder(output or {})
            stage.status = "completed"
            stage.output_summary = output
            stage.completed_at = self.now()
            context.setdefault("stages", {})[key] = output
            db.add(stage)
            db.commit()
            return output
        except Exception as exc:
            stage.status = "failed"
            stage.error_summary = str(exc)[:4000]
            stage.completed_at = self.now()
            db.add(stage)
            db.commit()
            raise

    def stage_ingestion(self, db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
        request: PipelineRunRequest = context["request"]
        if request.skip_ingestion and request.existing_job_id:
            job = self.require_job(db, request.existing_job_id)
            context["job_id"] = str(job.job_id)
            return self.job_summary(job, skipped=True)

        connector = StatsSAQLFSConnector()
        source = connector.ensure_source(db)
        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type="statssa_qlfs",
            triggered_by=context.get("actor_id"),
            parameters={
                "start_year": request.start_year,
                "end_year": request.end_year,
                "parse": request.parse,
                "dry_run": request.dry_run,
                "max_files": request.max_files,
                "orchestrated": True,
            },
        )
        db.commit()
        context["job_id"] = str(job.job_id)

        run_statssa_job(
            job_id=job.job_id,
            start_year=request.start_year,
            end_year=request.end_year,
            parse=request.parse,
            dry_run=request.dry_run,
            max_files=request.max_files,
        )
        db.expire_all()
        job = self.require_job(db, job.job_id)
        return self.job_summary(job, skipped=False)

    def stage_quality(self, db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
        request: PipelineRunRequest = context["request"]
        job = self.require_job(db, UUID(context["job_id"]))
        result = data_quality_service.run_job_quality(
            db=db,
            job=job,
            actor_id=context.get("actor_id"),
            limit=request.quality_limit,
        )
        db.commit()
        return result

    def stage_cleaned_records(self, db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
        job = self.require_job(db, UUID(context["job_id"]))

        existing_cleaned = {
            row[0]
            for row in db.query(CleanedIngestionRecord.raw_record_id)
            .filter(CleanedIngestionRecord.job_id == job.job_id)
            .all()
        }

        tables = (
            db.query(ExtractedTable)
            .filter(ExtractedTable.job_id == job.job_id)
            .order_by(ExtractedTable.created_at.asc())
            .all()
        )

        created = 0
        for table in tables:
            if table.raw_record_id in existing_cleaned:
                continue

            row_records = (
                db.query(ExtractedTableRow)
                .filter(ExtractedTableRow.table_id == table.table_id)
                .order_by(ExtractedTableRow.row_number.asc())
                .all()
            )

            raw_rows = []
            for rr in row_records:
                raw_rows.append(rr.row_payload or {})

            cleaned_payload = {
                "record_type": "statssa_qlfs_table",
                "raw_payload": {
                    "rows": raw_rows,
                    "year": table.year,
                    "quarter": table.quarter,
                    "source_file": table.source_file,
                    "table_index": table.table_index,
                    "page": table.page_number,
                    "series_code": table.series_code,
                    "title": table.title,
                },
                "normalised_payload": {
                    "year": table.year,
                    "quarter": table.quarter,
                    "source_file": table.source_file,
                },
            }

            content_hash = hashlib.sha256(
                json.dumps(cleaned_payload, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()

            cleaned = CleanedIngestionRecord(
                raw_record_id=table.raw_record_id,
                job_id=table.job_id,
                source_id=table.source_id,
                content_hash=content_hash,
                cleaning_status="cleaned",
                quality_score=1.0,
                cleaned_payload=cleaned_payload,
            )
            db.add(cleaned)
            existing_cleaned.add(table.raw_record_id)
            created += 1

        db.flush()
        return {
            "job_id": str(job.job_id),
            "extracted_tables": len(tables),
            "cleaned_records_created": created,
            "quality_stage": context.get("stages", {}).get("quality_checks", {}),
        }

    def stage_trend_facts(self, db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
        request: PipelineRunRequest = context["request"]
        result = labour_market_trend_service.normalise_from_cleaned_records(
            db=db,
            job_id=context["job_id"],
            limit=request.trend_limit,
            actor_id=context.get("actor_id"),
        )
        db.commit()
        return result

    def stage_canonical_signals(self, db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
        request: PipelineRunRequest = context["request"]
        result = labour_market_trend_service.generate_signals(
            db=db,
            limit=request.signal_limit,
            actor_id=context.get("actor_id"),
        )
        db.commit()
        return result

    def stage_skill_demand_evidence(self, db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
        # QLFS reports describe quarterly labour-force aggregates. Lexical
        # overlap between a table label and a skill is not evidence of an
        # employer vacancy or skill requirement. Preserve the contextual
        # signals, but require a separately classified vacancy/skills source
        # before creating SkillDemandEvidence.
        return {
            "status": "skipped_evidence_boundary",
            "evidence_created": 0,
            "reason": (
                "Stats SA QLFS is quarterly contextual aggregate evidence, "
                "not vacancy-level skill-demand evidence."
            ),
        }

    def stage_analytics(self, db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "skipped_evidence_boundary",
            "forecasts_created": 0,
            "alignments_created": 0,
            "recommendations_created": 0,
            "reason": (
                "Decision outputs require a separately validated vacancy/skill "
                "evidence stream; QLFS context alone is insufficient."
            ),
        }

    def stage_reports(self, db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
        # Recommendation dossiers are decision artefacts. A StatsSA-only run
        # deliberately stops at contextual signals and therefore must not
        # publish a dossier that appears to be supported by vacancy evidence.
        return {
            "status": "skipped_evidence_boundary",
            "reports_generated": 0,
            "report_ids": [],
            "reason": "No recommendation reports are generated from QLFS-only evidence.",
        }

    def get_run(self, db: Session, pipeline_run_id: UUID) -> Optional[PipelineRun]:
        return (
            db.query(PipelineRun)
            .filter(PipelineRun.pipeline_run_id == pipeline_run_id)
            .first()
        )

    def list_runs(self, db: Session, limit: int = 25):
        return (
            db.query(PipelineRun)
            .order_by(PipelineRun.created_at.desc())
            .limit(limit)
            .all()
        )

    def require_job(self, db: Session, job_id: UUID) -> IngestionJob:
        job = ingestion_job_service.get_job(db, job_id)
        if not job:
            raise ValueError(f"Ingestion job not found: {job_id}")
        return job

    def job_summary(self, job: IngestionJob, skipped: bool) -> Dict[str, Any]:
        return {
            "job_id": str(job.job_id),
            "status": job.status,
            "skipped_ingestion": skipped,
            "records_seen": job.records_seen,
            "records_loaded": job.records_loaded,
            "records_failed": job.records_failed,
            "progress_current": job.progress_current,
            "progress_total": job.progress_total,
        }

    def build_run_summary(self, context: Dict[str, Any]) -> Dict[str, Any]:
        stages = context.get("stages", {})
        return {
            "job_id": context.get("job_id"),
            "stage_count": len(stages),
            "stages": stages,
        }

    def stage_input_summary(self, key: str, context: Dict[str, Any]) -> Dict[str, Any]:
        request: PipelineRunRequest = context["request"]
        base = {"job_id": context.get("job_id")}
        if key == "statssa_ingestion":
            base.update(
                {
                    "start_year": request.start_year,
                    "end_year": request.end_year,
                    "parse": request.parse,
                    "dry_run": request.dry_run,
                    "max_files": request.max_files,
                    "skip_ingestion": request.skip_ingestion,
                }
            )
        return base

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)


pipeline_orchestrator_service = PipelineOrchestratorService()

