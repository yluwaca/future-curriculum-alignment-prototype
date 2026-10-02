"""
Curriculum data quality checks for programme/module/outcome extraction.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.academic_programme import AcademicProgramme
from app.models.curriculum_module import CurriculumModule
from app.models.document_chunk import DocumentChunk
from app.models.skill_mapping import SkillMapping


class CurriculumQualityService:
    def summary(self, db: Session) -> Dict[str, Any]:
        # Inactive rows are retained for provenance/audit but must not distort
        # current curriculum readiness or downstream quality gates.
        modules = db.query(CurriculumModule).filter(CurriculumModule.is_active.is_(True)).all()
        programmes = db.query(AcademicProgramme).all()
        chunks = db.query(DocumentChunk).limit(50000).all()

        module_count = len(modules)
        programme_count = len(programmes)
        chunk_count = len(chunks)

        outcome_counts = Counter((chunk.chunk_metadata or {}).get("outcome_type") or "unknown" for chunk in chunks)
        section_counts = Counter((chunk.chunk_metadata or {}).get("section") or "unknown" for chunk in chunks)
        module_chunk_counts = Counter(((chunk.chunk_metadata or {}).get("module_code") or str(chunk.module_id or "unknown")) for chunk in chunks)
        evidence_type_counts = Counter((chunk.chunk_metadata or {}).get("curriculum_evidence_type") or "unknown" for chunk in chunks)
        document_evidence_type_counts = Counter((chunk.chunk_metadata or {}).get("document_evidence_type") or "unknown" for chunk in chunks)
        linked_chunk_count = sum(1 for chunk in chunks if chunk.module_id or (chunk.chunk_metadata or {}).get("module_code"))
        chunks_with_assessment_criteria = sum(1 for chunk in chunks if (chunk.chunk_metadata or {}).get("contains_assessment_criteria"))
        chunks_with_topics = sum(1 for chunk in chunks if (chunk.chunk_metadata or {}).get("contains_module_topics"))
        chunks_with_assessments = sum(1 for chunk in chunks if (chunk.chunk_metadata or {}).get("contains_assessment_methods"))

        curriculum_skill_mappings = (
            db.query(func.count(SkillMapping.mapping_id))
            .filter(SkillMapping.source_domain == "curriculum")
            .scalar()
            or 0
        )

        module_completeness = {
            "with_programme_id": sum(1 for item in modules if item.programme_id),
            "with_description": sum(1 for item in modules if item.description),
            "with_credits": sum(1 for item in modules if item.credits is not None),
            "with_nqf_level": sum(1 for item in modules if item.nqf_level is not None),
            "with_faculty": sum(1 for item in modules if item.faculty),
            "with_programme_name": sum(1 for item in modules if item.programme),
        }
        module_counts_by_programme = Counter(str(item.programme_id) for item in modules if item.programme_id)
        zero_module_programmes = [
            {
                "programme_id": str(item.programme_id),
                "programme_name": item.name,
                "status": item.status,
                "reason": "No module data was extracted from the source",
            }
            for item in programmes
            if module_counts_by_programme.get(str(item.programme_id), 0) == 0
        ]
        programme_completeness = {
            "with_department": sum(1 for item in programmes if item.department_id),
            "with_qualification_type": sum(1 for item in programmes if item.qualification_type),
            "with_nqf_level": sum(1 for item in programmes if item.nqf_level),
            "with_description": sum(1 for item in programmes if item.description),
        }

        issues = []
        if module_count and module_completeness["with_credits"] / module_count < 0.8:
            issues.append("Many modules are missing credits.")
        if module_count and module_completeness["with_nqf_level"] / module_count < 0.8:
            issues.append("Many modules are missing NQF levels.")
        if chunk_count and outcome_counts.get("unknown", 0) / chunk_count > 0.5:
            issues.append("Many chunks do not yet have a classified outcome type.")
        if curriculum_skill_mappings == 0:
            issues.append("Curriculum skill extraction has not produced mappings yet.")
        if zero_module_programmes:
            issues.append(f"{len(zero_module_programmes)} programme(s) have no extracted module data and require source or metadata review.")

        return {
            "programmes": programme_count,
            "modules": module_count,
            "chunks": chunk_count,
            "curriculum_skill_mappings": curriculum_skill_mappings,
            "module_completeness": self.with_percentages(module_completeness, module_count),
            "programme_completeness": self.with_percentages(programme_completeness, programme_count),
            "zero_module_programmes": zero_module_programmes,
            "outcome_type_counts": dict(outcome_counts.most_common(20)),
            "section_counts": dict(section_counts.most_common(20)),
            "top_module_chunk_counts": dict(module_chunk_counts.most_common(20)),
            "evidence_type_counts": dict(evidence_type_counts.most_common(20)),
            "document_evidence_type_counts": dict(document_evidence_type_counts.most_common(20)),
            "chunk_linkage": {
                "linked_to_module_or_code": linked_chunk_count,
                "linked_percent": round((linked_chunk_count / chunk_count * 100), 2) if chunk_count else 0.0,
                "with_assessment_criteria": chunks_with_assessment_criteria,
                "with_topics": chunks_with_topics,
                "with_assessment_methods": chunks_with_assessments,
            },
            "issues": issues,
            "quality_score": self.quality_score(module_completeness, module_count, programme_completeness, programme_count, chunk_count, outcome_counts, curriculum_skill_mappings),
        }

    @staticmethod
    def with_percentages(counts: Dict[str, int], total: int) -> Dict[str, Dict[str, float]]:
        return {
            key: {
                "count": value,
                "percent": round((value / total * 100), 2) if total else 0.0,
            }
            for key, value in counts.items()
        }

    @staticmethod
    def quality_score(
        module_counts: Dict[str, int],
        module_total: int,
        programme_counts: Dict[str, int],
        programme_total: int,
        chunk_total: int,
        outcome_counts: Counter,
        curriculum_skill_mappings: int,
    ) -> float:
        components = []
        if module_total:
            components.extend(
                [
                    module_counts["with_description"] / module_total,
                    module_counts["with_credits"] / module_total,
                    module_counts["with_nqf_level"] / module_total,
                    module_counts["with_programme_name"] / module_total,
                ]
            )
        if programme_total:
            components.extend(
                [
                    programme_counts["with_qualification_type"] / programme_total,
                    programme_counts["with_nqf_level"] / programme_total,
                ]
            )
        if chunk_total:
            components.append(1 - (outcome_counts.get("unknown", 0) / chunk_total))
        components.append(1.0 if curriculum_skill_mappings else 0.0)
        return round(sum(components) / len(components), 4) if components else 0.0


curriculum_quality_service = CurriculumQualityService()
