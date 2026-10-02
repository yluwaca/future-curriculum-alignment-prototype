"""
Curriculum PDF ingestion service.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from xml.etree import ElementTree
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import pandas as pd
import pdfplumber
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.academic_department import AcademicDepartment
from app.models.academic_faculty import AcademicFaculty
from app.models.academic_programme import AcademicProgramme
from app.models.curriculum_document import CurriculumDocument
from app.models.curriculum_document_version import CurriculumDocumentVersion
from app.models.curriculum_module import CurriculumModule
from app.models.document_chunk import DocumentChunk
from app.services.audit_service import log_audit_event
from app.services.ingestion.job_service import ingestion_job_service
from app.services.ingestion.lineage_service import lineage_service
from app.services.curriculum_subject_profile_service import curriculum_subject_profile_service


CURRICULUM_SOURCE_KEY = "curriculum_pdf_upload"
SUPPORTED_CURRICULUM_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".xlsx"}
DEFAULT_CHUNK_SIZE = 1800
DEFAULT_CHUNK_OVERLAP = 200


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:120] or "curriculum-document"


def safe_filename(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return name[:180] or "curriculum.pdf"


SECTION_PATTERNS = [
    ("module_outcome", re.compile(r"\b(module|learning)\s+outcomes?\b", re.IGNORECASE)),
    ("assessment_criteria", re.compile(r"\bassessment\s+criteria\b", re.IGNORECASE)),
    ("competency", re.compile(r"\b(competenc(?:y|ies)|graduate attributes?)\b", re.IGNORECASE)),
    ("learning_objective", re.compile(r"\b(learning\s+objectives?|objectives?)\b", re.IGNORECASE)),
    ("module_topic", re.compile(r"\b(module\s+content|syllabus|topics?|units?|course\s+content)\b", re.IGNORECASE)),
    ("assessment_method", re.compile(r"\b(assessment\s+methods?|assessment\s+tasks?|formative|summative)\b", re.IGNORECASE)),
    ("module_metadata", re.compile(r"\b(module\s+code|module\s+name|credits?|nqf\s+level|prerequisites?)\b", re.IGNORECASE)),
]

MODULE_CODE_PATTERN = re.compile(r"\b([A-Z]{2,8}[0-9]{3,4}[A-Z0-9]?)\b")
OUTCOME_CODE_PATTERN = re.compile(r"^(?:SO|LO|ELO|CO|PO|GA)\d{1,3}$", re.IGNORECASE)
CREDIT_PATTERN = re.compile(r"\b(?:credits?|credit\s+value|saqa\s+credits?)\s*[:\-]?\s*(\d{1,3})\b|\b(\d{1,3})\s+credits?\b", re.IGNORECASE)
NQF_PATTERN = re.compile(r"\b(?:NQF\s*(?:level)?|level)\s*[:\-]?\s*(\d{1,2})\b", re.IGNORECASE)
ASSESSMENT_WEIGHT_PATTERN = re.compile(r"\b(assignment|test|exam|examination|project|portfolio|practical|presentation|quiz|case\s+study|laboratory)\b.*?(\d{1,3})\s*%", re.IGNORECASE)

MODULE_LABEL_PATTERNS = [
    re.compile(r"\bmodule\s+code\s*[:\-]?\s*([A-Z]{2,8}[0-9]{1,4}[A-Z0-9]?)\b", re.IGNORECASE),
    re.compile(r"\b(subject|course)\s+code\s*[:\-]?\s*([A-Z]{2,8}[0-9]{1,4}[A-Z0-9]?)\b", re.IGNORECASE),
]
MODULE_NAME_PATTERNS = [
    re.compile(r"\bmodule\s+name\s*[:\-]?\s*(.{3,180})$", re.IGNORECASE),
    re.compile(r"\b(subject|course)\s+name\s*[:\-]?\s*(.{3,180})$", re.IGNORECASE),
    re.compile(r"\btitle\s*[:\-]?\s*(.{3,180})$", re.IGNORECASE),
]
OUTCOME_ITEM_PATTERN = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]?|[a-z][.)]|[-*])\s+(.{12,})$", re.IGNORECASE)
ASSESSMENT_CRITERIA_PATTERN = re.compile(r"\b(assessment\s+criteria|criteria\s+for\s+assessment|marking\s+criteria|rubric)\b", re.IGNORECASE)
TOPIC_PATTERN = re.compile(r"^\s*(?:week|unit|topic|chapter|lesson|theme)\s*\d*\s*[:\-]?\s+(.{5,})$", re.IGNORECASE)
CURRICULUM_EVIDENCE_TYPES = {
    "study_guide": {
        "label": "Study guide",
        "definition": "Teaching document that usually contains weekly topics, assessments, outcomes and learning resources.",
    },
    "syllabus": {
        "label": "Syllabus",
        "definition": "Module-level outline of content, topics, learning outcomes and assessment structure.",
    },
    "module_descriptor": {
        "label": "Module descriptor",
        "definition": "Formal module metadata including module code, credits, NQF level, outcomes and prerequisites.",
    },
    "qualification_standard": {
        "label": "Qualification standard",
        "definition": "External or institutional standard defining purpose, exit-level outcomes and expected competencies.",
    },
    "prospectus": {
        "label": "Prospectus",
        "definition": "Public programme information useful for programme structure and admission context, but usually weaker than real curriculum evidence.",
    },
    "curriculum_map": {
        "label": "Curriculum map",
        "definition": "Mapping between programme outcomes, modules, assessments and skill coverage.",
    },
}


class CurriculumPDFIngestionService:
    """
    Uploads, versions, extracts, chunks, and records lineage for curriculum PDFs.
    """

    def ensure_source(self, db: Session, tenant_id: UUID):
        return ingestion_job_service.get_or_create_source(
            db=db,
            source_key=f"{CURRICULUM_SOURCE_KEY}_{tenant_id}",
            defaults={
                "name": "Curriculum PDF Uploads",
                "source_type": "uploaded_pdf",
                "source_category": "curriculum",
                "connector_type": "curriculum_pdf",
                "connector_key": "curriculum_pdf_upload",
                "base_url": None,
                "storage_path": str(settings.curriculum_upload_path),
                "refresh_policy": "manual",
                "retry_policy": {
                    "max_attempts": 2,
                    "initial_backoff_seconds": 60,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 900,
                    "open_circuit_after_failures": 5,
                    "circuit_open_seconds": 1800,
                },
                "owner": "system",
                "status": "active",
                "is_authorised": True,
                "tenant_id": tenant_id,
                "source_scope": "tenant",
                "config": {},
                "auth_config": {},
            },
        )

    def ingest_upload(
        self,
        db: Session,
        file_bytes: bytes,
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
        tenant_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        if not file_bytes:
            raise ValueError("Uploaded file is empty")

        source_format = self.detect_source_format(original_filename, mime_type)
        if source_format not in {"pdf", "docx", "txt", "csv", "xlsx"}:
            raise ValueError("Only PDF, DOCX, TXT, CSV, and Excel curriculum documents are supported")

        if tenant_id is None:
            raise ValueError("Tenant context is required for curriculum ingestion")
        tenant_id = UUID(str(tenant_id))
        source = self.ensure_source(db, tenant_id)

        if not source.is_authorised:
            raise ValueError("Curriculum PDF upload source is not authorised")

        document_title = title or Path(original_filename).stem
        resolved_key = slugify(document_key or document_title)
        content_hash = sha256_bytes(file_bytes)
        hierarchy = self.ensure_hierarchy(
            db=db,
            faculty_name=faculty,
            department_name=department,
            programme_name=programme,
        )

        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type="curriculum_pdf_upload",
            triggered_by=actor_id,
            parameters={
                "filename": original_filename,
                "title": document_title,
                "document_key": resolved_key,
                "faculty": faculty,
                "department": department,
                "programme": programme,
            },
        )
        ingestion_job_service.mark_running(db, job, total=1)

        try:
            document = (
                db.query(CurriculumDocument)
                .filter(
                    CurriculumDocument.document_key == resolved_key,
                    CurriculumDocument.tenant_id == tenant_id,
                )
                .first()
            )

            if not document:
                document = CurriculumDocument(
                    document_key=resolved_key,
                    tenant_id=source.tenant_id,
                    faculty_id=hierarchy.get("faculty_id"),
                    department_id=hierarchy.get("department_id"),
                    programme_id=hierarchy.get("programme_id"),
                    title=document_title,
                    faculty=faculty,
                    department=department,
                    programme=programme,
                    description=description,
                    document_metadata=metadata or {},
                    created_by=actor_id,
                    current_version_number=0,
                )
                db.add(document)
                db.flush()
            else:
                document.title = document_title or document.title
                document.tenant_id = source.tenant_id or document.tenant_id
                document.faculty_id = hierarchy.get("faculty_id") or document.faculty_id
                document.department_id = hierarchy.get("department_id") or document.department_id
                document.programme_id = hierarchy.get("programme_id") or document.programme_id
                document.faculty = faculty or document.faculty
                document.department = department or document.department
                document.programme = programme or document.programme
                document.description = description or document.description
                if metadata:
                    document.document_metadata = {
                        **(document.document_metadata or {}),
                        **metadata,
                    }

            version_number = document.current_version_number + 1
            storage_path = self.save_upload(
                document_key=resolved_key,
                version_number=version_number,
                original_filename=original_filename,
                content=file_bytes,
                content_hash=content_hash,
            )

            source_record = ingestion_job_service.add_raw_record(
                db=db,
                job=job,
                record_type="curriculum_pdf" if source_format == "pdf" else f"curriculum_{source_format}",
                source_record_id=f"{resolved_key}:v{version_number}:pdf",
                storage_uri=str(storage_path),
                content_hash=content_hash,
                validation_status="valid",
                raw_payload={
                    "document_key": resolved_key,
                    "original_filename": original_filename,
                    "mime_type": mime_type,
                    "file_size": len(file_bytes),
                    "source_format": source_format,
                },
                normalised_payload={
                    "title": document_title,
                    "faculty": faculty,
                    "department": department,
                    "programme": programme,
                    "version_number": version_number,
                    "source_format": source_format,
                },
            )

            lineage_service.record_event(
                db=db,
                job_id=job.job_id,
                source_id=source.source_id,
                output_record_id=source_record.record_id,
                source_system="Curriculum Document Upload",
                processing_stage="upload_capture",
                transformation_description="Captured uploaded curriculum source file and stored original content.",
                actor_id=actor_id,
                metadata={
                    "document_key": resolved_key,
                    "filename": original_filename,
                    "content_hash": content_hash,
                },
            )

            pages = self.extract_pages(storage_path) if source_format == "pdf" else self.extract_structured_pages(
                file_bytes=file_bytes,
                filename=original_filename,
                source_format=source_format,
            )
            extracted_text = "\n\n".join(page["text"] for page in pages if page["text"])
            extracted_text_hash = sha256_text(extracted_text)
            declared_evidence_type = (metadata or {}).get("declared_evidence_type") or (metadata or {}).get("curriculum_evidence_type")
            structure = self.extract_curriculum_structure(pages, declared_evidence_type=declared_evidence_type)

            text_record = ingestion_job_service.add_raw_record(
                db=db,
                job=job,
                record_type="curriculum_extracted_text",
                source_record_id=f"{resolved_key}:v{version_number}:text",
                storage_uri=str(storage_path),
                content_hash=extracted_text_hash,
                validation_status="valid",
                raw_payload={
                    "document_key": resolved_key,
                    "version_number": version_number,
                    "page_count": len(pages),
                    "text": extracted_text,
                    "pages": pages,
                    "source_format": source_format,
                },
                normalised_payload={
                    "text_length": len(extracted_text),
                    "page_count": len(pages),
                },
            )

            version = CurriculumDocumentVersion(
                document_id=document.document_id,
                job_id=job.job_id,
                source_id=source.source_id,
                tenant_id=source.tenant_id,
                raw_record_id=source_record.record_id,
                version_number=version_number,
                original_filename=original_filename,
                storage_uri=str(storage_path),
                content_hash=content_hash,
                mime_type=mime_type,
                file_size=len(file_bytes),
                extracted_text_hash=extracted_text_hash,
                page_count=len(pages),
                chunk_count=0,
                extraction_status="completed",
                extraction_metadata={
                    "extractor": "pdfplumber" if source_format == "pdf" else f"{source_format}_text_extractor",
                    "source_format": source_format,
                    "source_type": (metadata or {}).get("source_type", "upload"),
                    "text_length": len(extracted_text),
                    "text_record_id": str(text_record.record_id),
                    "structure_summary": structure["summary"],
                    "detected_modules": structure["modules"],
                    "detected_outcomes": structure["outcomes"][:100],
                },
                uploaded_by=actor_id,
            )
            db.add(version)
            db.flush()

            lineage_service.record_event(
                db=db,
                job_id=job.job_id,
                source_id=source.source_id,
                input_record_id=source_record.record_id,
                output_record_id=text_record.record_id,
                source_system="Curriculum Document Upload",
                processing_stage="text_extraction",
                transformation_description="Extracted text from uploaded curriculum source.",
                actor_id=actor_id,
                metadata={
                    "document_id": str(document.document_id),
                    "version_id": str(version.version_id),
                    "page_count": len(pages),
                    "text_length": len(extracted_text),
                    "source_format": source_format,
                },
            )

            chunks = self.chunk_pages(pages)
            for chunk in chunks:
                chunk_metadata = self.classify_chunk(chunk, structure)
                module_id = self.ensure_detected_module(
                    db=db,
                    module_code=chunk_metadata.get("module_code"),
                    module_name=chunk_metadata.get("module_name"),
                    programme_id=hierarchy.get("programme_id"),
                    faculty=faculty,
                    programme=programme,
                    metadata=chunk_metadata,
                    description=description,
                )
                chunk_hash = sha256_text(chunk["content"])
                chunk_record = ingestion_job_service.add_raw_record(
                    db=db,
                    job=job,
                    record_type="curriculum_document_chunk",
                    source_record_id=(
                        f"{resolved_key}:v{version_number}:chunk:{chunk['chunk_index']}"
                    ),
                    storage_uri=str(storage_path),
                    content_hash=chunk_hash,
                    validation_status="valid",
                    raw_payload={
                        "document_key": resolved_key,
                        "version_id": str(version.version_id),
                        **chunk,
                    },
                    normalised_payload={
                        "chunk_index": chunk["chunk_index"],
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                        "token_count": chunk["token_count"],
                        "section": chunk_metadata.get("section"),
                        "outcome_type": chunk_metadata.get("outcome_type"),
                        "module_code": chunk_metadata.get("module_code"),
                    },
                )

                db_chunk = DocumentChunk(
                    version_id=version.version_id,
                    job_id=job.job_id,
                    raw_record_id=chunk_record.record_id,
                    module_id=module_id,
                    programme_id=hierarchy.get("programme_id"),
                    tenant_id=source.tenant_id,
                    chunk_index=chunk["chunk_index"],
                    page_start=chunk["page_start"],
                    page_end=chunk["page_end"],
                    char_start=chunk["char_start"],
                    char_end=chunk["char_end"],
                    content=chunk["content"],
                    content_hash=chunk_hash,
                    token_count=chunk["token_count"],
                    chunk_metadata={
                        "document_key": resolved_key,
                        "source_filename": original_filename,
                        "chunk_size": DEFAULT_CHUNK_SIZE,
                        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
                        **chunk_metadata,
                    },
                )
                db.add(db_chunk)
                db.flush()

                lineage_service.record_event(
                    db=db,
                    job_id=job.job_id,
                    source_id=source.source_id,
                    input_record_id=text_record.record_id,
                    output_record_id=chunk_record.record_id,
                    source_system="Curriculum PDF Upload",
                    processing_stage="text_chunking",
                    transformation_description="Segmented extracted curriculum text into reusable chunks.",
                    actor_id=actor_id,
                    metadata={
                        "document_id": str(document.document_id),
                        "version_id": str(version.version_id),
                        "chunk_id": str(db_chunk.chunk_id),
                        "chunk_index": chunk["chunk_index"],
                    },
                )

            version.chunk_count = len(chunks)
            subject_profile = curriculum_subject_profile_service.build_for_version(db, version.version_id)
            version.extraction_metadata = {
                **(version.extraction_metadata or {}),
                "subject_profile_id": str(subject_profile.profile_id) if subject_profile else None,
                "subject_code": subject_profile.subject_code if subject_profile else None,
                "structured_profile_ready": bool(subject_profile),
            }
            document.current_version_number = version_number

            ingestion_job_service.update_progress(
                db=db,
                job=job,
                current=1,
                seen_delta=1,
                loaded_delta=1,
            )
            ingestion_job_service.mark_completed(db, job, status="completed")

            log_audit_event(
                db=db,
                event_layer="application",
                event_type="curriculum_document",
                actor_type=actor_type,
                actor_id=actor_id,
                token_id=None,
                source_component="curriculum.ingestion",
                action="curriculum_pdf_uploaded",
                result="success",
                metadata={
                    "document_id": str(document.document_id),
                    "version_id": str(version.version_id),
                    "job_id": str(job.job_id),
                        "chunk_count": len(chunks),
                        "source_format": source_format,
                    },
                )
            db.commit()
            db.refresh(document)
            db.refresh(version)

            return {
                "document": document,
                "version": version,
                "job": job,
                "chunk_count": len(chunks),
            }

        except Exception as exc:
            db.rollback()
            failed_job = ingestion_job_service.get_job(db, job.job_id)
            if failed_job:
                ingestion_job_service.mark_failed(
                    db=db,
                    job=failed_job,
                    error=str(exc),
                    failure_stage="curriculum_pdf_ingestion",
                    failure_category=ingestion_job_service.classify_exception(exc),
                    diagnostic_payload={
                        "connector": "curriculum_pdf_upload",
                        "filename": original_filename,
                        "document_key": document_key,
                        "exception_type": exc.__class__.__name__,
                    },
                )
                db.commit()
            raise

    def save_upload(
        self,
        document_key: str,
        version_number: int,
        original_filename: str,
        content: bytes,
        content_hash: str,
    ) -> Path:
        target_dir = settings.curriculum_upload_path / document_key / f"v{version_number}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{content_hash[:12]}_{safe_filename(original_filename)}"
        target_path.write_bytes(content)
        return target_path

    @staticmethod
    def detect_source_format(filename: str, mime_type: Optional[str]) -> str:
        suffix = Path(filename or "").suffix.lower()
        mime = (mime_type or "").lower()
        if suffix == ".pdf" or "pdf" in mime:
            return "pdf"
        if suffix == ".docx" or "wordprocessingml" in mime:
            return "docx"
        if suffix == ".txt" or mime.startswith("text/plain"):
            return "txt"
        if suffix == ".csv" or "csv" in mime:
            return "csv"
        if suffix == ".xlsx" or "spreadsheet" in mime or "excel" in mime:
            return "xlsx"
        return suffix.lstrip(".") or "unknown"

    def extract_structured_pages(
        self,
        file_bytes: bytes,
        filename: str,
        source_format: str,
    ) -> List[Dict[str, Any]]:
        if source_format == "txt":
            text = file_bytes.decode("utf-8", errors="replace")
            return self.text_to_pages(text)

        if source_format == "csv":
            text = file_bytes.decode("utf-8", errors="replace")
            df = pd.read_csv(io.StringIO(text))
            extracted = self.dataframe_to_text(df, sheet_name=Path(filename).stem)
            return self.text_to_pages(extracted)

        if source_format == "xlsx":
            return self.text_to_pages(self.xlsx_to_text(file_bytes))

        if source_format == "docx":
            return self.text_to_pages(self.docx_to_text(file_bytes))

        text = file_bytes.decode("utf-8", errors="replace")
        return self.text_to_pages(text)

    @staticmethod
    def xlsx_to_text(file_bytes: bytes) -> str:
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as workbook:
            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in workbook.namelist():
                root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
                for item in root.findall(".//x:si", ns):
                    parts = [node.text or "" for node in item.findall(".//x:t", ns)]
                    shared_strings.append("".join(parts))

            sheet_names = sorted(
                name for name in workbook.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
            sections: List[str] = []
            for sheet_index, sheet_name in enumerate(sheet_names, start=1):
                sheet_xml = workbook.read(sheet_name).lstrip()
                root = ElementTree.fromstring(sheet_xml)
                lines = [f"Sheet: {sheet_index}"]
                for row in root.findall(".//x:sheetData/x:row", ns):
                    values: List[str] = []
                    for cell in row.findall("x:c", ns):
                        ref = cell.attrib.get("r", "")
                        value_node = cell.find("x:v", ns)
                        inline_node = cell.find(".//x:is/x:t", ns)
                        value = ""
                        if inline_node is not None and inline_node.text:
                            value = inline_node.text
                        elif value_node is not None and value_node.text:
                            value = value_node.text
                            if cell.attrib.get("t") == "s":
                                index = int(value)
                                value = shared_strings[index] if index < len(shared_strings) else value
                        if value:
                            values.append(f"{ref}: {value}")
                    if values:
                        lines.append("; ".join(values))
                sections.append("\n".join(lines))
            return "\n\n".join(sections)

    @staticmethod
    def docx_to_text(file_bytes: bytes) -> str:
        """Extract paragraph and table text from a DOCX without executing embedded content."""
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as document:
            if "word/document.xml" not in document.namelist():
                raise ValueError("DOCX does not contain word/document.xml")
            root = ElementTree.fromstring(document.read("word/document.xml"))
            lines: List[str] = []
            for paragraph in root.findall(".//w:p", namespace):
                parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
                value = "".join(parts).strip()
                if value:
                    lines.append(value)
            return "\n".join(lines)

    @staticmethod
    def dataframe_to_text(df: pd.DataFrame, sheet_name: str) -> str:
        df = df.dropna(how="all")
        lines = [f"Sheet: {sheet_name}"]
        for index, row in df.iterrows():
            values = []
            for column, value in row.items():
                if pd.isna(value):
                    continue
                values.append(f"{column}: {value}")
            if values:
                lines.append(f"Row {index + 1}: " + "; ".join(values))
        return "\n".join(lines)

    @staticmethod
    def text_to_pages(text: str, page_size: int = 4000) -> List[Dict[str, Any]]:
        cleaned = re.sub(r"[ \t]+", " ", text or "").strip()
        pages: List[Dict[str, Any]] = []
        if not cleaned:
            return [{"page_number": 1, "text": "", "char_start": 0, "char_end": 0}]

        start = 0
        page_number = 1
        while start < len(cleaned):
            end = min(start + page_size, len(cleaned))
            page_text = cleaned[start:end].strip()
            pages.append(
                {
                    "page_number": page_number,
                    "text": page_text,
                    "char_start": start,
                    "char_end": end,
                }
            )
            if end >= len(cleaned):
                break
            start = end
            page_number += 1
        return pages

    @staticmethod
    def extract_pages(pdf_path: Path) -> List[Dict[str, Any]]:
        pages: List[Dict[str, Any]] = []
        global_start = 0

        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                text = re.sub(r"[ \t]+", " ", text).strip()
                global_end = global_start + len(text)
                pages.append(
                    {
                        "page_number": index,
                        "text": text,
                        "char_start": global_start,
                        "char_end": global_end,
                    }
                )
                global_start = global_end + 2

        return pages

    @staticmethod
    def chunk_pages(
        pages: List[Dict[str, Any]],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []

        for page in pages:
            text = page["text"]
            if not text:
                continue

            start = 0
            while start < len(text):
                end = min(start + chunk_size, len(text))
                content = text[start:end].strip()

                if content:
                    chunks.append(
                        {
                            "chunk_index": len(chunks) + 1,
                            "page_start": page["page_number"],
                            "page_end": page["page_number"],
                            "char_start": page["char_start"] + start,
                            "char_end": page["char_start"] + end,
                            "content": content,
                            "token_count": len(content.split()),
                        }
                    )

                if end >= len(text):
                    break

                start = max(end - overlap, start + 1)

        return chunks

    def ensure_hierarchy(
        self,
        db: Session,
        faculty_name: Optional[str],
        department_name: Optional[str],
        programme_name: Optional[str],
    ) -> Dict[str, Optional[Any]]:
        faculty = self.get_or_create_faculty(db, faculty_name)
        department = self.get_or_create_department(db, department_name, faculty.faculty_id if faculty else None)
        programme = self.get_or_create_programme(db, programme_name, department.department_id if department else None)
        return {
            "faculty_id": faculty.faculty_id if faculty else None,
            "department_id": department.department_id if department else None,
            "programme_id": programme.programme_id if programme else None,
        }

    def get_or_create_faculty(self, db: Session, name: Optional[str]) -> Optional[AcademicFaculty]:
        if not name:
            return None
        key = slugify(name)
        faculty = db.query(AcademicFaculty).filter(AcademicFaculty.faculty_key == key).first()
        if faculty:
            return faculty
        faculty = AcademicFaculty(faculty_key=key, name=name)
        db.add(faculty)
        db.flush()
        return faculty

    def get_or_create_department(
        self,
        db: Session,
        name: Optional[str],
        faculty_id: Optional[Any],
    ) -> Optional[AcademicDepartment]:
        if not name:
            return None
        key = slugify(name)
        department = db.query(AcademicDepartment).filter(AcademicDepartment.department_key == key).first()
        if department:
            if faculty_id and not department.faculty_id:
                department.faculty_id = faculty_id
            return department
        department = AcademicDepartment(department_key=key, name=name, faculty_id=faculty_id)
        db.add(department)
        db.flush()
        return department

    def get_or_create_programme(
        self,
        db: Session,
        name: Optional[str],
        department_id: Optional[Any],
    ) -> Optional[AcademicProgramme]:
        if not name:
            return None
        key = slugify(name)
        programme = db.query(AcademicProgramme).filter(AcademicProgramme.programme_key == key).first()
        if programme:
            if department_id and not programme.department_id:
                programme.department_id = department_id
            return programme
        programme = AcademicProgramme(programme_key=key, name=name, department_id=department_id)
        db.add(programme)
        db.flush()
        return programme

    def ensure_detected_module(
        self,
        db: Session,
        module_code: Optional[str],
        module_name: Optional[str],
        programme_id: Optional[Any],
        faculty: Optional[str],
        programme: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> Optional[Any]:
        if not module_code:
            return None
        metadata = metadata or {}
        module = db.query(CurriculumModule).filter(CurriculumModule.module_code == module_code).first()
        if not module:
            module = CurriculumModule(
                module_code=module_code,
                module_name=module_name or module_code,
                programme_id=programme_id,
                faculty=faculty,
                programme=programme,
                data_source="curriculum_pdf_extraction",
            )
            db.add(module)
            db.flush()

        if programme_id and not module.programme_id:
            module.programme_id = programme_id
        if module_name and (not module.module_name or module.module_name == module.module_code):
            module.module_name = module_name[:255]
        if faculty and not module.faculty:
            module.faculty = faculty
        if programme and not module.programme:
            module.programme = programme
        if metadata.get("credits") and module.credits is None:
            module.credits = int(metadata["credits"])
        if metadata.get("nqf_level") and module.nqf_level is None:
            module.nqf_level = int(metadata["nqf_level"])

        descriptor_bits = []
        for key in ("outcomes", "assessment_criteria", "topics"):
            values = metadata.get(key) or []
            if values:
                descriptor_bits.extend(str(item.get("text") if isinstance(item, dict) else item) for item in values[:5])
        if description:
            descriptor_bits.insert(0, description)
        if descriptor_bits and not module.description:
            module.description = "\n".join(bit for bit in descriptor_bits if bit)[:5000]
        return module.module_id
    def extract_curriculum_structure(
        self,
        pages: List[Dict[str, Any]],
        declared_evidence_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        outcomes: List[Dict[str, Any]] = []
        modules: Dict[str, Dict[str, Any]] = {}
        sections: Dict[str, int] = {}
        assessments: List[Dict[str, Any]] = []
        assessment_criteria: List[Dict[str, Any]] = []
        topics: List[Dict[str, Any]] = []
        evidence_type_counts: Dict[str, int] = {}
        current_section = "body"
        current_module_code: Optional[str] = None
        current_module_name: Optional[str] = None
        # A study guide is evidence for one subject even when its cover lists
        # programme-specific aliases (for example PRJ470S/PRJ471S/PRJ472S).
        # Multi-module extraction remains available for prospectuses and maps.
        single_subject_document = declared_evidence_type in {
            "study_guide", "module_descriptor", "syllabus"
        }

        for page in pages:
            page_number = page["page_number"]
            page_text = page.get("text") or ""
            page_evidence_type = declared_evidence_type or self.classify_evidence_type(page_text)
            evidence_type_counts[page_evidence_type] = evidence_type_counts.get(page_evidence_type, 0) + 1
            lines = [line.strip() for line in page_text.splitlines() if line.strip()]
            for line in lines:
                detected_section = self.detect_section(line)
                if detected_section:
                    current_section = detected_section
                sections[current_section] = sections.get(current_section, 0) + 1

                module_code = self.extract_module_code(line)
                if (
                    single_subject_document
                    and current_module_code
                    and module_code
                    and module_code != current_module_code
                ):
                    module_code = None
                labelled_module_name = self.extract_labelled_module_name(line)
                module_metadata = self.extract_module_metadata(line)
                if module_code:
                    current_module_code = module_code
                    current_module_name = labelled_module_name or self.extract_module_name(line, current_module_code) or current_module_name
                    existing = modules.setdefault(
                        current_module_code,
                        {
                            "module_code": current_module_code,
                            "module_name": current_module_name,
                            "first_page": page_number,
                            "last_page": page_number,
                            "credits": None,
                            "nqf_level": None,
                            "topics": [],
                            "outcomes": [],
                            "assessment_criteria": [],
                            "assessment_methods": [],
                            "evidence_types": [],
                        },
                    )
                    existing["last_page"] = page_number
                    if current_module_name and not existing.get("module_name"):
                        existing["module_name"] = current_module_name
                    for key in ("credits", "nqf_level"):
                        if module_metadata.get(key) and not existing.get(key):
                            existing[key] = module_metadata[key]
                    if page_evidence_type not in existing["evidence_types"]:
                        existing["evidence_types"].append(page_evidence_type)
                elif labelled_module_name and current_module_code and current_module_code in modules:
                    current_module_name = labelled_module_name
                    modules[current_module_code]["module_name"] = labelled_module_name

                if current_module_code and current_module_code in modules:
                    for key in ("credits", "nqf_level"):
                        if module_metadata.get(key) and not modules[current_module_code].get(key):
                            modules[current_module_code][key] = module_metadata[key]
                    modules[current_module_code]["last_page"] = page_number
                    if page_evidence_type not in modules[current_module_code].setdefault("evidence_types", []):
                        modules[current_module_code]["evidence_types"].append(page_evidence_type)

                outcome_type = self.detect_outcome_type(line, current_section)
                if outcome_type and not self.is_section_heading(line):
                    record = {
                        "page": page_number,
                        "section": current_section,
                        "outcome_type": outcome_type,
                        "module_code": current_module_code,
                        "module_name": current_module_name,
                        "text": self.clean_evidence_line(line)[:1000],
                        "evidence_type": page_evidence_type,
                    }
                    if outcome_type == "assessment_criteria":
                        assessment_criteria.append(record)
                        if current_module_code in modules:
                            modules[current_module_code].setdefault("assessment_criteria", []).append(record)
                    else:
                        outcomes.append(record)
                        if current_module_code in modules:
                            modules[current_module_code].setdefault("outcomes", []).append(record)

                assessment = self.extract_assessment_method(line)
                if (current_section in {"module_topic", "syllabus"} or self.looks_like_topic(line)) and not self.is_section_heading(line) and not assessment:
                    topic = {
                        "page": page_number,
                        "module_code": current_module_code,
                        "module_name": current_module_name,
                        "text": self.clean_evidence_line(line)[:1000],
                        "evidence_type": page_evidence_type,
                    }
                    topics.append(topic)
                    if current_module_code in modules:
                        modules[current_module_code].setdefault("topics", []).append(topic["text"])

                if assessment:
                    assessment.update(
                        {
                            "page": page_number,
                            "module_code": current_module_code,
                            "module_name": current_module_name,
                            "text": self.clean_evidence_line(line)[:1000],
                            "evidence_type": page_evidence_type,
                        }
                    )
                    assessments.append(assessment)
                    if current_module_code in modules:
                        modules[current_module_code].setdefault("assessment_methods", []).append(
                            {"method": assessment.get("method"), "weight": assessment.get("weight")}
                        )

        document_evidence_type = declared_evidence_type or self.primary_evidence_type(evidence_type_counts)
        return {
            "summary": {
                "section_counts": sections,
                "document_evidence_type": document_evidence_type,
                "declared_evidence_type": declared_evidence_type,
                "evidence_type_counts": evidence_type_counts,
                "module_count": len(modules),
                "outcome_count": len(outcomes),
                "assessment_criteria_count": len(assessment_criteria),
                "assessment_count": len(assessments),
                "topic_count": len(topics),
                "outcome_type_counts": self.count_by(outcomes + assessment_criteria, "outcome_type"),
                "evidence_types_supported": sorted(CURRICULUM_EVIDENCE_TYPES.keys()),
            },
            "modules": list(modules.values()),
            "outcomes": outcomes,
            "assessment_criteria": assessment_criteria,
            "assessments": assessments,
            "topics": topics,
        }
    def classify_chunk(self, chunk: Dict[str, Any], structure: Dict[str, Any]) -> Dict[str, Any]:
        content = chunk["content"]
        section = self.detect_section(content) or "body"
        outcome_type = self.detect_outcome_type(content, section)
        module_code = self.extract_module_code(content)
        module_name = None
        if module_code:
            module_name = self.extract_labelled_module_name(content) or self.extract_module_name(content, module_code)

        page_start = chunk["page_start"]
        page_end = chunk["page_end"]
        page_outcomes = [
            item for item in structure.get("outcomes", [])
            if page_start <= item.get("page", 0) <= page_end
        ]
        page_assessment_criteria = [
            item for item in structure.get("assessment_criteria", [])
            if page_start <= item.get("page", 0) <= page_end
        ]
        page_topics = [
            item for item in structure.get("topics", [])
            if page_start <= item.get("page", 0) <= page_end
        ]
        page_assessments = [
            item for item in structure.get("assessments", [])
            if page_start <= item.get("page", 0) <= page_end
        ]
        page_module = self.module_for_page(structure, page_start, module_code)
        if not module_code and page_module:
            module_code = page_module.get("module_code")
            module_name = page_module.get("module_name")
        if module_code and not module_name and page_module:
            module_name = page_module.get("module_name")
        if not outcome_type and page_assessment_criteria:
            outcome_type = "assessment_criteria"
        if not outcome_type and page_outcomes:
            outcome_type = page_outcomes[0].get("outcome_type")

        module_metadata = self.extract_module_metadata(content)
        if page_module:
            module_metadata = {
                "credits": module_metadata.get("credits") or page_module.get("credits"),
                "nqf_level": module_metadata.get("nqf_level") or page_module.get("nqf_level"),
            }
        evidence_type = self.classify_evidence_type(content)
        if evidence_type == "unknown":
            evidence_type = (page_module or {}).get("evidence_types", [None])[0] or structure.get("summary", {}).get("document_evidence_type") or "unknown"

        return {
            "page": page_start,
            "section": section,
            "module_code": module_code,
            "module_name": module_name,
            "outcome_type": outcome_type,
            "curriculum_evidence_type": evidence_type,
            "document_evidence_type": structure.get("summary", {}).get("document_evidence_type"),
            "credits": module_metadata.get("credits"),
            "nqf_level": module_metadata.get("nqf_level"),
            "detected_outcome_count": len(page_outcomes),
            "detected_assessment_criteria_count": len(page_assessment_criteria),
            "detected_topic_count": len(page_topics),
            "detected_assessment_method_count": len(page_assessments),
            "outcomes": page_outcomes[:10],
            "assessment_criteria": page_assessment_criteria[:10],
            "topics": page_topics[:10],
            "assessment_methods": page_assessments[:10],
            "contains_assessment_criteria": bool(page_assessment_criteria or ASSESSMENT_CRITERIA_PATTERN.search(content)),
            "contains_learning_objective": bool(re.search(r"\blearning\s+objectives?\b", content, re.IGNORECASE)),
            "contains_competency": bool(re.search(r"\bcompetenc(?:y|ies)\b", content, re.IGNORECASE)),
            "contains_module_topics": bool(page_topics or re.search(r"\b(module\s+content|syllabus|topics?|units?)\b", content, re.IGNORECASE)),
            "contains_assessment_methods": bool(page_assessments or re.search(r"\b(assignment|test|exam|project|portfolio|practical|quiz|case\s+study)\b", content, re.IGNORECASE)),
        }
    @staticmethod
    def extract_module_code(text: str) -> Optional[str]:
        for pattern in MODULE_LABEL_PATTERNS:
            match = pattern.search(text or "")
            if match:
                return match.group(match.lastindex or 1).upper()
        # A study guide commonly labels outcomes as SO1, LO2, ELO3, etc.
        # Those tokens resemble short module codes but must never create
        # CurriculumModule rows. Prefer the first non-outcome code candidate.
        for match in MODULE_CODE_PATTERN.finditer(text or ""):
            candidate = match.group(1).upper()
            if not OUTCOME_CODE_PATTERN.fullmatch(candidate):
                return candidate
        return None

    @staticmethod
    def extract_labelled_module_name(text: str) -> Optional[str]:
        for pattern in MODULE_NAME_PATTERNS:
            match = pattern.search(text or "")
            if match:
                value = match.group(match.lastindex or 1)
                value = re.sub(r"\s+", " ", value).strip(" :-")
                return value[:255] if value else None
        return None

    @staticmethod
    def clean_evidence_line(text: str) -> str:
        match = OUTCOME_ITEM_PATTERN.match(text or "")
        value = match.group(1) if match else (text or "")
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def is_section_heading(text: str) -> bool:
        stripped = (text or "").strip()
        if len(stripped) > 120:
            return False
        return bool(any(pattern.search(stripped) for _, pattern in SECTION_PATTERNS))

    @staticmethod
    def primary_evidence_type(counts: Dict[str, int]) -> str:
        if not counts:
            return "unknown"
        priority = ["study_guide", "module_descriptor", "syllabus", "curriculum_map", "qualification_standard", "prospectus"]
        for item in priority:
            if counts.get(item):
                return item
        return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]

    @staticmethod
    def module_for_page(structure: Dict[str, Any], page_number: int, preferred_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        modules = structure.get("modules") or []
        if preferred_code:
            for module in modules:
                if module.get("module_code") == preferred_code:
                    return module
        containing = [
            module for module in modules
            if (module.get("first_page") or 0) <= page_number <= (module.get("last_page") or module.get("first_page") or 0)
        ]
        if containing:
            return containing[-1]
        previous = [module for module in modules if (module.get("first_page") or 0) <= page_number]
        return previous[-1] if previous else None
    @staticmethod
    def detect_section(text: str) -> Optional[str]:
        for section, pattern in SECTION_PATTERNS:
            if pattern.search(text):
                return section
        heading = text.strip()
        if len(heading) <= 80 and heading.upper() == heading and re.search(r"[A-Z]", heading):
            return slugify(heading).replace("-", "_")
        return None

    @staticmethod
    def detect_outcome_type(text: str, section: str) -> Optional[str]:
        lowered = text.lower()
        if section in {"module_outcome", "assessment_criteria", "competency", "learning_objective"}:
            return section
        if ASSESSMENT_CRITERIA_PATTERN.search(text or ""):
            return "assessment_criteria"
        if re.search(r"\b(exit\s+level\s+outcomes?|specific\s+outcomes?|critical\s+cross-field\s+outcomes?|learning\s+outcomes?)\b", lowered):
            return "module_outcome"
        if re.search(r"\b(students?|learners?)\s+(will|should|must)\b", lowered) or re.search(r"\b(able to|demonstrate|apply|analyse|evaluate|design|develop|explain|identify)\b", lowered):
            return "module_outcome"
        if "competenc" in lowered or "graduate attribute" in lowered:
            return "competency"
        if "objective" in lowered:
            return "learning_objective"
        if "topic" in lowered or "module content" in lowered:
            return "module_topic"
        return None

    @staticmethod
    def extract_module_metadata(text: str) -> Dict[str, Any]:
        credit_match = CREDIT_PATTERN.search(text or "")
        nqf_match = NQF_PATTERN.search(text or "")
        credit_value = None
        if credit_match:
            credit_value = credit_match.group(1) or credit_match.group(2)
        return {
            "credits": int(credit_value) if credit_value else None,
            "nqf_level": int(nqf_match.group(1)) if nqf_match else None,
        }

    @staticmethod
    def extract_assessment_method(text: str) -> Optional[Dict[str, Any]]:
        match = ASSESSMENT_WEIGHT_PATTERN.search(text)
        if match:
            method = match.group(1).lower().replace("examination", "exam")
            return {"method": method, "weight": int(match.group(2))}
        lowered = text.lower()
        for method in ("assignment", "test", "exam", "examination", "project", "portfolio", "practical", "presentation", "quiz", "case study", "laboratory"):
            if method in lowered and ("assessment" in lowered or len(text) < 160):
                return {"method": method, "weight": None}
        return None

    @staticmethod
    def looks_like_topic(text: str) -> bool:
        return bool(TOPIC_PATTERN.match(text or "") or re.match(r"^\s*(week|unit|topic|chapter|lesson|theme)\s+\d+", text or "", re.IGNORECASE))

    @staticmethod
    def classify_evidence_type(text: str) -> str:
        lowered = (text or "").lower()
        if "study guide" in lowered or "learner guide" in lowered or "module guide" in lowered:
            return "study_guide"
        if "qualification standard" in lowered or "exit level outcome" in lowered or "saqa" in lowered:
            return "qualification_standard"
        if "curriculum map" in lowered or "programme map" in lowered:
            return "curriculum_map"
        if "prospectus" in lowered or "admission requirements" in lowered:
            return "prospectus"
        if "syllabus" in lowered or "course content" in lowered or "module content" in lowered:
            return "syllabus"
        if "module descriptor" in lowered or "module code" in lowered or "subject code" in lowered or "nqf" in lowered or "credits" in lowered:
            return "module_descriptor"
        return "unknown"

    @staticmethod
    def extract_module_name(text: str, module_code: str) -> Optional[str]:
        lines = text.split(module_code, 1)[-1].splitlines()
        if not lines:
            return None
        after = lines[0]
        cleaned = re.sub(r"[:\-â€“]+", " ", after).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned[:255] if cleaned else None

    @staticmethod
    def count_by(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in items:
            value = item.get(key) or "unknown"
            counts[value] = counts.get(value, 0) + 1
        return counts


curriculum_pdf_ingestion_service = CurriculumPDFIngestionService()
