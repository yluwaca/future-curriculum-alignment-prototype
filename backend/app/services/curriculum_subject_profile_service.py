"""Build structured subject profiles from uploaded curriculum chunks."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

from sqlalchemy.orm import Session

from app.models.curriculum_document import CurriculumDocument
from app.models.curriculum_document_version import CurriculumDocumentVersion
from app.models.curriculum_module import CurriculumModule
from app.models.curriculum_subject_profile import CurriculumSubjectProfile
from app.models.document_chunk import DocumentChunk


class CurriculumSubjectProfileService:
    """Convert document chunks into a stable subject/module curriculum object."""

    SUBJECT_CODE_RE = re.compile(r"\b[A-Z]{2,5}\d{3}[A-Z]?\b")
    YEAR_RE = re.compile(r"\b(20\d{2})\b")
    NQF_RE = re.compile(r"\bNQF\s*(?:LEVEL)?\s*[:\-]?\s*(\d{1,2})\b", re.I)
    CREDIT_RE = re.compile(r"\b(?:CREDITS?|CREDIT\s+VALUE)\s*[:\-]?\s*(\d{1,3})\b|\b(\d{1,3})\s+CREDITS?\b", re.I)
    FACULTY_RE = re.compile(r"\b(FACULTY\s+OF\s+[A-Z][A-Z &/\-]{3,100}?)(?=\s+(?:DEPARTMENT|PROGRAMME|QUALIFICATION|SUBJECT|COURSE|CONTACT|$))", re.I)
    PROGRAMME_LABEL_RE = re.compile(r"\b(?:PROGRAMME|QUALIFICATION)\s*(?:NAME|TITLE)?\s*[:\-]\s*([A-Z][A-Z0-9 &/(),.\-]{4,180}?)(?=\s+(?:PROGRAMME\s+CODE|QUALIFICATION\s+CODE|NQF|SUBJECT|MODULE|COURSE|$))", re.I)
    QUALIFICATION_RE = re.compile(r"\b((?:POSTGRADUATE|ADVANCED|NATIONAL)?\s*DIPLOMA\s+IN\s+[A-Z][A-Z &/()\-]{4,160}?)(?=\s+(?:PROGRAMME\s+CODE|QUALIFICATION\s+CODE|NQF|SUBJECT|MODULE|COURSE|$))", re.I)
    HEADING_STOP_RE = re.compile(r"\b(PRE[- ]?AND|PRE[- ]?REQUISITE|SUBJECT\s+GOALS|TOPIC\s+SEQUENCING|ASSESSMENT|STUDY\s+UNITS?|ARTICULATION|LEARNING\s+PRESUMED)\b", re.I)
    SKILL_PATTERNS: list[tuple[str, str, list[str]]] = [
        ("Database design", "database", ["database design", "data modelling", "data modeling", "erd", "entity relationship"]),
        ("ER modelling", "database", ["entity relationship", "erd", "er diagram"]),
        ("Normalisation", "database", ["normalisation", "normalization"]),
        ("SQL", "database", ["sql", "structured query language"]),
        ("Advanced SQL", "database", ["advanced sql", "stored procedure", "trigger", "view"]),
        ("Transaction management", "database", ["transaction management", "transaction processing", "concurrency"]),
        ("Query optimisation", "database", ["query optimisation", "query optimization", "performance tuning"]),
        ("Distributed databases", "database", ["distributed database", "distributed dbms"]),
        ("Data warehousing", "analytics", ["data warehouse", "data warehousing"]),
        ("Business intelligence", "analytics", ["business intelligence", "decision support", "dss"]),
        ("OLAP", "analytics", ["olap", "multidimensional", "data cube", "star schema"]),
        ("Big Data", "analytics", ["big data"]),
        ("NoSQL", "database", ["nosql"]),
        ("Database administration", "database", ["database administration", "db administration"]),
        ("Database security", "security", ["database security", "security"]),
        ("Software development", "software", ["software development", "application development", "programming"]),
        ("Project management", "professional", ["project management", "project"]),
        ("Technical writing", "professional", ["technical writing", "report writing"]),
        ("Teamwork", "professional", ["teamwork", "group work", "work effectively with others"]),
        ("Research and evaluation", "professional", ["research", "evaluate", "evaluation"]),
    ]

    def build_for_version(self, db: Session, version_id: Any) -> CurriculumSubjectProfile | None:
        version = db.query(CurriculumDocumentVersion).filter(CurriculumDocumentVersion.version_id == version_id).first()
        if not version:
            return None
        document = db.query(CurriculumDocument).filter(CurriculumDocument.document_id == version.document_id).first()
        chunks = db.query(DocumentChunk).filter(DocumentChunk.version_id == version.version_id).order_by(DocumentChunk.chunk_index.asc()).all()
        if not chunks:
            return None
        text = "\n".join(chunk.content or "" for chunk in chunks)
        compact = self._normalise_text(" ".join(text.split()))
        subject_code = self._subject_code(document, version, chunks, compact)
        subject_name = self._subject_name(subject_code, document, version, compact)
        year = self._year(version.original_filename, document.title if document else "", compact)
        nqf = self._first_int(self.NQF_RE, compact)
        credits = self._first_int(self.CREDIT_RE, compact)
        purpose = self._section(compact, ["Purpose of the Subject", "Purpose"], max_chars=1400)
        prerequisites = self._prerequisites(compact)
        articulation = self._section(compact, ["Articulation with other subjects", "Articulation"], max_chars=1000)
        outcomes = self._outcomes(compact, chunks)
        assessments = self._assessments(compact, chunks)
        topics = self._topics(compact)
        skills = self._skills(compact, chunks)
        module = self._upsert_module(db, document, subject_code, subject_name, nqf, credits, purpose)
        existing = db.query(CurriculumSubjectProfile).filter(CurriculumSubjectProfile.version_id == version.version_id, CurriculumSubjectProfile.subject_code == subject_code).first()
        profile = existing or CurriculumSubjectProfile(document_id=version.document_id, version_id=version.version_id, tenant_id=version.tenant_id, programme_id=document.programme_id if document else None, subject_code=subject_code)
        profile.module_id = module.module_id if module else None
        profile.institution = self._institution(compact) or "Cape Peninsula University of Technology"
        profile.faculty = (document.faculty if document else None) or self._faculty(compact)
        profile.department = document.department if document else None
        profile.programme_name = (document.programme if document else None) or self._programme_name(compact)
        profile.programme_code = self._programme_code(compact)
        profile.qualification_type = self._qualification_type(document.programme if document else None, compact)
        profile.subject_name = subject_name
        profile.subject_year = year
        profile.nqf_level = nqf
        profile.credits = credits
        profile.purpose = purpose
        profile.prerequisites = prerequisites
        profile.articulation = articulation
        profile.learning_outcomes = outcomes
        profile.assessment_evidence = assessments
        profile.topic_evidence = topics
        profile.extracted_skills = skills
        profile.source_version_ids = [str(version.version_id)]
        profile.source_chunk_ids = [str(chunk.chunk_id) for chunk in chunks]
        profile.extraction_metadata = {"extractor": "rules_v1_subject_profile", "source_filename": version.original_filename, "source_document_title": document.title if document else None, "chunk_count": len(chunks), "note": "Raw chunks are preserved for audit; this profile is the consolidated subject/module evidence object."}
        if document:
            # Keep the document list/reporting projection aligned with the
            # extracted profile when upload metadata was absent.  Human edits
            # made later through Subject Profile Validation supersede this.
            document.faculty = document.faculty or profile.faculty
            document.department = document.department or profile.department
            document.programme = document.programme or profile.programme_name
            db.add(document)
        if not existing:
            db.add(profile)
        db.flush()
        return profile

    def _faculty(self, text: str) -> str | None:
        match = self.FACULTY_RE.search(text)
        return self._clean(match.group(1), 180).title() if match else None

    def _programme_name(self, text: str) -> str | None:
        for pattern in (self.PROGRAMME_LABEL_RE, self.QUALIFICATION_RE):
            match = pattern.search(text)
            if match:
                return self._clean(match.group(1), 255).title()
        return None

    def _subject_code(self, document, version, chunks, compact: str) -> str:
        """Resolve the canonical subject code from document identity first."""
        priority_values = [
            version.original_filename,
            getattr(document, "document_key", None),
            getattr(document, "title", None),
        ]
        for value in priority_values:
            if not value:
                continue
            matches = [m for m in self.SUBJECT_CODE_RE.findall(str(value).upper()) if not m.startswith("CCFO")]
            if matches:
                return matches[0]

        counts: OrderedDict[str, int] = OrderedDict()
        for chunk in chunks[:12]:
            meta = chunk.chunk_metadata or {}
            for value in [meta.get("module_code"), meta.get("subject_code"), chunk.content[:900] if chunk.content else None]:
                if not value:
                    continue
                for match in self.SUBJECT_CODE_RE.findall(str(value).upper()):
                    if not match.startswith("CCFO"):
                        counts[match] = counts.get(match, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0] if counts else "UNKNOWN"

    def _subject_name(self, code: str, document, version, compact: str) -> str:
        title = (getattr(document, "title", None) or version.original_filename or code).strip()
        cleaned = re.sub(r"subject\s+(guide|outcomes?)", "", title, flags=re.I)
        cleaned = re.sub(r"20\d{2}", "", cleaned)
        cleaned = re.sub(r"\.(pdf|docx?|txt|csv|xlsx)$", "", cleaned, flags=re.I)
        cleaned = " ".join(cleaned.replace("_", " ").replace("-", " ").split())
        if code != "UNKNOWN":
            title_candidate = re.sub(rf"{re.escape(code)}", "", cleaned, flags=re.I)
            title_candidate = " ".join(title_candidate.split()).strip(" :-")
            if title_candidate and title_candidate.lower() not in {"course code", "subject code", "module code"}:
                return title_candidate
            around = re.search(rf"([A-Z][A-Z\s&/:-]{{5,120}})\s+{re.escape(code)}", compact.upper())
            if around:
                candidate = " ".join(around.group(1).split())[-90:].strip(" :-")
                if len(candidate) > 5 and not candidate.startswith("CAPE PENINSULA") and candidate.lower() not in {"course code", "subject code", "module code"}:
                    return candidate.title()
        return cleaned or code

    def _year(self, *values: str) -> int | None:
        for value in values:
            if value:
                match = self.YEAR_RE.search(str(value))
                if match:
                    return int(match.group(1))
        return None

    def _first_int(self, pattern: re.Pattern, text: str) -> int | None:
        match = pattern.search(text)
        if not match:
            return None
        for group in match.groups():
            if group:
                return int(group)
        return None

    def _section(self, text: str, starts: list[str], max_chars: int = 1200) -> str | None:
        lower = text.lower()
        candidates: list[str] = []
        for start in starts:
            search_at = 0
            while True:
                idx = lower.find(start.lower(), search_at)
                if idx < 0:
                    break
                fragment = text[idx + len(start):idx + len(start) + max_chars * 2]
                search_at = idx + len(start)
                if self._looks_like_toc_fragment(fragment):
                    continue
                stop = self.HEADING_STOP_RE.search(fragment[80:])
                if stop:
                    fragment = fragment[:80 + stop.start()]
                cleaned = self._clean(fragment, max_chars)
                if cleaned:
                    candidates.append(cleaned)
        if not candidates:
            return None
        # Prefer the richest non-TOC fragment.
        candidates.sort(key=lambda value: (self._content_score(value), len(value)), reverse=True)
        return candidates[0]

    def _looks_like_toc_fragment(self, fragment: str) -> bool:
        sample = fragment[:500]
        if sample.count('.') > 35:
            return True
        if len(re.findall(r"\d+(?:\.\d+)*", sample)) > 18 and len(re.findall(r"[A-Za-z]{5,}", sample)) < 25:
            return True
        toc_terms = ["table of contents", "page", "error! bookmark", "subject structure", "subject breakdown schedule"]
        if sum(term in sample.lower() for term in toc_terms) >= 3:
            return True
        return False

    def _content_score(self, value: str) -> int:
        lower = value.lower()
        score = len(re.findall(r"[A-Za-z]{4,}", value))
        score += 30 if any(term in lower for term in ["students", "student", "able to", "knowledge", "skills", "assessment", "database", "research", "artificial intelligence"]) else 0
        score -= 40 if self._looks_like_toc_fragment(value) else 0
        return score

    def _prerequisites(self, text: str) -> list[dict[str, Any]]:
        section = self._section(text, ["Pre- and co-requisite knowledge", "Prerequisites", "Learning presumed to be in place"], max_chars=1400)
        if not section:
            return []
        codes = sorted(set(self.SUBJECT_CODE_RE.findall(section.upper())))
        return [{"text": section, "codes": codes, "source": "document_section"}]

    def _outcomes(self, text: str, chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
        outcomes: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for match in re.finditer(r"\b(SO\d+)\s*[:\-) ]+(.{20,260}?)(?=\bSO\d+\b|\bTHEME\b|\bSTUDY\s+UNIT\b|$)", text, flags=re.I):
            code = match.group(1).upper()
            value = self._clean(match.group(2), 260)
            if value:
                outcomes.setdefault(code, {"outcome_code": code, "outcome_text": value, "evidence_type": "subject_outcome"})
        for chunk in chunks:
            meta = chunk.chunk_metadata or {}
            if str(meta.get("section") or "") in {"module_outcome", "learning_objective"} and len(outcomes) < 20:
                cleaned = self._clean(chunk.content or "", 500)
                if cleaned:
                    outcomes.setdefault(f"chunk-{chunk.chunk_index}", {"outcome_code": meta.get("module_code") or None, "outcome_text": cleaned, "page_start": chunk.page_start, "evidence_type": meta.get("section")})
        return list(outcomes.values())[:30]

    def _assessments(self, text: str, chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
        evidence: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for match in re.finditer(r"\b(Test|Assignment|Practical|Project|Exam|Examination|Presentation|Quiz|Portfolio)\s*(\d+)?\b.{0,80}?(\d{1,3})\s*%", text, flags=re.I):
            label = " ".join(part for part in [match.group(1).title(), match.group(2) or ""] if part).strip()
            evidence[label.lower()] = {"assessment_type": label, "weight": int(match.group(3)), "evidence_type": "assessment_weight"}
        for chunk in chunks:
            meta = chunk.chunk_metadata or {}
            section = str(meta.get("section") or "")
            methods = meta.get("assessment_methods") or []
            criteria = meta.get("assessment_criteria") or []
            has_assessment_metadata = bool(methods or criteria or meta.get("contains_assessment_methods") or meta.get("contains_assessment_criteria"))
            if section in {"assessment_method", "assessment_criteria"} or has_assessment_metadata:
                cleaned = self._clean(chunk.content or "", 900)
                if not cleaned:
                    continue
                method_names = sorted({str(item.get("method") or "").strip().title() for item in methods if isinstance(item, dict) and item.get("method")})
                criteria_count = len(criteria) if isinstance(criteria, list) else 0
                assessment_type = ", ".join(method_names[:4]) if method_names else "Assessment evidence"
                key = f"chunk-{chunk.chunk_index}-{assessment_type.lower()}"
                evidence.setdefault(key, {
                    "assessment_type": assessment_type,
                    "assessment_text": cleaned,
                    "page_start": chunk.page_start,
                    "evidence_type": "assessment_section" if section == "assessment_method" else "assessment_criteria_section",
                    "methods_detected": method_names,
                    "criteria_count": criteria_count,
                })
        return list(evidence.values())[:30]

    def _topics(self, text: str) -> list[dict[str, Any]]:
        topics: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for match in re.finditer(r"\b(Topic|Study Unit|Theme)\s*(\d+)?\s*[:\-]?\s+(.{8,120})", text, flags=re.I):
            key = f"{match.group(1).lower()}-{match.group(2) or len(topics)+1}"
            topics.setdefault(key, {"topic_label": f"{match.group(1).title()} {match.group(2) or ''}".strip(), "topic_text": self._clean(match.group(3), 160)})
        for skill, _category, aliases in self.SKILL_PATTERNS:
            if any(alias in text.lower() for alias in aliases):
                topics.setdefault(skill.lower(), {"topic_label": skill, "topic_text": skill, "evidence_type": "derived_from_curriculum_text"})
        return list(topics.values())[:40]

    def _skills(self, text: str, chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
        lower = text.lower()
        skills = []
        for skill, category, aliases in self.SKILL_PATTERNS:
            hits = [alias for alias in aliases if alias in lower]
            if not hits:
                continue
            if skill == "Advanced SQL" and "advanced sql" not in lower:
                continue
            source_pages = []
            for chunk in chunks:
                chunk_lower = self._normalise_text(chunk.content or "").lower()
                if any(alias in chunk_lower for alias in aliases):
                    source_pages.append(chunk.page_start)
            evidence_count = len(set(source_pages)) or len(hits)
            if category == "professional" and evidence_count < 2:
                continue
            skills.append({"skill_name": skill, "skill_category": category, "evidence_count": evidence_count, "source_pages": sorted({p for p in source_pages if p is not None}), "confidence_score": 0.85 if evidence_count >= 2 else 0.7, "extraction_method": "rules_v1_alias_from_subject_profile"})
        return sorted(skills, key=lambda item: (-item["evidence_count"], item["skill_name"]))

    def _clean(self, value: str, max_chars: int) -> str:
        value = self._normalise_text(value)
        value = re.sub(r"\.{4,}", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        value = re.sub(r"^[:\-\s]+", "", value)
        return value[:max_chars].strip()

    def _normalise_text(self, value: str) -> str:
        result = str(value or "")
        # Normalise common mojibake/control fragments without depending on fragile console encodings.
        result = result.replace("\uFFFD", "")
        result = result.replace("??", "")
        result = result.replace("???", "-").replace("???", "-")
        result = result.replace("???", "'").replace("???", '"').replace("???", '"')
        result = result.replace("??~", "-")
        result = result.replace("?Ts", "'s").replace("?T", "'").replace("?~", "-")
        result = re.sub(r"[?]{2,}", "", result)
        return result

    def _institution(self, text: str) -> str | None:
        return "Cape Peninsula University of Technology" if "cape peninsula university of technology" in text.lower() or "cput" in text.lower() else None

    def _programme_code(self, text: str) -> str | None:
        match = re.search(r"\b(DIPICT[A-Z]?)\b", text.upper())
        return match.group(1) if match else None

    def _qualification_type(self, programme: str | None, text: str) -> str | None:
        value = f"{programme or ''} {text[:3000]}".lower()
        if "advanced diploma" in value:
            return "Advanced Diploma"
        if "postgraduate diploma" in value:
            return "Postgraduate Diploma"
        if "diploma" in value:
            return "Diploma"
        return None

    def _upsert_module(self, db: Session, document, code: str, name: str, nqf: int | None, credits: int | None, purpose: str | None):
        if code == "UNKNOWN":
            return None
        module = db.query(CurriculumModule).filter(CurriculumModule.module_code == code).first()
        if not module:
            module = CurriculumModule(module_code=code, module_name=name, programme_id=document.programme_id if document else None)
            db.add(module)
        module.module_name = name or module.module_name
        module.programme_id = document.programme_id if document and document.programme_id else module.programme_id
        module.description = purpose or module.description
        module.nqf_level = nqf or module.nqf_level
        module.credits = credits or module.credits
        module.faculty = document.faculty if document and document.faculty else module.faculty
        module.programme = document.programme if document and document.programme else module.programme
        module.data_source = "curriculum_subject_profile"
        db.flush()
        return module


curriculum_subject_profile_service = CurriculumSubjectProfileService()

