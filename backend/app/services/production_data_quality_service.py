"""Production data quality summary service."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Dict, Iterable, List

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.cleaned_ingestion_record import CleanedIngestionRecord
from app.models.data_source import DataSource
from app.models.document_chunk import DocumentChunk
from app.models.extracted_table import ExtractedTable
from app.models.extracted_table_row import ExtractedTableRow
from app.models.job_posting import JobPosting
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.curriculum_quality_service import curriculum_quality_service
from app.services.ingestion.table_extraction_service import TableExtractionPersistenceService


class ProductionDataQualityService:
    """Summarises the production-readiness quality state of major data streams."""

    def data_quality_summary(self, db: Session) -> Dict[str, Any]:
        curriculum = curriculum_quality_service.summary(db)
        job_quality = self.job_cleaning_quality(db)
        canonical_mapping = self.canonical_mapping_quality(db)
        review_queue = self.review_queue_quality(db)
        scores = [
            curriculum.get("quality_score") or 0.0,
            job_quality.get("quality_score") or 0.0,
            canonical_mapping.get("quality_score") or 0.0,
            review_queue.get("quality_score") or 0.0,
        ]
        return {
            "phase": "Ingestion Data Quality",
            "overall_quality_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "curriculum_extraction_quality": curriculum,
            "job_data_cleaning_quality": job_quality,
            "stats_che_canonical_mapping_quality": canonical_mapping,
            "review_queue_quality": review_queue,
            "next_actions": self.next_actions(curriculum, job_quality, canonical_mapping, review_queue),
        }

    def job_cleaning_quality(self, db: Session) -> Dict[str, Any]:
        stats = db.execute(text("""
            select
                count(*) as total,
                count(*) filter (where nullif(trim(job_title), '') is not null) as with_title,
                count(*) filter (where nullif(trim(coalesce(job_description, '')), '') is not null) as with_description,
                count(*) filter (where nullif(trim(region), '') is not null) as with_region,
                count(*) filter (where nullif(trim(coalesce(employment_type, '')), '') is not null) as with_employment_type,
                count(*) filter (where salary_min is not null or salary_max is not null) as with_salary,
                count(*) filter (where posted_date is not null) as with_posted_date,
                count(*) filter (where required_skills is not null and required_skills::text not in ('{}', '[]', 'null')) as with_required_skills,
                count(*) filter (where is_processed is true) as processed
            from job_posting
        """)).mappings().first() or {}
        total = int(stats.get("total") or 0)
        completeness_counts = {
            "with_title": int(stats.get("with_title") or 0),
            "with_description": int(stats.get("with_description") or 0),
            "with_region": int(stats.get("with_region") or 0),
            "with_employment_type": int(stats.get("with_employment_type") or 0),
            "with_salary": int(stats.get("with_salary") or 0),
            "with_posted_date": int(stats.get("with_posted_date") or 0),
            "with_required_skills": int(stats.get("with_required_skills") or 0),
            "processed": int(stats.get("processed") or 0),
        }
        duplicate_job_ids = int(db.execute(text("""
            select count(*) from (
                select job_id from job_posting group by job_id having count(*) > 1
            ) duplicate_groups
        """)).scalar() or 0)
        cleaned_stats = db.execute(text("""
            select count(*) as cleaned_job_records, coalesce(avg(quality_score), 0) as avg_quality
            from cleaned_ingestion_record
            where normaliser_key in ('job_advert_v1', 'job_board_payload_v1')
        """)).mappings().first() or {}
        cleaned_job_records = int(cleaned_stats.get("cleaned_job_records") or 0)
        avg_cleaned_quality = float(cleaned_stats.get("avg_quality") or 0.0)
        source_counts = self.query_counter(db, "select coalesce(source, 'unknown') as key, count(*) as value from job_posting group by 1 order by value desc limit 10")
        employment_counts = self.query_counter(db, "select coalesce(employment_type, 'unknown') as key, count(*) as value from job_posting group by 1 order by value desc limit 10")
        region_counts = self.query_counter(db, "select coalesce(region, 'unknown') as key, count(*) as value from job_posting group by 1 order by value desc limit 10")
        completeness = self.with_percentages(completeness_counts, total)
        components = [
            completeness["with_title"]["ratio"],
            completeness["with_description"]["ratio"],
            completeness["with_region"]["ratio"],
            completeness["with_posted_date"]["ratio"],
            completeness["with_required_skills"]["ratio"],
            1.0 if duplicate_job_ids == 0 else max(0.0, 1.0 - duplicate_job_ids / max(total, 1)),
            avg_cleaned_quality if cleaned_job_records else 0.0,
        ]
        issues = []
        if total and completeness["with_required_skills"]["ratio"] < 0.70:
            issues.append("Many job records still need stronger skill extraction or declared-skill parsing.")
        if total and completeness["with_employment_type"]["ratio"] < 0.50:
            issues.append("Employment type normalisation is sparse across job records.")
        if total and completeness["with_salary"]["ratio"] < 0.30:
            issues.append("Salary values are sparse; salary-based demand features should remain optional.")
        if duplicate_job_ids:
            issues.append(f"{duplicate_job_ids} duplicate external job identifiers were detected.")
        return {
            "job_postings": total,
            "cleaned_job_records": cleaned_job_records,
            "average_cleaned_quality_score": round(avg_cleaned_quality, 4),
            "completeness": completeness,
            "duplicate_job_id_groups": duplicate_job_ids,
            "top_sources": source_counts,
            "employment_type_counts": employment_counts,
            "top_regions": region_counts,
            "issues": issues,
            "quality_score": round(sum(components) / len(components), 4) if components else 0.0,
        }

    def canonical_mapping_quality(self, db: Session) -> Dict[str, Any]:
        table_stats = db.execute(text("""
            select
                count(*) as table_total,
                count(*) filter (where nullif(trim(coalesce(title, '')), '') is not null) as table_title_count
            from extracted_table
        """)).mappings().first() or {}
        row_stats = db.execute(text("""
            select
                count(*) as row_total,
                count(*) filter (
                    where coalesce(normalised_payload->>'canonical_indicator_group', normalised_payload->>'canonical_table', 'unknown') = 'unknown'
                       or coalesce(normalised_payload->>'canonical_domain', 'unknown') = 'unknown'
                       or coalesce(normalised_payload->>'source_family', 'unknown') = 'unknown'
                ) as unknown_rows,
                count(*) filter (
                    where coalesce(normalised_payload->>'mapping_confidence', '0') ~ '^[0-9.]+$'
                      and (normalised_payload->>'mapping_confidence')::float < 0.60
                ) as low_confidence_rows,
                count(*) filter (
                    where coalesce(normalised_payload->>'row_role', normalised_payload->>'canonical_row_role', '') in ('data', 'fact', 'valid_fact')
                       or normalised_payload->>'is_valid_fact' = 'true'
                ) as valid_fact_rows,
                coalesce(avg((normalised_payload->>'mapping_confidence')::float) filter (
                    where coalesce(normalised_payload->>'mapping_confidence', '') ~ '^[0-9.]+$'
                ), 0) as avg_confidence
            from extracted_table_row
        """)).mappings().first() or {}
        table_total = int(table_stats.get("table_total") or 0)
        row_total = int(row_stats.get("row_total") or 0)
        table_title_count = int(table_stats.get("table_title_count") or 0)
        unknown_rows = int(row_stats.get("unknown_rows") or 0)
        low_confidence_rows = int(row_stats.get("low_confidence_rows") or 0)
        valid_fact_rows = int(row_stats.get("valid_fact_rows") or 0)
        avg_confidence = float(row_stats.get("avg_confidence") or 0.0)
        unknown_ratio = unknown_rows / row_total if row_total else 0.0
        low_confidence_ratio = low_confidence_rows / row_total if row_total else 0.0
        source_counts = self.query_counter(db, """
            select coalesce(normalised_payload->>'source_family', 'unknown') as key, count(*) as value
            from extracted_table_row group by 1 order by value desc limit 10
        """)
        indicator_counts = self.query_counter(db, """
            select coalesce(normalised_payload->>'canonical_indicator_group', normalised_payload->>'canonical_table', 'unknown') as key, count(*) as value
            from extracted_table_row group by 1 order by value desc limit 15
        """)
        domain_counts = self.query_counter(db, """
            select coalesce(normalised_payload->>'canonical_domain', 'unknown') as key, count(*) as value
            from extracted_table_row group by 1 order by value desc limit 10
        """)
        role_counts = self.query_counter(db, """
            select coalesce(normalised_payload->>'row_role', normalised_payload->>'canonical_row_role', 'unknown') as key, count(*) as value
            from extracted_table_row group by 1 order by value desc limit 10
        """)
        components = [
            table_title_count / table_total if table_total else 0.0,
            1.0 - unknown_ratio if row_total else 0.0,
            1.0 - low_confidence_ratio if row_total else 0.0,
            avg_confidence,
            valid_fact_rows / row_total if row_total else 0.0,
        ]
        issues = []
        if table_total and table_title_count / table_total < 0.65:
            issues.append("Many extracted tables still need clearer table title detection.")
        if unknown_ratio > 0.25:
            issues.append("A high share of extracted rows still map to unknown source/domain/indicator groups.")
        if low_confidence_ratio > 0.25:
            issues.append("Many table rows have low canonical mapping confidence.")
        if valid_fact_rows == 0 and row_total:
            issues.append("Rows are extracted, but valid fact/header/note separation still needs improvement.")
        return {
            "extracted_tables": table_total,
            "extracted_rows": row_total,
            "tables_with_titles": table_title_count,
            "average_mapping_confidence": round(avg_confidence, 4),
            "unknown_row_count": unknown_rows,
            "unknown_row_percent": round(unknown_ratio * 100, 2) if row_total else 0.0,
            "low_confidence_row_count": low_confidence_rows,
            "valid_fact_rows": valid_fact_rows,
            "source_family_counts": source_counts,
            "indicator_group_counts": indicator_counts,
            "domain_counts": domain_counts,
            "row_role_counts": role_counts,
            "issues": issues,
            "quality_score": round(sum(components) / len(components), 4) if components else 0.0,
        }

    def review_queue_quality(self, db: Session) -> Dict[str, Any]:
        problem_statuses = "'failed', 'warning', 'invalid', 'skipped', 'noise', 'unmatched', 'pending'"
        stats = db.execute(text(f"""
            select
                count(*) as total,
                count(*) filter (where (normalised_payload->'review_metadata'->>'reviewed_at') is not null) as reviewed,
                count(*) filter (where normalised_payload->'review_metadata'->>'corrected' = 'true') as corrected,
                count(*) filter (
                    where coalesce(normalised_payload->>'confidence_score', '1') ~ '^[0-9.]+$'
                      and (normalised_payload->>'confidence_score')::float < 0.60
                       or coalesce(normalised_payload->>'quality_score', '1') ~ '^[0-9.]+$'
                      and (normalised_payload->>'quality_score')::float < 0.60
                ) as low_confidence
            from raw_ingestion_record
            where validation_status in ({problem_statuses})
        """)).mappings().first() or {}
        total = int(stats.get("total") or 0)
        reviewed = int(stats.get("reviewed") or 0)
        corrected = int(stats.get("corrected") or 0)
        low_confidence = int(stats.get("low_confidence") or 0)
        status_counts = self.query_counter(db, f"""
            select validation_status as key, count(*) as value
            from raw_ingestion_record
            where validation_status in ({problem_statuses})
            group by 1 order by value desc
        """)
        category_counts = self.query_counter(db, f"""
            select coalesce(data_source.source_category, 'unknown') as key, count(*) as value
            from raw_ingestion_record
            left join data_source on raw_ingestion_record.source_id = data_source.source_id
            where validation_status in ({problem_statuses})
            group by 1 order by value desc
        """)
        record_type_counts = self.query_counter(db, f"""
            select record_type as key, count(*) as value
            from raw_ingestion_record
            where validation_status in ({problem_statuses})
            group by 1 order by value desc limit 15
        """)
        unresolved_ratio = 1.0 - (reviewed / total) if total else 0.0
        components = [
            1.0 - min(total, 1000) / 1000,
            1.0 - unresolved_ratio,
            1.0 - (low_confidence / total if total else 0.0),
        ]
        issues = []
        if total > 500:
            issues.append("The review queue is large; add bulk filters/actions before production use.")
        if low_confidence:
            issues.append(f"{low_confidence} queued records are low-confidence and should be prioritised.")
        if category_counts.get("unknown", 0):
            issues.append("Some queued records are not linked to a classified source category.")
        return {
            "queued_records": total,
            "reviewed_records": reviewed,
            "corrected_records": corrected,
            "low_confidence_records": low_confidence,
            "status_counts": status_counts,
            "source_category_counts": category_counts,
            "record_type_counts": record_type_counts,
            "issues": issues,
            "quality_score": round(sum(components) / len(components), 4) if components else 1.0,
        }

    def remap_extracted_table_rows(self, db: Session, limit: int = 5000) -> Dict[str, Any]:
        rows = (
            db.query(ExtractedTableRow)
            .order_by(ExtractedTableRow.updated_at.asc())
            .limit(limit)
            .all()
        )
        updated = 0
        changed_groups = Counter()
        for row in rows:
            previous = row.normalised_payload or {}
            next_payload = TableExtractionPersistenceService.normalise_row(row.row_payload or {})
            if next_payload != previous:
                updated += 1
                changed_groups[next_payload.get("canonical_indicator_group") or "unknown"] += 1
                row.normalised_payload = next_payload
        db.commit()
        return {
            "rows_checked": len(rows),
            "rows_updated": updated,
            "changed_indicator_groups": dict(changed_groups.most_common(15)),
        }

    def next_actions(
        self,
        curriculum: Dict[str, Any],
        job_quality: Dict[str, Any],
        canonical_mapping: Dict[str, Any],
        review_queue: Dict[str, Any],
    ) -> List[str]:
        actions: List[str] = []
        for label, section in [
            ("Curriculum", curriculum),
            ("Job data", job_quality),
            ("StatsSA/CHE mapping", canonical_mapping),
            ("Review queue", review_queue),
        ]:
            for issue in section.get("issues") or []:
                actions.append(f"{label}: {issue}")
        return actions[:12]

    @staticmethod
    def query_counter(db: Session, sql: str) -> Dict[str, int]:
        rows = db.execute(text(sql)).mappings().all()
        return {str(row["key"]): int(row["value"] or 0) for row in rows}

    @staticmethod
    def with_percentages(counts: Dict[str, int], total: int) -> Dict[str, Dict[str, float]]:
        return {
            key: {
                "count": value,
                "percent": round((value / total * 100), 2) if total else 0.0,
                "ratio": round((value / total), 4) if total else 0.0,
            }
            for key, value in counts.items()
        }

    @staticmethod
    def text_present(value: Any) -> bool:
        return bool(str(value or "").strip())

    @staticmethod
    def safe_float(value: Any, default: float | None = 0.0) -> float | None:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default


production_data_quality_service = ProductionDataQualityService()
