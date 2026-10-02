"""Repeatable data sanity checks for the current configured database."""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import engine


MINIMUM_COUNTS = {
    "curriculum_document": 1,
    "curriculum_document_version": 1,
    "document_chunk": 1,
    "job_posting": 1,
    "raw_ingestion_record": 1,
    "cleaned_ingestion_record": 1,
    "labour_market_signal": 1,
    "skill": 1,
    "skill_mapping": 1,
    "skill_demand_evidence": 1,
    "alignment_score": 1,
    "forecast": 1,
    "recommendation": 1,
    "ingestion_job": 1,
}


def table_count(table_name: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"select count(*) from {table_name}")).scalar() or 0)


def test_core_tables_have_repeatable_baseline_data() -> None:
    failures = []
    for table_name, minimum in MINIMUM_COUNTS.items():
        count = table_count(table_name)
        if count < minimum:
            failures.append(f"{table_name}: expected >= {minimum}, got {count}")
    assert not failures, "Baseline data checks failed: " + "; ".join(failures)


def test_raw_cleaned_and_skill_relationships_are_plausible() -> None:
    raw_records = table_count("raw_ingestion_record")
    cleaned_records = table_count("cleaned_ingestion_record")
    skills = table_count("skill")
    mappings = table_count("skill_mapping")
    demand_evidence = table_count("skill_demand_evidence")
    signals = table_count("labour_market_signal")

    assert raw_records >= cleaned_records, "Cleaned records should not exceed raw records"
    assert skills > 0 and mappings > 0 and signals > 0
    assert demand_evidence > 0, "Demand evidence should exist once labour-market data is normalised"
    with engine.connect() as connection:
        mapped_domains = int(
            connection.execute(
                text("select count(distinct source_domain) from skill_mapping")
            ).scalar()
            or 0
        )
    assert mapped_domains > 0, "Skill mappings should identify at least one evidence domain"


def test_review_queue_filter_has_current_job_records(client, auth_headers) -> None:
    response = client.get(
        "/api/v1/ingestion/records/review?limit=5&source_category=current_jobs",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert isinstance(rows, list)
    for row in rows:
        assert row.get("source_category") in {"current_jobs", None}



def test_data_quality_summary_has_required_sections(client, auth_headers) -> None:
    response = client.get("/api/v1/ingestion/data-quality/summary", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["phase"] == "Ingestion Data Quality"
    assert 0 <= payload["overall_quality_score"] <= 1
    for key in [
        "curriculum_extraction_quality",
        "job_data_cleaning_quality",
        "stats_che_canonical_mapping_quality",
        "review_queue_quality",
    ]:
        assert key in payload
        assert 0 <= payload[key]["quality_score"] <= 1
    assert isinstance(payload.get("next_actions"), list)
