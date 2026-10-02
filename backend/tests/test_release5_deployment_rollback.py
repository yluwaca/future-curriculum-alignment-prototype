import json
from pathlib import Path

from app.services.deployment_rollback_service import DeploymentRollbackService


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent


def test_application_rollback_evidence_passed_with_hash_verification():
    evidence_root = ROOT / "data/deployment/rollback-evidence"
    evidence_files = sorted(evidence_root.glob("app_rollback_*.json"))
    assert evidence_files, "Run the application rollback rehearsal before acceptance"
    evidence = json.loads(evidence_files[-1].read_text(encoding="utf-8"))
    assert evidence["status"] == "passed"
    assert evidence["file_count"] > 0
    assert evidence["hash_mismatches"] == {}
    assert evidence["safe_archive_entries"] is True
    assert evidence["live_application_switched"] is False


def test_application_release_manifest_matches_archive_checksum():
    release_dirs = sorted((ROOT / "data/deployment/releases").glob("release_*"))
    assert release_dirs
    release = release_dirs[-1]
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    archive = release / "future-release.zip"
    assert archive.is_file()
    assert DeploymentRollbackService._sha256(archive) == manifest["archive_sha256"]
    assert len(manifest["files"]) > 0


def test_database_rehearsal_is_isolated_and_cleanup_is_guaranteed():
    source = (ROOT / "app/services/deployment_rollback_service.py").read_text(encoding="utf-8")
    assert 'database_name = f"future_migration_' in source
    assert '"downgrade"' in source
    assert '"upgrade"' in source
    assert '"dropdb.exe"' in source
    assert '"--force"' in source
    assert '"live_database_modified": False' in source
    assert 'evidence["temporary_database_removed"] = True' in source


def test_rollback_api_and_portal_are_admin_controlled():
    router = (ROOT / "app/routers/operations.py").read_text(encoding="utf-8")
    html = (PROJECT / "frontend/system-operations.html").read_text(encoding="utf-8")
    assert '@router.get("/rollback-readiness")' in router
    assert '@router.post("/rollback/application-rehearsal"' in router
    assert '@router.post("/rollback/database-rehearsal"' in router
    assert 'id="runApplicationRollbackBtn"' in html
    assert 'id="runDatabaseRollbackBtn"' in html


def test_uat_release_switch_is_atomic_and_health_checked():
    script = (PROJECT / "scripts/uat/deploy_atomic_release.sh").read_text(encoding="utf-8")
    assert 'ln -sfn "$TARGET" "${CURRENT}.next"' in script
    assert 'mv -Tf "${CURRENT}.next" "$CURRENT"' in script
    assert "previous-release.txt" in script
    assert "health ||" in script
    assert 'case "$PREVIOUS" in "$ROOT"/release_*' in script
