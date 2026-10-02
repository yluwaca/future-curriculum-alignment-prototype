from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACTIONS = PROJECT_ROOT / "frontend" / "dashboard-actions.js"


def test_xgboost_uses_locked_reviewed_label_snapshot_for_preflight():
    source = ACTIONS.read_text(encoding="utf-8")
    train_block = source[source.index("async function trainModel"):source.index("async function loadDashboard")]

    assert "const usesReviewedLabelSnapshot = modelType === 'xgboost';" in train_block
    assert "? Boolean(state.alignmentLabelSnapshot)" in train_block
    assert "postJson(endpoint, {})" in train_block
    assert "btn.disabled = !compatible;" in train_block
