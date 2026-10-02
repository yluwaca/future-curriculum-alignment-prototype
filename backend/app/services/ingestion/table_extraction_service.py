"""
Persistence helpers for document table extraction.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.extracted_table import ExtractedTable
from app.models.extracted_table_row import ExtractedTableRow
from app.models.ingestion_job import IngestionJob
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.ingestion.canonical_table_mapping_service import canonical_table_mapping_service


def to_jsonable(value: Any) -> Any:
    """
    Convert pandas/numpy scalar values into JSONB-safe Python values.
    """

    if value is None:
        return None

    if isinstance(value, float) and math.isnan(value):
        return None

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        float_value = float(value)
        return None if math.isnan(float_value) else float_value

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}

    if isinstance(value, list):
        return [to_jsonable(item) for item in value]

    if pd.isna(value):
        return None

    return value


def stable_json_hash(payload: Dict[str, Any]) -> str:
    serialised = json.dumps(
        to_jsonable(payload),
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


class TableExtractionPersistenceService:
    """
    Stores extracted table metadata and row-level payloads.
    """

    def create_table_from_dataframe(
        self,
        db: Session,
        job: IngestionJob,
        raw_record: RawIngestionRecord,
        pdf_file: Path,
        table_info: Dict[str, Any],
        rows: List[Dict[str, Any]],
    ) -> ExtractedTable:
        json_rows = [to_jsonable(row) for row in rows]
        columns = list(json_rows[0].keys()) if json_rows else []

        extracted_table = ExtractedTable(
            job_id=job.job_id,
            source_id=job.source_id,
            raw_record_id=raw_record.record_id,
            source_file=pdf_file.name,
            document_uri=str(pdf_file),
            page_number=table_info.get("page"),
            table_index=table_info.get("table_index"),
            title=table_info.get("title"),
            year=table_info.get("year"),
            quarter=table_info.get("quarter"),
            series_code=table_info.get("series_code"),
            row_count=len(json_rows),
            column_count=len(columns),
            columns=columns,
            extraction_method=table_info.get("extraction_method", "pdfplumber"),
            extraction_metadata={
                "timestamp": table_info.get("timestamp"),
                "raw_row_count": len(table_info.get("raw_data") or []),
                "source_record_id": raw_record.source_record_id,
                "canonical_table": table_info.get("canonical_table"),
                "context_domain": table_info.get("context_domain"),
            },
        )
        db.add(extracted_table)
        db.flush()

        for row_number, row in enumerate(json_rows, start=1):
            row_record = ExtractedTableRow(
                table_id=extracted_table.table_id,
                row_number=row_number,
                row_payload=row,
                normalised_payload=self.normalise_row(row),
                content_hash=stable_json_hash(row),
            )
            db.add(row_record)

        db.flush()
        return extracted_table

    @staticmethod
    def normalise_row(row: Dict[str, Any]) -> Dict[str, Any]:
        row_role = TableExtractionPersistenceService.classify_row(row)
        canonical_mapping = canonical_table_mapping_service.map_row(row)
        normalised = {
            "year": row.get("meta_year"),
            "quarter": row.get("meta_quarter"),
            "source_file": row.get("meta_source_file"),
            "table_title": row.get("meta_table_title"),
            "canonical_table": row.get("meta_canonical_table"),
            **canonical_mapping,
            "row_role": row_role,
            "quality_score": TableExtractionPersistenceService.row_quality_score(row, row_role),
            "numeric_values": {},
            "descriptors": {},
        }

        for key, value in row.items():
            if key.startswith("meta_") or value is None:
                continue

            if isinstance(value, (int, float)):
                normalised["numeric_values"][key] = value
            else:
                normalised["descriptors"][key] = value

        return normalised

    @staticmethod
    def classify_row(row: Dict[str, Any]) -> str:
        values = [
            str(value).strip()
            for key, value in row.items()
            if not str(key).startswith("meta_") and value is not None and str(value).strip()
        ]
        text = " ".join(values).lower()
        numeric_count = sum(1 for value in row.values() if isinstance(value, (int, float)))
        descriptor_count = len(values) - numeric_count
        if not values:
            return "noise"
        if any(marker in text for marker in ["source:", "note:", "notes:", "n/a", "not applicable"]):
            return "note"
        if any(marker in text for marker in ["footnote", "excluding", "including", "due to rounding"]):
            return "footnote"
        if "total" in text and numeric_count:
            return "total"
        if numeric_count >= 1 and descriptor_count >= 1:
            return "fact"
        if numeric_count == 0 and descriptor_count >= 1:
            return "header"
        return "noise"

    @staticmethod
    def row_quality_score(row: Dict[str, Any], row_role: str) -> float:
        if row_role == "fact":
            numeric_count = sum(1 for value in row.values() if isinstance(value, (int, float)))
            descriptor_count = sum(
                1
                for key, value in row.items()
                if not str(key).startswith("meta_")
                and value is not None
                and not isinstance(value, (int, float))
            )
            return min(1.0, 0.45 + (numeric_count * 0.12) + min(descriptor_count, 2) * 0.1)
        if row_role in {"total", "note", "footnote"}:
            return 0.55
        if row_role == "header":
            return 0.35
        return 0.15


table_extraction_service = TableExtractionPersistenceService()
