"""
Lineage helpers for ingestion and processing stages.
"""

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.data_lineage_event import DataLineageEvent


class LineageService:
    """
    Records source-to-output traceability events.
    """

    def record_event(
        self,
        db: Session,
        source_system: str,
        processing_stage: str,
        transformation_description: str,
        job_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
        input_record_id: Optional[UUID] = None,
        output_record_id: Optional[UUID] = None,
        actor_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DataLineageEvent:
        event = DataLineageEvent(
            job_id=job_id,
            source_id=source_id,
            input_record_id=input_record_id,
            output_record_id=output_record_id,
            source_system=source_system,
            processing_stage=processing_stage,
            transformation_description=transformation_description,
            actor_id=actor_id,
            lineage_metadata=metadata or {},
        )
        db.add(event)
        return event


lineage_service = LineageService()
