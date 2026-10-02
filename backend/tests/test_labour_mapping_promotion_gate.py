from pathlib import Path


def test_job_signal_generation_requires_approved_mapping():
    source = (
        Path(__file__).parents[1]
        / "app"
        / "services"
        / "labour_market_skill_pipeline_service.py"
    ).read_text(encoding="utf-8")
    start = source.index("def generate_job_skill_signals")
    end = source.index("def generate_job_skill_demand_evidence", start)
    method = source[start:end]
    assert 'SkillMapping.mapping_status == "approved"' in method
    assert '"promotion_gate": "approved_labour_mappings_only"' in method
