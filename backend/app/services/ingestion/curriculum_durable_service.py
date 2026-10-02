"""Staging and durable execution for curriculum document uploads."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ingestion.curriculum_pdf_service import (
    curriculum_pdf_ingestion_service,
    safe_filename,
)


def staging_root() -> Path:
    root = (settings.curriculum_upload_path / "_staging").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def stage_curriculum_upload(file_bytes: bytes, original_filename: str) -> Path:
    if not file_bytes:
        raise ValueError("Uploaded file is empty")
    root = staging_root()
    target = root / f"{uuid.uuid4().hex}_{safe_filename(original_filename)}"
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.write_bytes(file_bytes)
    os.replace(temporary, target)
    return target


def run_staged_curriculum_upload(
    db: Session,
    *,
    staging_path: str,
    original_filename: str,
    mime_type: Optional[str],
    actor_id: str,
    actor_type: str,
    title: Optional[str] = None,
    faculty: Optional[str] = None,
    department: Optional[str] = None,
    programme: Optional[str] = None,
    document_key: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    root = staging_root()
    supplied_path = Path(staging_path)
    path = (
        supplied_path.resolve()
        if supplied_path.is_absolute()
        else (root / supplied_path.name).resolve()
    )
    if path.parent != root:
        raise ValueError("Invalid curriculum staging path")
    if not path.is_file():
        raise FileNotFoundError(f"Staged curriculum upload not found: {path.name}")

    result = curriculum_pdf_ingestion_service.ingest_upload(
        db=db,
        file_bytes=path.read_bytes(),
        original_filename=original_filename,
        mime_type=mime_type,
        actor_id=actor_id,
        actor_type=actor_type,
        title=title,
        faculty=faculty,
        department=department,
        programme=programme,
        document_key=document_key,
        description=description,
        metadata=metadata,
        tenant_id=uuid.UUID(str(tenant_id)) if tenant_id else None,
    )
    document = result["document"]
    version = result["version"]
    ingestion_job = result["job"]
    path.unlink(missing_ok=True)
    return {
        "document_id": str(document.document_id),
        "version_id": str(version.version_id),
        "ingestion_job_id": str(ingestion_job.job_id),
        "ingestion_status": ingestion_job.status,
        "chunk_count": int(result.get("chunk_count") or 0),
        "version_number": version.version_number,
        "original_filename": original_filename,
    }
