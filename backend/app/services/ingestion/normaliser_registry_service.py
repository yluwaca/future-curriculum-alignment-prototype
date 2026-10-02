"""
Normaliser registry and runtime resolution service.
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.ingestion_contract import IngestionContract
from app.models.normaliser_definition import NormaliserDefinition
from app.models.raw_ingestion_record import RawIngestionRecord


RECORD_TYPE_NORMALISER_MAP = {
    "curriculum_pdf": "curriculum_document_v1",
    "curriculum_extracted_text": "curriculum_document_v1",
    "curriculum_document_chunk": "curriculum_document_v1",
    "cput_prospectus_course_index": "cput_prospectus_v1",
    "cput_prospectus_course_detail": "cput_prospectus_v1",
    "cput_prospectus_module": "cput_prospectus_v1",
    "statssa_qlfs_pdf": "statssa_qlfs_v1",
    "statssa_qlfs_table": "statssa_qlfs_v1",
    "che_vitalstats_pdf": "che_vitalstats_v1",
    "che_vitalstats_table": "che_vitalstats_v1",
    "esco_skill": "esco_taxonomy_v1",
    "esco_taxonomy_record": "esco_taxonomy_v1",
    "job_advert": "job_advert_v1",
    "job_advert_record": "job_advert_v1",
    "job_posting": "job_advert_v1",
    "api_payload": "api_payload_v1",
    "json_api_record": "api_payload_v1",
    "csv_row": "tabular_dataset_v1",
    "xlsx_row": "tabular_dataset_v1",
    "generic_tabular_record": "tabular_dataset_v1",
}


class NormaliserRegistryService:
    """
    Resolves versioned normaliser definitions and applies light runtime shaping.
    """

    def list_definitions(
        self,
        db: Session,
        source_category: Optional[str] = None,
        input_format: Optional[str] = None,
        active_only: bool = True,
    ) -> List[NormaliserDefinition]:
        query = db.query(NormaliserDefinition)
        if source_category:
            query = query.filter(NormaliserDefinition.source_category == source_category)
        if input_format:
            query = query.filter(NormaliserDefinition.input_format == input_format)
        if active_only:
            query = query.filter(NormaliserDefinition.status == "active")
        return query.order_by(
            NormaliserDefinition.source_category,
            NormaliserDefinition.normaliser_key,
            NormaliserDefinition.version,
        ).all()

    def get_definition(
        self,
        db: Session,
        normaliser_key: str,
        version: Optional[str] = None,
    ) -> Optional[NormaliserDefinition]:
        query = db.query(NormaliserDefinition).filter(
            NormaliserDefinition.normaliser_key == normaliser_key,
        )
        if version:
            query = query.filter(NormaliserDefinition.version == version)
        else:
            query = query.filter(
                NormaliserDefinition.status == "active",
                NormaliserDefinition.is_default.is_(True),
            )
        return query.order_by(NormaliserDefinition.version.desc()).first()

    def resolve_for_record(
        self,
        db: Session,
        record: RawIngestionRecord,
        contract: Optional[IngestionContract] = None,
    ) -> Optional[NormaliserDefinition]:
        normaliser_key = None
        if record.source and record.source.normaliser_key:
            normaliser_key = record.source.normaliser_key
        if contract and contract.cleaning_profile.get("normaliser_key"):
            normaliser_key = contract.cleaning_profile["normaliser_key"]
        normaliser_key = normaliser_key or RECORD_TYPE_NORMALISER_MAP.get(record.record_type)

        if not normaliser_key:
            return None
        definition = self.get_definition(db, normaliser_key)
        if not definition:
            return None
        supported = definition.supported_record_types or []
        if supported and record.record_type not in supported:
            mapped_key = RECORD_TYPE_NORMALISER_MAP.get(record.record_type)
            if mapped_key and mapped_key != normaliser_key:
                return self.get_definition(db, mapped_key)
        return definition

    def normalise_payload(
        self,
        record: RawIngestionRecord,
        base_payload: Dict[str, Any],
        definition: Optional[NormaliserDefinition],
    ) -> Dict[str, Any]:
        payload = deepcopy(base_payload)
        if not definition:
            payload.setdefault("normaliser", {"status": "unregistered"})
            return payload

        profile = definition.transformation_profile or {}
        payload["normaliser"] = {
            "normaliser_definition_id": str(definition.normaliser_definition_id),
            "normaliser_key": definition.normaliser_key,
            "normaliser_version": definition.version,
            "output_record_type": definition.output_record_type,
        }

        normalised_payload = payload.get("normalised_payload") or {}
        raw_payload = payload.get("raw_payload") or {}
        normalised_payload.setdefault("output_record_type", definition.output_record_type)
        normalised_payload.setdefault("source_category", definition.source_category)

        if profile.get("clean_numeric_values") and isinstance(raw_payload.get("rows"), list):
            payload["numeric_summary"] = self.numeric_summary(raw_payload["rows"])

        if profile.get("extract_skill_text"):
            payload["skill_text"] = self.extract_skill_text(raw_payload, normalised_payload)

        payload["normalised_payload"] = normalised_payload
        return payload

    def numeric_summary(self, rows: List[Any]) -> Dict[str, Any]:
        numeric_cells = 0
        descriptor_cells = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            for value in row.values():
                if isinstance(value, (int, float)):
                    numeric_cells += 1
                elif value not in (None, ""):
                    descriptor_cells += 1
        return {
            "row_count": len(rows),
            "numeric_cells": numeric_cells,
            "descriptor_cells": descriptor_cells,
        }

    def extract_skill_text(self, raw_payload: Dict[str, Any], normalised_payload: Dict[str, Any]) -> str:
        parts: List[str] = []
        for payload in (normalised_payload, raw_payload):
            for key in ("title", "description", "body", "text", "requirements", "content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        return "\n".join(parts)


normaliser_registry_service = NormaliserRegistryService()
