from pathlib import Path

from app.services.research_claim_reconciliation_service import (
    ResearchClaimReconciliationService,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent


def test_claim_catalog_covers_material_paper_overclaims():
    source = (ROOT / "app/services/research_claim_reconciliation_service.py").read_text(encoding="utf-8")
    for claim_id in [f"C{number:02d}" for number in range(1, 17)]:
        assert f'"{claim_id}"' in source
    for status in (
        "simulation_only",
        "reproducibility_blocked",
        "claim_must_change",
        "external_validation_required",
    ):
        assert status in source


def test_claim_gate_depends_on_reproducible_evidence_not_code_presence():
    source = (ROOT / "app/services/research_claim_reconciliation_service.py").read_text(encoding="utf-8")
    assert "LabelDatasetSnapshot" in source
    assert "ModelRegistryEntry" in source
    assert '"camera_ready_gate": "revision_required" if blocking' in source
    assert "No active registry-approved XGBoost model" in source
    assert "No active registry-approved LSTM model" in source


def test_reviewer_actions_and_deadline_are_encoded():
    source = (ROOT / "app/services/research_claim_reconciliation_service.py").read_text(encoding="utf-8")
    assert '"camera_ready_due": "2026-08-20"' in source
    assert "Replace Figures 1-3" in source
    assert "Rebuild Tables I-II" in source
    assert "Remove citations from the conclusion" in source
    assert "38.2% strictly as a simulated sandbox result" in source


def test_claim_report_is_archivable_and_visible_in_system_operations():
    router = (ROOT / "app/routers/operations.py").read_text(encoding="utf-8")
    portal = (PROJECT / "frontend/system-operations.html").read_text(encoding="utf-8")
    assert '@router.get("/research-claims")' in router
    assert '@router.post("/research-claims/archive")' in router
    assert 'id="loadResearchClaimsBtn"' in portal
    assert 'id="researchClaimRows"' in portal


def test_paper_hash_is_bound_to_the_evidence_report():
    service = ResearchClaimReconciliationService()
    assert service.PAPER_PATH.is_file()
    assert len(service._sha256(service.PAPER_PATH)) == 64
