import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.backup_restore_service import BackupRestoreService


ROOT = Path(__file__).resolve().parents[1]


def _manifest(root: Path, backup_id: str, created_at: datetime) -> None:
    target = root / backup_id
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(
        json.dumps({"backup_id": backup_id, "created_at": created_at.isoformat()}),
        encoding="utf-8",
    )


def test_retention_always_keeps_latest_and_never_permanently_deletes(monkeypatch):
    tmp_path = ROOT / "data" / "test_backup_retention_contract"
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True)
    try:
        service = BackupRestoreService()
        monkeypatch.setattr(service, "BACKUP_ROOT", tmp_path / "snapshots")
        monkeypatch.setattr(service, "QUARANTINE_ROOT", tmp_path / "quarantine")
        monkeypatch.setenv("FUTURE_BACKUP_RETENTION_DAILY", "1")
        monkeypatch.setenv("FUTURE_BACKUP_RETENTION_WEEKLY", "1")
        monkeypatch.setenv("FUTURE_BACKUP_RETENTION_MONTHLY", "1")
        now = datetime.now(timezone.utc)
        _manifest(service.BACKUP_ROOT, "old_1", now - timedelta(days=400))
        _manifest(service.BACKUP_ROOT, "old_2", now - timedelta(days=200))
        _manifest(service.BACKUP_ROOT, "latest", now)

        plan = service.retention_plan()
        assert "latest" in plan["keep"]
        assert plan["destructive_delete"] is False
        result = service.apply_retention(actor_id="admin")
        assert result["recoverable"] is True
        assert not (service.BACKUP_ROOT / "old_1").exists()
        assert list(service.QUARANTINE_ROOT.glob("*/old_1/manifest.json"))
    finally:
        shutil.rmtree(tmp_path)


def test_restore_drill_uses_generated_database_and_guaranteed_cleanup():
    source = (ROOT / "app/services/backup_restore_service.py").read_text(encoding="utf-8")
    assert 'database_name = f"future_restore_' in source
    assert 'if not database_name.startswith("future_restore_")' in source
    assert '"dropdb.exe"' in source
    assert '"--force"' in source
    assert 'result["temporary_database_removed"] = True' in source
    assert '"live_database_modified": False' in source


def test_restore_authority_is_separate_from_application_credentials():
    source = (ROOT / "app/services/backup_restore_service.py").read_text(encoding="utf-8")
    assert 'os.getenv("FUTURE_RESTORE_ADMIN_DATABASE_URL"' in source
    assert "The application role remains least-privileged" in source
    router = (ROOT / "app/routers/operations.py").read_text(encoding="utf-8")
    assert '@router.get("/backups/restore-readiness")' in router
    assert "administrative_database_url" in router
    assert "result.pop" in router


def test_portal_exposes_retention_and_restore_controls():
    html = (ROOT.parent / "frontend/system-operations.html").read_text(encoding="utf-8")
    actions = (ROOT.parent / "frontend/dashboard-actions.js").read_text(encoding="utf-8")
    assert 'id="applyBackupRetentionBtn"' in html
    assert 'id="runRestoreDrillBtn"' in html
    assert "No backup will be permanently deleted" in actions
    assert "The live database is not changed" in actions
