"""
Contract-driven data quality and cleaning for ingestion jobs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.cleaned_ingestion_record import CleanedIngestionRecord
from app.models.data_quality_check import DataQualityCheck
from app.models.data_quality_rule import DataQualityRule
from app.models.data_source import DataSource
from app.models.ingestion_contract import IngestionContract
from app.models.ingestion_job import IngestionJob
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.ingestion.lineage_service import lineage_service
from app.services.ingestion.normaliser_registry_service import normaliser_registry_service
from app.services.ingestion.table_extraction_service import stable_json_hash


BUILTIN_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "che_vitalstats_pdf": {
        "contract_key": "che_vitalstats_pdf_v1",
        "name": "CHE VitalStats PDF Source Contract",
        "description": "Expected metadata for discovered or downloaded CHE VitalStats publications.",
        "record_type": "che_vitalstats_pdf",
        "schema_definition": {
            "required_raw_fields": ["url", "filename", "year", "download_status"],
            "required_normalised_fields": ["series", "year", "source", "context_domain"],
        },
        "cleaning_profile": {
            "trim_strings": True,
            "collapse_whitespace": True,
            "preserve_raw_payload": True,
            "normaliser_key": "che_vitalstats_v1",
        },
        "quality_thresholds": {"minimum_score_for_model_use": 0.80},
        "rules": [
            {
                "rule_key": "che_pdf_content_hash_present",
                "rule_type": "content_hash_present",
                "severity": "warning",
                "description": "Downloaded CHE PDFs should have a content hash unless the job was a dry run.",
                "expectation": {},
            },
            {
                "rule_key": "che_pdf_required_fields",
                "rule_type": "required_fields",
                "severity": "error",
                "description": "CHE PDF records must include source publication metadata.",
                "expectation": {
                    "raw_fields": ["url", "filename", "year", "download_status"],
                    "normalised_fields": ["series", "year", "source", "context_domain"],
                },
            },
        ],
    },
    "che_vitalstats_table": {
        "contract_key": "che_vitalstats_table_v1",
        "name": "CHE VitalStats Extracted Table Contract",
        "description": "Expected payload for semi-structured tables extracted from CHE VitalStats PDFs.",
        "record_type": "che_vitalstats_table",
        "schema_definition": {
            "required_raw_fields": ["source_file", "page", "table_index", "raw_data", "rows"],
            "required_normalised_fields": ["year", "row_count", "column_count", "context_domain"],
        },
        "cleaning_profile": {
            "trim_strings": True,
            "collapse_whitespace": True,
            "drop_empty_rows": True,
            "preserve_raw_payload": True,
            "normaliser_key": "che_vitalstats_v1",
        },
        "quality_thresholds": {"minimum_score_for_model_use": 0.75},
        "rules": [
            {
                "rule_key": "che_table_required_fields",
                "rule_type": "required_fields",
                "severity": "error",
                "description": "CHE extracted table records must include source metadata and row payloads.",
                "expectation": {
                    "raw_fields": ["source_file", "page", "table_index", "raw_data", "rows"],
                    "normalised_fields": ["row_count", "column_count", "context_domain"],
                },
            },
            {
                "rule_key": "che_table_has_rows",
                "rule_type": "minimum_count",
                "field_path": "raw_payload.rows",
                "severity": "error",
                "description": "CHE extracted tables must contain at least one row.",
                "expectation": {"minimum": 1},
            },
        ],
    },
    "statssa_qlfs_pdf": {
        "contract_key": "statssa_qlfs_pdf_v2",
        "version": "2.0.0",
        "name": "StatsSA QLFS PDF Source Contract",
        "description": "Expected metadata for downloaded or discovered StatsSA QLFS PDF publications.",
        "record_type": "statssa_qlfs_pdf",
        "schema_definition": {
            "required_raw_fields": ["url", "filename", "year", "quarter", "download_status"],
            "required_normalised_fields": ["series", "year", "quarter", "source"],
            "evidence_role": "quarterly_contextual_labour_market_aggregate",
            "empirical_scope": "official_publication_metadata_and_extracted_tables",
            "prohibited_interpretations": [
                "vacancy_count",
                "vacancy_skill_requirement",
                "real_time_job_demand",
            ],
            "required_observation_fields": [
                "survey_year",
                "survey_quarter",
                "geography",
                "published_estimate",
                "unit",
                "table_or_variable_reference",
            ],
            "conditional_observation_fields": [
                "occupation_classification_version",
                "weighting_basis",
                "standard_error_or_confidence_interval",
                "comparability_note",
            ],
        },
        "cleaning_profile": {
            "trim_strings": True,
            "normalise_quarter": True,
            "preserve_raw_payload": True,
        },
        "quality_thresholds": {"minimum_score_for_model_use": 0.80},
        "rules": [
            {
                "rule_key": "pdf_content_hash_present",
                "rule_type": "content_hash_present",
                "severity": "warning",
                "description": "Downloaded PDFs should have a content hash unless the job was a dry run.",
                "expectation": {},
            },
            {
                "rule_key": "pdf_required_fields",
                "rule_type": "required_fields",
                "severity": "error",
                "description": "StatsSA PDF records must include discovery and normalised metadata.",
                "expectation": {
                    "raw_fields": ["url", "filename", "year", "quarter", "download_status"],
                    "normalised_fields": ["series", "year", "quarter", "source"],
                },
            },
            {
                "rule_key": "pdf_quarter_allowed",
                "rule_type": "allowed_values",
                "field_path": "normalised_payload.quarter",
                "severity": "error",
                "description": "Quarter values must be normalised to Q1-Q4.",
                "expectation": {"values": ["Q1", "Q2", "Q3", "Q4"]},
            },
        ],
    },
    "statssa_qlfs_table": {
        "contract_key": "statssa_qlfs_table_v2",
        "version": "2.0.0",
        "name": "StatsSA QLFS Extracted Table Contract",
        "description": "Expected payload for semi-structured tables extracted from QLFS PDFs.",
        "record_type": "statssa_qlfs_table",
        "schema_definition": {
            "required_raw_fields": ["source_file", "page", "table_index", "raw_data", "rows"],
            "required_normalised_fields": ["year", "quarter", "row_count", "column_count"],
            "evidence_role": "candidate_quarterly_contextual_aggregate",
            "prohibited_interpretations": [
                "vacancy_count",
                "vacancy_skill_requirement",
                "monthly_skill_demand",
            ],
            "promotion_gate": "table title, population, geography, unit, weighting, footnotes and classification must be validated before model use",
        },
        "cleaning_profile": {
            "trim_strings": True,
            "drop_empty_rows": True,
            "preserve_raw_payload": True,
        },
        "quality_thresholds": {"minimum_score_for_model_use": 0.75},
        "rules": [
            {
                "rule_key": "table_required_fields",
                "rule_type": "required_fields",
                "severity": "error",
                "description": "Extracted table records must include source metadata, raw data, and row payloads.",
                "expectation": {
                    "raw_fields": ["source_file", "page", "table_index", "raw_data", "rows"],
                    "normalised_fields": ["row_count", "column_count"],
                },
            },
            {
                "rule_key": "table_has_rows",
                "rule_type": "minimum_count",
                "field_path": "raw_payload.rows",
                "severity": "error",
                "description": "Extracted tables must contain at least one data row.",
                "expectation": {"minimum": 1},
            },
            {
                "rule_key": "table_column_count_positive",
                "rule_type": "minimum_value",
                "field_path": "normalised_payload.column_count",
                "severity": "warning",
                "description": "Extracted tables should have at least one detected column.",
                "expectation": {"minimum": 1},
            },
        ],
    },
    "curriculum_pdf": {
        "contract_key": "curriculum_pdf_v1",
        "name": "Curriculum PDF Source Contract",
        "description": "Expected metadata for uploaded curriculum PDF source files.",
        "record_type": "curriculum_pdf",
        "schema_definition": {
            "required_raw_fields": ["original_filename", "document_key", "mime_type", "file_size"],
            "required_normalised_fields": ["title", "version_number"],
        },
        "cleaning_profile": {
            "trim_strings": True,
            "preserve_raw_payload": True,
        },
        "quality_thresholds": {"minimum_score_for_model_use": 0.80},
        "rules": [
            {
                "rule_key": "curriculum_pdf_required_fields",
                "rule_type": "required_fields",
                "severity": "error",
                "description": "Curriculum PDF records must include file and document metadata.",
                "expectation": {
                    "raw_fields": ["original_filename", "document_key", "mime_type", "file_size"],
                    "normalised_fields": ["title", "version_number"],
                },
            },
            {
                "rule_key": "curriculum_pdf_file_size_positive",
                "rule_type": "minimum_value",
                "field_path": "raw_payload.file_size",
                "severity": "warning",
                "description": "Uploaded curriculum PDFs should have a positive file size.",
                "expectation": {"minimum": 1},
            },
        ],
    },
    "curriculum_extracted_text": {
        "contract_key": "curriculum_extracted_text_v1",
        "name": "Curriculum Extracted Text Contract",
        "description": "Expected payload for full text extracted from curriculum PDFs.",
        "record_type": "curriculum_extracted_text",
        "schema_definition": {
            "required_raw_fields": ["text", "pages", "page_count"],
            "required_normalised_fields": ["page_count", "text_length"],
        },
        "cleaning_profile": {
            "trim_strings": True,
            "collapse_whitespace": False,
            "preserve_raw_payload": True,
        },
        "quality_thresholds": {"minimum_score_for_model_use": 0.80},
        "rules": [
            {
                "rule_key": "curriculum_text_required_fields",
                "rule_type": "required_fields",
                "severity": "error",
                "description": "Extracted curriculum text records must include text and page metadata.",
                "expectation": {
                    "raw_fields": ["text", "pages", "page_count"],
                    "normalised_fields": ["page_count", "text_length"],
                },
            },
            {
                "rule_key": "curriculum_text_page_count_positive",
                "rule_type": "minimum_value",
                "field_path": "normalised_payload.page_count",
                "severity": "warning",
                "description": "Extracted curriculum text should include at least one page.",
                "expectation": {"minimum": 1},
            },
        ],
    },
    "curriculum_document_chunk": {
        "contract_key": "curriculum_document_chunk_v1",
        "name": "Curriculum PDF Chunk Contract",
        "description": "Expected metadata for text chunks extracted from curriculum PDFs.",
        "record_type": "curriculum_document_chunk",
        "schema_definition": {
            "required_raw_fields": ["content"],
            "required_normalised_fields": ["chunk_index", "token_count"],
        },
        "cleaning_profile": {
            "trim_strings": True,
            "collapse_whitespace": True,
            "preserve_raw_payload": True,
        },
        "quality_thresholds": {"minimum_score_for_model_use": 0.80},
        "rules": [
            {
                "rule_key": "chunk_content_present",
                "rule_type": "required_fields",
                "severity": "error",
                "description": "Curriculum chunks must include extracted text content.",
                "expectation": {
                    "raw_fields": ["content"],
                    "normalised_fields": ["chunk_index", "token_count"],
                },
            },
            {
                "rule_key": "chunk_token_count_positive",
                "rule_type": "minimum_value",
                "field_path": "normalised_payload.token_count",
                "severity": "warning",
                "description": "Curriculum chunks should include a positive token count.",
                "expectation": {"minimum": 1},
            },
        ],
    },
}


class DataQualityService:
    """
    Validates and cleans raw ingestion records using source contracts.
    """

    def list_contracts(self, db: Session) -> List[IngestionContract]:
        return (
            db.query(IngestionContract)
            .order_by(IngestionContract.record_type, IngestionContract.version)
            .all()
        )

    def ensure_builtin_contract(
        self,
        db: Session,
        source: DataSource,
        record_type: str,
    ) -> Optional[IngestionContract]:
        spec = BUILTIN_CONTRACTS.get(record_type)
        if not spec:
            return None

        contract = (
            db.query(IngestionContract)
            .filter(
                IngestionContract.source_id == source.source_id,
                IngestionContract.contract_key == spec["contract_key"],
                IngestionContract.version == spec.get("version", "1.0.0"),
            )
            .first()
        )
        if not contract:
            contract = IngestionContract(
                source_id=source.source_id,
                contract_key=spec["contract_key"],
                name=spec["name"],
                version=spec.get("version", "1.0.0"),
                record_type=record_type,
                description=spec["description"],
                schema_definition=spec["schema_definition"],
                cleaning_profile=spec["cleaning_profile"],
                quality_thresholds=spec["quality_thresholds"],
                status="active",
            )
            db.add(contract)
            db.flush()

        existing_rules = {
            row.rule_key
            for row in db.query(DataQualityRule)
            .filter(DataQualityRule.contract_id == contract.contract_id)
            .all()
        }
        for rule in spec["rules"]:
            if rule["rule_key"] in existing_rules:
                continue
            db.add(
                DataQualityRule(
                    contract_id=contract.contract_id,
                    rule_key=rule["rule_key"],
                    rule_type=rule["rule_type"],
                    field_path=rule.get("field_path"),
                    severity=rule["severity"],
                    description=rule["description"],
                    expectation=rule["expectation"],
                    is_active=True,
                )
            )
        db.flush()
        return contract

    def run_job_quality(
        self,
        db: Session,
        job: IngestionJob,
        actor_id: Optional[str] = None,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        records = (
            db.query(RawIngestionRecord)
            .filter(RawIngestionRecord.job_id == job.job_id)
            .order_by(RawIngestionRecord.created_at.asc())
            .limit(limit)
            .all()
        )

        db.query(DataQualityCheck).filter(DataQualityCheck.job_id == job.job_id).delete(
            synchronize_session=False
        )
        db.query(CleanedIngestionRecord).filter(
            CleanedIngestionRecord.job_id == job.job_id
        ).delete(synchronize_session=False)
        db.flush()

        summary = {
            "job_id": str(job.job_id),
            "records_seen": len(records),
            "records_cleaned": 0,
            "records_failed": 0,
            "checks_passed": 0,
            "checks_warned": 0,
            "checks_failed": 0,
            "contracts_created_or_used": set(),
        }

        for record in records:
            contract = None
            if record.source:
                contract = self.ensure_builtin_contract(db, record.source, record.record_type)

            checks = self.evaluate_record(db, job, record, contract)
            score = self.calculate_quality_score(checks)
            status = self.resolve_record_status(checks)
            record.validation_status = status

            for check in checks:
                db.add(check)
                if check.status == "passed":
                    summary["checks_passed"] += 1
                elif check.status == "warning":
                    summary["checks_warned"] += 1
                elif check.status == "failed":
                    summary["checks_failed"] += 1

            if status == "failed":
                summary["records_failed"] += 1
                continue

            normaliser = normaliser_registry_service.resolve_for_record(db, record, contract)
            cleaned_payload = self.clean_payload(record, contract)
            cleaned_payload = normaliser_registry_service.normalise_payload(
                record=record,
                base_payload=cleaned_payload,
                definition=normaliser,
            )
            content_hash = stable_json_hash(cleaned_payload)
            cleaned = CleanedIngestionRecord(
                raw_record_id=record.record_id,
                job_id=job.job_id,
                source_id=record.source_id,
                tenant_id=record.tenant_id,
                contract_id=contract.contract_id if contract else None,
                normaliser_definition_id=normaliser.normaliser_definition_id if normaliser else None,
                normaliser_key=normaliser.normaliser_key if normaliser else None,
                normaliser_version=normaliser.version if normaliser else None,
                cleaning_status="cleaned_with_warnings" if status == "warning" else "cleaned",
                content_hash=content_hash,
                quality_score=score,
                cleaned_payload=cleaned_payload,
                cleaning_metadata={
                    "source_record_id": record.source_record_id,
                    "record_type": record.record_type,
                    "contract_key": contract.contract_key if contract else None,
                    "normaliser_key": normaliser.normaliser_key if normaliser else None,
                    "normaliser_version": normaliser.version if normaliser else None,
                    "quality_status": status,
                },
            )
            db.add(cleaned)
            db.flush()
            summary["records_cleaned"] += 1

            if contract:
                summary["contracts_created_or_used"].add(contract.contract_key)

            lineage_service.record_event(
                db=db,
                job_id=job.job_id,
                source_id=record.source_id,
                input_record_id=record.record_id,
                source_system=record.source.name if record.source else "unknown",
                processing_stage="data_quality_cleaning",
                transformation_description="Validated raw ingestion record and produced cleaned model-ready payload.",
                actor_id=actor_id,
                metadata={
                    "cleaned_record_id": str(cleaned.cleaned_record_id),
                    "normaliser_key": normaliser.normaliser_key if normaliser else None,
                    "normaliser_version": normaliser.version if normaliser else None,
                    "quality_score": score,
                    "quality_status": status,
                },
            )

        summary["contracts_created_or_used"] = sorted(summary["contracts_created_or_used"])
        return summary

    def evaluate_record(
        self,
        db: Session,
        job: IngestionJob,
        record: RawIngestionRecord,
        contract: Optional[IngestionContract],
    ) -> List[DataQualityCheck]:
        if not contract:
            return [
                self.build_check(
                    job=job,
                    record=record,
                    contract=None,
                    rule=None,
                    status="warning",
                    severity="warning",
                    message=f"No ingestion contract is registered for record type {record.record_type}.",
                    observed_value={"record_type": record.record_type},
                )
            ]

        rules = (
            db.query(DataQualityRule)
            .filter(
                DataQualityRule.contract_id == contract.contract_id,
                DataQualityRule.is_active.is_(True),
            )
            .order_by(DataQualityRule.rule_key.asc())
            .all()
        )
        return [self.evaluate_rule(job, record, contract, rule) for rule in rules]

    def evaluate_rule(
        self,
        job: IngestionJob,
        record: RawIngestionRecord,
        contract: IngestionContract,
        rule: DataQualityRule,
    ) -> DataQualityCheck:
        status = "passed"
        message = "Quality rule passed."
        observed: Dict[str, Any] = {}

        if rule.rule_type == "content_hash_present":
            status = "passed" if bool(record.content_hash) else "warning"
            message = "Content hash is present." if status == "passed" else "Content hash is missing."
            observed = {"content_hash_present": bool(record.content_hash)}

        elif rule.rule_type == "required_fields":
            raw_missing = self.missing_fields(record.raw_payload, rule.expectation.get("raw_fields", []))
            normalised_missing = self.missing_fields(
                record.normalised_payload,
                rule.expectation.get("normalised_fields", []),
            )
            missing = {"raw_payload": raw_missing, "normalised_payload": normalised_missing}
            status = "failed" if raw_missing or normalised_missing else "passed"
            message = "Required fields are present." if status == "passed" else "Required fields are missing."
            observed = missing

        elif rule.rule_type == "allowed_values":
            value = self.get_path(record, rule.field_path)
            allowed = set(rule.expectation.get("values", []))
            status = "passed" if value in allowed else "failed"
            message = "Value is allowed." if status == "passed" else "Value is outside the allowed set."
            observed = {"value": value, "allowed": sorted(allowed)}

        elif rule.rule_type == "minimum_count":
            value = self.get_path(record, rule.field_path)
            count = len(value) if isinstance(value, list) else 0
            minimum = int(rule.expectation.get("minimum", 1))
            status = "passed" if count >= minimum else "failed"
            message = "Minimum count satisfied." if status == "passed" else "Minimum count not satisfied."
            observed = {"count": count, "minimum": minimum}

        elif rule.rule_type == "minimum_value":
            value = self.get_path(record, rule.field_path)
            minimum = float(rule.expectation.get("minimum", 0))
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                numeric_value = None
            status = "passed" if numeric_value is not None and numeric_value >= minimum else "warning"
            message = "Minimum value satisfied." if status == "passed" else "Minimum value not satisfied."
            observed = {"value": value, "minimum": minimum}

        return self.build_check(
            job=job,
            record=record,
            contract=contract,
            rule=rule,
            status=status,
            severity=rule.severity,
            message=message,
            observed_value=observed,
        )

    @staticmethod
    def build_check(
        job: IngestionJob,
        record: RawIngestionRecord,
        contract: Optional[IngestionContract],
        rule: Optional[DataQualityRule],
        status: str,
        severity: str,
        message: str,
        observed_value: Dict[str, Any],
    ) -> DataQualityCheck:
        return DataQualityCheck(
            job_id=job.job_id,
            source_id=record.source_id,
            raw_record_id=record.record_id,
            contract_id=contract.contract_id if contract else None,
            rule_id=rule.rule_id if rule else None,
            check_scope="record",
            status=status,
            severity=severity,
            message=message,
            observed_value=observed_value,
            check_metadata={
                "record_type": record.record_type,
                "rule_key": rule.rule_key if rule else None,
            },
        )

    @staticmethod
    def missing_fields(payload: Dict[str, Any], fields: Iterable[str]) -> List[str]:
        return [
            field
            for field in fields
            if payload.get(field) is None or payload.get(field) == ""
        ]

    @staticmethod
    def get_path(record: RawIngestionRecord, field_path: Optional[str]) -> Any:
        if not field_path:
            return None

        root_name, _, nested = field_path.partition(".")
        if root_name == "raw_payload":
            value: Any = record.raw_payload
        elif root_name == "normalised_payload":
            value = record.normalised_payload
        else:
            return None

        for part in nested.split("."):
            if not part:
                continue
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def clean_payload(
        self,
        record: RawIngestionRecord,
        contract: Optional[IngestionContract],
    ) -> Dict[str, Any]:
        profile = contract.cleaning_profile if contract else {}
        raw_payload = deepcopy(record.raw_payload)
        normalised_payload = deepcopy(record.normalised_payload)

        if profile.get("trim_strings", True):
            raw_payload = self.clean_value(raw_payload, collapse_whitespace=profile.get("collapse_whitespace", False))
            normalised_payload = self.clean_value(normalised_payload, collapse_whitespace=True)

        if profile.get("drop_empty_rows") and isinstance(raw_payload.get("rows"), list):
            raw_payload["rows"] = [
                row for row in raw_payload["rows"] if isinstance(row, dict) and any(v not in (None, "") for v in row.values())
            ]

        return {
            "record_type": record.record_type,
            "source_record_id": record.source_record_id,
            "storage_uri": record.storage_uri,
            "content_hash": record.content_hash,
            "normalised_payload": normalised_payload,
            "raw_payload": raw_payload if profile.get("preserve_raw_payload", True) else {},
        }

    def clean_value(self, value: Any, collapse_whitespace: bool = False) -> Any:
        if isinstance(value, dict):
            return {key: self.clean_value(item, collapse_whitespace) for key, item in value.items()}
        if isinstance(value, list):
            return [self.clean_value(item, collapse_whitespace) for item in value]
        if isinstance(value, str):
            cleaned = value.strip()
            if collapse_whitespace:
                cleaned = " ".join(cleaned.split())
            return cleaned
        return value

    @staticmethod
    def calculate_quality_score(checks: List[DataQualityCheck]) -> float:
        if not checks:
            return 0.0
        penalty = 0.0
        for check in checks:
            if check.status == "failed":
                penalty += 0.35 if check.severity == "error" else 0.20
            elif check.status == "warning":
                penalty += 0.10
        return max(0.0, round(1.0 - penalty, 4))

    @staticmethod
    def resolve_record_status(checks: List[DataQualityCheck]) -> str:
        if any(check.status == "failed" and check.severity == "error" for check in checks):
            return "failed"
        if any(check.status in {"failed", "warning"} for check in checks):
            return "warning"
        return "valid"

    def job_quality_summary(self, db: Session, job_id: UUID) -> Dict[str, Any]:
        status_rows = (
            db.query(DataQualityCheck.status, func.count(DataQualityCheck.check_id))
            .filter(DataQualityCheck.job_id == job_id)
            .group_by(DataQualityCheck.status)
            .all()
        )
        cleaned_rows = (
            db.query(CleanedIngestionRecord.cleaning_status, func.count(CleanedIngestionRecord.cleaned_record_id))
            .filter(CleanedIngestionRecord.job_id == job_id)
            .group_by(CleanedIngestionRecord.cleaning_status)
            .all()
        )
        score = (
            db.query(func.avg(CleanedIngestionRecord.quality_score))
            .filter(CleanedIngestionRecord.job_id == job_id)
            .scalar()
        )
        return {
            "job_id": str(job_id),
            "checks": {status: count for status, count in status_rows},
            "cleaned_records": {status: count for status, count in cleaned_rows},
            "average_quality_score": round(float(score), 4) if score is not None else None,
        }


data_quality_service = DataQualityService()
