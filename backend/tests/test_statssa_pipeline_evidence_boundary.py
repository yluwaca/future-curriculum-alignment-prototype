from app.services.pipeline_orchestrator_service import PipelineOrchestratorService


def test_statssa_pipeline_does_not_create_vacancy_skill_evidence():
    service = PipelineOrchestratorService()

    result = service.stage_skill_demand_evidence(db=None, context={})

    assert result["status"] == "skipped_evidence_boundary"
    assert result["evidence_created"] == 0
    assert "not vacancy-level" in result["reason"]


def test_statssa_pipeline_does_not_publish_decision_outputs():
    service = PipelineOrchestratorService()

    analytics = service.stage_analytics(db=None, context={})
    reports = service.stage_reports(db=None, context={})

    assert analytics["status"] == "skipped_evidence_boundary"
    assert analytics["recommendations_created"] == 0
    assert analytics["alignments_created"] == 0
    assert reports["reports_generated"] == 0
