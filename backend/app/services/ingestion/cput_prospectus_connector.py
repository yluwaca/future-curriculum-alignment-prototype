"""
CPUT online prospectus connector.

The CPUT public faculty/course pages wrap a structured prospectus system:
https://prospectus.cput.ac.za/index.php/link-to-courses?f=220
https://prospectus.cput.ac.za/index.php/course-details?q=DPICTA&f=220

This connector treats those pages as curriculum-discovery evidence. It preserves
raw HTML for traceability and maps the visible programme/year/subject structure
into the existing academic hierarchy and curriculum_module table.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import requests
import urllib3
from sqlalchemy.orm import Session

from app.models.academic_department import AcademicDepartment
from app.models.academic_faculty import AcademicFaculty
from app.models.academic_programme import AcademicProgramme
from app.models.curriculum_document import CurriculumDocument
from app.models.curriculum_document_version import CurriculumDocumentVersion
from app.models.curriculum_module import CurriculumModule
from app.models.document_chunk import DocumentChunk
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.audit_service import log_audit_event
from app.services.ingestion.job_service import ingestion_job_service
from app.services.ingestion.lineage_service import lineage_service


CPUT_PROSPECTUS_SOURCE_KEY = "cput_online_prospectus"
CPUT_PROSPECTUS_BASE_URL = "https://prospectus.cput.ac.za/"
DEFAULT_FACULTY_CODE = "220"
DEFAULT_FACULTY_NAME = "Informatics and Design"


def clean_text(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def slugify(value: str, max_length: int = 150) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"&", " and ", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return (value or "unknown")[:max_length].strip("-") or "unknown"


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class CourseLink:
    department: str
    title: str
    course_code: str
    url: str


class AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: List[Tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "a":
            attr_map = dict(attrs)
            self._href = attr_map.get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.items.append((self._href, clean_text(" ".join(self._text))))
            self._href = None
            self._text = []


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tokens: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = clean_text(data)
        if text:
            self.tokens.append(text)


class CPUTProspectusConnector:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PCLMAS/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def ensure_source(self, db: Session):
        return ingestion_job_service.get_or_create_source(
            db=db,
            source_key=CPUT_PROSPECTUS_SOURCE_KEY,
            defaults={
                "name": "CPUT Online Prospectus",
                "source_type": "public_web",
                "source_category": "curriculum",
                "connector_type": "cput_online_prospectus",
                "connector_key": "cput_online_prospectus",
                "base_url": CPUT_PROSPECTUS_BASE_URL,
                "storage_path": None,
                "refresh_policy": "manual",
                "retry_policy": {
                    "max_attempts": 3,
                    "initial_backoff_seconds": 120,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 3600,
                    "open_circuit_after_failures": 5,
                    "circuit_open_seconds": 1800,
                },
                "owner": "system",
                "status": "active",
                "is_authorised": True,
                "config": {
                    "ingestion_group": "curriculum",
                    "institution": "CPUT",
                    "publisher": "Cape Peninsula University of Technology",
                    "source_page": CPUT_PROSPECTUS_BASE_URL,
                },
                "auth_config": {},
            },
        )

    def fetch_html(self, url: str) -> str:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = self.session.get(url, timeout=40, verify=False)
        response.raise_for_status()
        return response.text

    def discover_courses(self, faculty_code: str = DEFAULT_FACULTY_CODE) -> Tuple[str, List[CourseLink]]:
        url = urljoin(CPUT_PROSPECTUS_BASE_URL, f"index.php/link-to-courses?f={faculty_code}")
        html = self.fetch_html(url)
        parser = AnchorExtractor()
        parser.feed(html)

        current_department = "Unclassified"
        links: List[CourseLink] = []
        department_markers = self.extract_department_markers(html)

        for href, label in parser.items:
            if not label:
                continue
            if label.upper() in department_markers:
                current_department = label.title()
                continue
            if "course-details" not in href:
                continue
            query = parse_qs(urlparse(href).query)
            query_code = (query.get("q") or [""])[0].strip().upper()
            query_faculty = (query.get("f") or [""])[0].strip()
            if query_faculty and query_faculty != str(faculty_code):
                continue
            code_match = re.search(r"\[([A-Z0-9]+)\]", label)
            course_code = (code_match.group(1) if code_match else query_code).strip().upper()
            if not course_code:
                continue
            title = re.sub(r"\s*\[[^\]]+\].*$", "", label).strip()
            links.append(
                CourseLink(
                    department=current_department,
                    title=clean_text(title),
                    course_code=course_code,
                    url=urljoin(CPUT_PROSPECTUS_BASE_URL, href),
                )
            )
        return html, links

    @staticmethod
    def extract_department_markers(html: str) -> set[str]:
        text_parser = TextExtractor()
        text_parser.feed(html)
        markers = set()
        for token in text_parser.tokens:
            upper = token.upper()
            if "[" not in upper and len(upper) >= 4 and upper == token:
                markers.add(upper)
        return markers

    def parse_course_detail(self, html: str, fallback: CourseLink) -> Dict[str, Any]:
        text_parser = TextExtractor()
        text_parser.feed(html)
        tokens = [token for token in text_parser.tokens if token != "\uf077"]
        title = fallback.title
        department = fallback.department
        if tokens:
            department = tokens[0].title()

        course_aim = self.extract_between(tokens, "Course Aim:", "Opportunities:")
        opportunities = self.extract_between(tokens, "Opportunities:", "Undergraduates")
        offering_types = [token for token in tokens if token.startswith("Offering type:")]
        contacts = self.extract_contacts(tokens)
        modules = self.extract_modules(tokens)

        return {
            "institution": "CPUT",
            "faculty": DEFAULT_FACULTY_NAME,
            "department": department,
            "programme_title": title,
            "programme_code": fallback.course_code,
            "course_aim": course_aim,
            "opportunities": opportunities,
            "offering_types": offering_types,
            "contacts": contacts,
            "modules": modules,
            "source_url": fallback.url,
        }

    def preserve_curriculum_evidence(
        self,
        db: Session,
        *,
        actor_id: str,
        source,
        job,
        detail_record: RawIngestionRecord,
        detail_html: str,
        parsed: Dict[str, Any],
        programme: AcademicProgramme,
        faculty: AcademicFaculty,
        department: AcademicDepartment,
    ) -> CurriculumDocumentVersion:
        """Preserve an official prospectus page as reviewable curriculum evidence.

        Programme/module rows alone are useful operational data, but alignment
        labelling deliberately consumes versioned, reviewable evidence.  This
        adapter therefore preserves the same public prospectus page as a logical
        curriculum document and creates one traceable evidence chunk per module.
        Re-imports are content-addressed and do not duplicate versions.
        """
        programme_code = str(parsed["programme_code"]).strip().upper()
        document_key = f"cput-prospectus-{programme_code.lower()}"
        source_url = str(parsed.get("source_url") or "")
        content_hash = stable_hash(detail_html)

        document = db.query(CurriculumDocument).filter(
            CurriculumDocument.document_key == document_key
        ).first()
        if document is None:
            document = CurriculumDocument(
                document_key=document_key,
                tenant_id=getattr(source, "tenant_id", None),
                faculty_id=faculty.faculty_id,
                department_id=department.department_id,
                programme_id=programme.programme_id,
                title=f"{parsed['programme_title']} — CPUT Online Prospectus",
                faculty=str(parsed.get("faculty") or DEFAULT_FACULTY_NAME),
                department=str(parsed.get("department") or "Information Technology"),
                programme=str(parsed["programme_title"]),
                status="active",
                current_version_number=0,
                description="Official public CPUT online prospectus curriculum evidence.",
                document_metadata={
                    "source_key": CPUT_PROSPECTUS_SOURCE_KEY,
                    "source_url": source_url,
                    "programme_code": programme_code,
                    "evidence_type": "prospectus",
                },
                created_by=actor_id,
            )
            db.add(document)
            db.flush()

        existing = db.query(CurriculumDocumentVersion).filter(
            CurriculumDocumentVersion.document_id == document.document_id,
            CurriculumDocumentVersion.content_hash == content_hash,
        ).first()
        if existing is not None:
            return existing

        version_number = int(document.current_version_number or 0) + 1
        extracted_text = clean_text(detail_html)
        version = CurriculumDocumentVersion(
            document_id=document.document_id,
            job_id=job.job_id,
            source_id=source.source_id,
            tenant_id=getattr(source, "tenant_id", None),
            raw_record_id=detail_record.record_id,
            version_number=version_number,
            original_filename=f"CPUT-{programme_code}-online-prospectus.html",
            storage_uri=source_url,
            content_hash=content_hash,
            mime_type="text/html",
            file_size=len(detail_html.encode("utf-8")),
            extracted_text_hash=stable_hash(extracted_text),
            page_count=1,
            chunk_count=len(parsed.get("modules") or []),
            extraction_status="completed",
            extraction_metadata={
                "source_key": CPUT_PROSPECTUS_SOURCE_KEY,
                "source_url": source_url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "programme_code": programme_code,
                "evidence_type": "prospectus",
                "parser": "cput_prospectus_connector_v2",
            },
            uploaded_by=actor_id,
        )
        db.add(version)
        db.flush()

        course_aim = str(parsed.get("course_aim") or "").strip()
        opportunities = str(parsed.get("opportunities") or "").strip()
        for chunk_index, module in enumerate(parsed.get("modules") or []):
            module_code = str(module.get("module_code") or "").strip().upper()
            module_row = db.query(CurriculumModule).filter(
                CurriculumModule.module_code == module_code
            ).first()
            content = clean_text(
                " ".join(
                    value for value in [
                        f"Institution: CPUT. Programme: {parsed['programme_title']} ({programme_code}).",
                        f"Official curriculum module: {module.get('module_name')} ({module_code}), year {module.get('year')}.",
                        "Compulsory module." if module.get("is_compulsory") else "Curriculum module.",
                        f"Programme aim: {course_aim}." if course_aim else "",
                        f"Career and progression context: {opportunities}." if opportunities else "",
                        f"Source: {source_url}.",
                    ] if value
                )
            )
            db.add(DocumentChunk(
                version_id=version.version_id,
                module_id=module_row.module_id if module_row else None,
                programme_id=programme.programme_id,
                tenant_id=getattr(source, "tenant_id", None),
                job_id=job.job_id,
                raw_record_id=detail_record.record_id,
                chunk_index=chunk_index,
                page_start=1,
                page_end=1,
                char_start=0,
                char_end=len(content),
                content=content,
                content_hash=stable_hash(content),
                token_count=len(content.split()),
                chunk_metadata={
                    "evidence_type": "module_descriptor",
                    "module_code": module_code,
                    "module_name": module.get("module_name"),
                    "programme_code": programme_code,
                    "programme_name": parsed["programme_title"],
                    "academic_year": module.get("year"),
                    "is_compulsory": bool(module.get("is_compulsory")),
                    "contains_module_topics": True,
                    "source_key": CPUT_PROSPECTUS_SOURCE_KEY,
                    "source_url": source_url,
                },
            ))

        document.current_version_number = version_number
        document.programme_id = programme.programme_id
        document.department_id = department.department_id
        document.faculty_id = faculty.faculty_id
        db.add(document)
        db.flush()
        return version

    @staticmethod
    def extract_between(tokens: List[str], start: str, end: str) -> Optional[str]:
        try:
            start_index = tokens.index(start) + 1
        except ValueError:
            return None
        try:
            end_index = tokens.index(end, start_index)
        except ValueError:
            end_index = min(start_index + 8, len(tokens))
        return clean_text(" ".join(tokens[start_index:end_index])) or None

    @staticmethod
    def extract_contacts(tokens: List[str]) -> List[Dict[str, str]]:
        contacts: List[Dict[str, str]] = []
        for index, token in enumerate(tokens):
            if "@" not in token or index == 0:
                continue
            contact: Dict[str, str] = {"email": token}
            if index >= 1:
                contact["phone"] = tokens[index - 1]
            if index >= 2:
                contact["name"] = tokens[index - 2]
            contacts.append(contact)
        return contacts

    @staticmethod
    def extract_modules(tokens: List[str]) -> List[Dict[str, Any]]:
        modules: List[Dict[str, Any]] = []
        current_year: Optional[int] = None
        compulsory = False
        year_map = {"FIRST YEAR": 1, "SECOND YEAR": 2, "THIRD YEAR": 3, "FOURTH YEAR": 4}

        for index, token in enumerate(tokens):
            if token in year_map:
                current_year = year_map[token]
                compulsory = False
                continue
            if "Compulsary subject" in token or "Compulsory subject" in token:
                compulsory = True
                continue
            match = re.match(r"^(.+?)\s+\(([A-Z0-9]+)\)$", token)
            if not match or current_year is None:
                continue
            fee = None
            if index + 1 < len(tokens) and re.match(r"^R\s*[\d,]+(\.\d{2})?$", tokens[index + 1]):
                fee = tokens[index + 1]
            modules.append(
                {
                    "year": current_year,
                    "module_name": clean_text(match.group(1)).title(),
                    "module_code": match.group(2),
                    "is_compulsory": compulsory,
                    "fee": fee,
                }
            )
        return modules

    def import_faculty(
        self,
        db: Session,
        actor_id: str,
        faculty_code: str = DEFAULT_FACULTY_CODE,
        max_courses: Optional[int] = None,
        course_codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        requested_codes = {code.strip().upper() for code in (course_codes or []) if code.strip()}
        source = self.ensure_source(db)
        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type="cput_prospectus_import",
            triggered_by=actor_id,
            parameters={
                "faculty_code": faculty_code,
                "max_courses": max_courses,
                "course_codes": sorted(requested_codes),
            },
        )
        db.commit()

        try:
            ingestion_job_service.mark_running(db, job)
            index_html, discovered_links = self.discover_courses(faculty_code)
            available_codes = sorted({link.course_code.upper() for link in discovered_links})
            links = discovered_links
            if requested_codes:
                links = [link for link in discovered_links if link.course_code.upper() in requested_codes]
                missing_codes = sorted(requested_codes - {link.course_code.upper() for link in links})
                if missing_codes:
                    raise ValueError(
                        "Requested CPUT course code(s) not found for faculty "
                        f"{faculty_code}: {', '.join(missing_codes)}. "
                        f"Available codes: {', '.join(available_codes[:30]) or 'none'}"
                    )
            if max_courses:
                links = links[:max_courses]
            if not links:
                raise ValueError(
                    f"No CPUT prospectus courses found for faculty {faculty_code}. "
                    f"Available codes: {', '.join(available_codes[:30]) or 'none'}"
                )
            job.progress_total = len(links)
            db.add(job)
            db.flush()

            index_record = self.record_raw(
                db=db,
                job=job,
                source=source,
                source_record_id=f"cput-faculty-{faculty_code}-course-index",
                record_type="cput_prospectus_course_index",
                raw_payload={
                    "faculty_code": faculty_code,
                    "source_url": f"{CPUT_PROSPECTUS_BASE_URL}index.php/link-to-courses?f={faculty_code}",
                    "course_count": len(links),
                    "html": index_html,
                },
                normalised_payload={
                    "faculty": DEFAULT_FACULTY_NAME,
                    "course_links": [link.__dict__ for link in links],
                },
            )

            faculty = self.get_or_create_faculty(db, DEFAULT_FACULTY_NAME, faculty_code)
            imported_programmes = 0
            imported_modules = 0
            failed_courses = 0

            for position, link in enumerate(links, start=1):
                try:
                    detail_html = self.fetch_html(link.url)
                    parsed = self.parse_course_detail(detail_html, link)
                    detail_record = self.record_raw(
                        db=db,
                        job=job,
                        source=source,
                        source_record_id=f"cput-course-{link.course_code}",
                        record_type="cput_prospectus_course_detail",
                        raw_payload={"source_url": link.url, "html": detail_html},
                        normalised_payload=parsed,
                    )
                    department = self.get_or_create_department(db, faculty, parsed["department"])
                    programme = self.get_or_create_programme(db, department, parsed)
                    imported_programmes += 1
                    for module in parsed["modules"]:
                        self.upsert_module(db, programme, parsed, module)
                        self.record_raw(
                            db=db,
                            job=job,
                            source=source,
                            source_record_id=f"cput-module-{link.course_code}-{module['module_code']}",
                            record_type="cput_prospectus_module",
                            raw_payload={"course_record_id": str(detail_record.record_id), **module},
                            normalised_payload={
                                "programme_id": str(programme.programme_id),
                                "programme_code": parsed["programme_code"],
                                "programme_title": parsed["programme_title"],
                                "faculty": parsed["faculty"],
                                "department": parsed["department"],
                                **module,
                            },
                        )
                        imported_modules += 1
                    self.preserve_curriculum_evidence(
                        db,
                        actor_id=actor_id,
                        source=source,
                        job=job,
                        detail_record=detail_record,
                        detail_html=detail_html,
                        parsed=parsed,
                        programme=programme,
                        faculty=faculty,
                        department=department,
                    )
                    lineage_service.record_event(
                        db=db,
                        source_system="cput_online_prospectus",
                        processing_stage="curriculum_discovery",
                        transformation_description="CPUT prospectus course page mapped to academic programme",
                        job_id=job.job_id,
                        source_id=source.source_id,
                        input_record_id=detail_record.record_id,
                        actor_id=actor_id,
                        metadata={
                            "course_code": link.course_code,
                            "programme_id": str(programme.programme_id),
                            "index_record_id": str(index_record.record_id),
                        },
                    )
                    ingestion_job_service.update_progress(db, job, current=position, loaded_delta=1, seen_delta=1)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    job = ingestion_job_service.get_job(db, job.job_id)
                    source = self.ensure_source(db)
                    failed_courses += 1
                    ingestion_job_service.update_progress(db, job, current=position, failed_delta=1, seen_delta=1)
                    job.failure_details = {
                        **(job.failure_details or {}),
                        f"course_{link.course_code}": str(exc)[:500],
                    }
                    db.add(job)
                    db.commit()

            ingestion_job_service.mark_completed(db, job, status="completed" if failed_courses == 0 else "completed_with_errors")
            log_audit_event(
                db=db,
                event_layer="application",
                event_type="curriculum_ingestion",
                actor_type="human",
                actor_id=actor_id,
                token_id=None,
                source_component="cput_prospectus_connector",
                action="curriculum.cput_prospectus.imported",
                result="success",
                metadata={
                    "job_id": str(job.job_id),
                    "faculty_code": faculty_code,
                    "programmes": imported_programmes,
                    "modules": imported_modules,
                    "failed_courses": failed_courses,
                },
            )
            db.commit()
            return {
                "message": "CPUT prospectus import completed",
                "job": job,
                "faculty_code": faculty_code,
                "courses_discovered": len(links),
                "programmes_imported": imported_programmes,
                "modules_imported": imported_modules,
                "failed_courses": failed_courses,
            }
        except Exception as exc:
            ingestion_job_service.mark_failed(
                db=db,
                job=job,
                error=str(exc),
                failure_stage="cput_prospectus_import",
                failure_category=ingestion_job_service.classify_exception(exc),
                retryable=not isinstance(exc, ValueError),
                diagnostic_payload={"available_action": "Use Discover CPUT Courses, then import one of the listed course codes."} if isinstance(exc, ValueError) else None,
            )
            db.commit()
            raise

    def record_raw(
        self,
        db: Session,
        job,
        source,
        source_record_id: str,
        record_type: str,
        raw_payload: Dict[str, Any],
        normalised_payload: Dict[str, Any],
    ) -> RawIngestionRecord:
        payload_for_hash = f"{source_record_id}:{record_type}:{raw_payload.get('html') or raw_payload}"
        record = RawIngestionRecord(
            job_id=job.job_id,
            source_id=source.source_id,
            tenant_id=source.tenant_id,
            source_record_id=source_record_id,
            record_type=record_type,
            content_hash=stable_hash(payload_for_hash),
            validation_status="valid",
            raw_payload=raw_payload,
            normalised_payload=normalised_payload,
        )
        db.add(record)
        db.flush()
        return record

    @staticmethod
    def get_or_create_faculty(db: Session, name: str, faculty_code: str) -> AcademicFaculty:
        key = f"cput-{slugify(name)}-{faculty_code}"
        faculty = db.query(AcademicFaculty).filter(AcademicFaculty.faculty_key == key).first()
        if faculty:
            return faculty
        faculty = AcademicFaculty(
            faculty_key=key,
            name=name,
            description="Imported from the CPUT public online prospectus.",
            status="active",
            faculty_metadata={"institution": "CPUT", "source": "cput_online_prospectus", "faculty_code": faculty_code},
        )
        db.add(faculty)
        db.flush()
        return faculty

    @staticmethod
    def get_or_create_department(db: Session, faculty: AcademicFaculty, name: str) -> AcademicDepartment:
        key = f"cput-{slugify(faculty.name)}-{slugify(name)}"
        department = db.query(AcademicDepartment).filter(AcademicDepartment.department_key == key).first()
        if department:
            return department
        department = AcademicDepartment(
            faculty_id=faculty.faculty_id,
            department_key=key,
            name=name,
            description="Imported from the CPUT public online prospectus.",
            status="active",
            department_metadata={"institution": "CPUT", "source": "cput_online_prospectus"},
        )
        db.add(department)
        db.flush()
        return department

    @staticmethod
    def get_or_create_programme(db: Session, department: AcademicDepartment, parsed: Dict[str, Any]) -> AcademicProgramme:
        programme_code = parsed["programme_code"]
        key = f"cput-{programme_code.lower()}"
        programme = db.query(AcademicProgramme).filter(AcademicProgramme.programme_key == key).first()
        metadata = {
            "institution": "CPUT",
            "source": "cput_online_prospectus",
            "source_url": parsed["source_url"],
            "programme_code": programme_code,
            "course_aim": parsed.get("course_aim"),
            "opportunities": parsed.get("opportunities"),
            "offering_types": parsed.get("offering_types", []),
            "contacts": parsed.get("contacts", []),
            "last_imported_at": datetime.now(timezone.utc).isoformat(),
        }
        if programme:
            programme.department_id = department.department_id
            programme.name = parsed["programme_title"]
            programme.qualification_type = CPUTProspectusConnector.qualification_type(parsed["programme_title"])
            programme.description = parsed.get("course_aim")
            programme.programme_metadata = {**(programme.programme_metadata or {}), **metadata}
            db.add(programme)
            db.flush()
            return programme
        programme = AcademicProgramme(
            department_id=department.department_id,
            programme_key=key,
            name=parsed["programme_title"],
            qualification_type=CPUTProspectusConnector.qualification_type(parsed["programme_title"]),
            nqf_level=None,
            description=parsed.get("course_aim"),
            status="active",
            programme_metadata=metadata,
        )
        db.add(programme)
        db.flush()
        return programme

    @staticmethod
    def qualification_type(title: str) -> Optional[str]:
        upper = title.upper()
        if "HIGHER CERT" in upper or upper.startswith("HC:"):
            return "Higher Certificate"
        if "ADV" in upper and "DIP" in upper:
            return "Advanced Diploma"
        if "DIP" in upper or upper.startswith("DIP:"):
            return "Diploma"
        if "MASTER" in upper:
            return "Master"
        if "DOCTOR" in upper or "PHD" in upper:
            return "Doctoral"
        return None

    @staticmethod
    def upsert_module(
        db: Session,
        programme: AcademicProgramme,
        parsed: Dict[str, Any],
        module: Dict[str, Any],
    ) -> CurriculumModule:
        existing = db.query(CurriculumModule).filter(CurriculumModule.module_code == module["module_code"]).first()
        description = (
            f"Imported from CPUT online prospectus. Year {module['year']}. "
            f"{'Compulsory' if module.get('is_compulsory') else 'Subject'} for {parsed['programme_title']}."
        )
        if existing:
            existing.module_name = module["module_name"]
            existing.programme_id = programme.programme_id
            existing.programme = parsed["programme_title"]
            existing.faculty = parsed["faculty"]
            existing.description = description
            existing.data_source = "cput_online_prospectus"
            existing.last_processed_at = datetime.now(timezone.utc)
            existing.is_active = True
            db.add(existing)
            db.flush()
            return existing
        item = CurriculumModule(
            module_code=module["module_code"],
            module_name=module["module_name"],
            programme_id=programme.programme_id,
            description=description,
            nqf_level=None,
            faculty=parsed["faculty"],
            programme=parsed["programme_title"],
            credits=None,
            is_active=True,
            data_source="cput_online_prospectus",
            last_processed_at=datetime.now(timezone.utc),
        )
        db.add(item)
        db.flush()
        return item


cput_prospectus_connector = CPUTProspectusConnector()

