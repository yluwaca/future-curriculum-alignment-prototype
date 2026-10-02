"""Non-destructive application and isolated database rollback rehearsals."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.services.backup_restore_service import backup_restore_service


class DeploymentRollbackService:
    ROOT = Path(__file__).resolve().parents[3]
    EVIDENCE_ROOT = Path("data/deployment/rollback-evidence")
    RELEASE_ROOT = Path("data/deployment/releases")
    INCLUDE_ROOTS = (
        "backend/app", "backend/migrations", "frontend", "scripts",
        "nginx", "docker-compose.yml", "backend/alembic.ini",
        "backend/requirements.txt", ".env.production.example",
    )
    EXCLUDED_PARTS = {"__pycache__", ".git", "venv", "node_modules", "data", "logs"}

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    def readiness(self) -> dict[str, Any]:
        database = backup_restore_service.restore_drill_readiness()
        database.pop("administrative_database_url", None)
        latest = self.latest_evidence()
        return {
            "application_rehearsal_ready": True,
            "database_rehearsal_ready": database["ready"],
            "database_authority": database,
            "latest_evidence": latest,
            "live_application_switching": False,
            "live_database_modified": False,
        }

    def run_application_rehearsal(self, actor_id: str | None = None) -> dict[str, Any]:
        self.EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
        self.RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
        release_id = f"release_{self.now().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        release_dir = self.RELEASE_ROOT / release_id
        release_dir.mkdir(parents=True, exist_ok=False)
        archive_path = release_dir / "future-release.zip"
        source_hashes = self._source_hashes()
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in source_hashes:
                archive.write(self.ROOT / relative, arcname=relative)
        archive_sha = self._sha256(archive_path)
        with tempfile.TemporaryDirectory(prefix="future-release-rollback-") as temporary:
            extracted = Path(temporary)
            with zipfile.ZipFile(archive_path, "r") as archive:
                unsafe = [
                    name for name in archive.namelist()
                    if Path(name).is_absolute() or ".." in Path(name).parts
                ]
                if unsafe:
                    raise ValueError(f"Unsafe release archive entries: {unsafe[:5]}")
                archive.extractall(extracted)
            restored_hashes = {
                relative: self._sha256(extracted / relative)
                for relative in source_hashes
            }
        mismatches = {
            path: {"source": digest, "restored": restored_hashes.get(path)}
            for path, digest in source_hashes.items()
            if restored_hashes.get(path) != digest
        }
        if mismatches:
            raise ValueError(f"Application rollback bundle hash mismatch: {list(mismatches)[:5]}")
        previous = self._previous_release(release_id)
        evidence = {
            "rehearsal_id": f"app_rollback_{uuid.uuid4().hex[:10]}",
            "type": "application_release_rollback",
            "status": "passed",
            "completed_at": self.now().isoformat(),
            "completed_by": actor_id,
            "release_id": release_id,
            "previous_release_id": previous,
            "archive_path": str(archive_path),
            "archive_sha256": archive_sha,
            "file_count": len(source_hashes),
            "hash_mismatches": {},
            "safe_archive_entries": True,
            "live_application_switched": False,
            "rollback_contract": {
                "deploy": "extract verified release into a new version directory, run checks, then atomically switch the current symlink",
                "rollback": "atomically switch the current symlink to previous_release_id and restart services",
                "database": "run isolated migration rehearsal before deployment; never downgrade the live database without approved backup and change record",
            },
        }
        (release_dir / "manifest.json").write_text(
            json.dumps({"release_id": release_id, "archive_sha256": archive_sha, "files": source_hashes}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._write_evidence(evidence)
        return evidence

    def run_database_rehearsal(self, actor_id: str | None = None) -> dict[str, Any]:
        readiness = backup_restore_service.restore_drill_readiness()
        if not readiness["ready"]:
            raise PermissionError(readiness["reason"])
        admin_url = make_url(readiness["administrative_database_url"])
        database_name = f"future_migration_{uuid.uuid4().hex[:12]}"
        if not database_name.startswith("future_migration_"):
            raise ValueError("Unsafe migration rehearsal database name")
        environment = os.environ.copy()
        environment["DATABASE_URL"] = str(admin_url.set(database=database_name))
        if admin_url.password:
            environment["PGPASSWORD"] = admin_url.password
        alembic_config = Config(str(self.ROOT / "backend/alembic.ini"))
        scripts = ScriptDirectory.from_config(alembic_config)
        head = scripts.get_current_head()
        head_script = scripts.get_revision(head)
        previous = head_script.down_revision
        if not previous or isinstance(previous, tuple):
            raise ValueError("Migration head does not have a single reversible predecessor")
        created = False
        try:
            backup_restore_service._run_pg(
                "createdb.exe",
                ["--host", str(admin_url.host or "127.0.0.1"), "--port", str(admin_url.port or 5432),
                 "--username", str(admin_url.username or ""), database_name],
                environment, 120,
            )
            created = True
            self._alembic(environment, "upgrade", "head")
            upgraded_fingerprint = self._schema_fingerprint(environment["DATABASE_URL"])
            self._alembic(environment, "downgrade", str(previous))
            downgraded_revision = self._revision(environment["DATABASE_URL"])
            if downgraded_revision != str(previous):
                raise ValueError(f"Downgrade revision mismatch: expected {previous}, got {downgraded_revision}")
            self._alembic(environment, "upgrade", "head")
            final_revision = self._revision(environment["DATABASE_URL"])
            final_fingerprint = self._schema_fingerprint(environment["DATABASE_URL"])
            if final_revision != head or final_fingerprint != upgraded_fingerprint:
                raise ValueError("Re-upgraded schema does not match the initial head schema")
            evidence = {
                "rehearsal_id": f"db_rollback_{uuid.uuid4().hex[:10]}",
                "type": "database_migration_rollback",
                "status": "passed",
                "completed_at": self.now().isoformat(),
                "completed_by": actor_id,
                "head_revision": head,
                "downgraded_revision": str(previous),
                "final_revision": final_revision,
                "schema_fingerprint": final_fingerprint,
                "temporary_database": database_name,
                "temporary_database_removed": False,
                "live_database_modified": False,
            }
        finally:
            if created:
                backup_restore_service._run_pg(
                    "dropdb.exe",
                    ["--if-exists", "--force", "--host", str(admin_url.host or "127.0.0.1"),
                     "--port", str(admin_url.port or 5432), "--username", str(admin_url.username or ""), database_name],
                    environment, 120,
                )
        evidence["temporary_database_removed"] = True
        self._write_evidence(evidence)
        return evidence

    def latest_evidence(self) -> dict[str, Any] | None:
        self.EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
        files = sorted(self.EVIDENCE_ROOT.glob("*.json"))
        return json.loads(files[-1].read_text(encoding="utf-8")) if files else None

    def _source_hashes(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for declared in self.INCLUDE_ROOTS:
            source = self.ROOT / declared
            candidates = source.rglob("*") if source.is_dir() else [source]
            for item in candidates:
                if not item.is_file() or any(part in self.EXCLUDED_PARTS for part in item.relative_to(self.ROOT).parts):
                    continue
                relative = item.relative_to(self.ROOT).as_posix()
                hashes[relative] = self._sha256(item)
        if not hashes:
            raise ValueError("No application files were selected for the release bundle")
        return dict(sorted(hashes.items()))

    def _previous_release(self, current: str) -> str | None:
        releases = sorted(path.name for path in self.RELEASE_ROOT.glob("release_*") if path.is_dir() and path.name != current)
        return releases[-1] if releases else None

    def _write_evidence(self, evidence: dict[str, Any]) -> None:
        self.EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
        path = self.EVIDENCE_ROOT / f"{evidence['rehearsal_id']}.json"
        evidence["evidence_path"] = str(path)
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")

    def _alembic(self, environment: dict[str, str], command: str, revision: str) -> None:
        subprocess.run(
            [str(self.ROOT / "backend/venv/Scripts/python.exe"), "-m", "alembic",
             "-c", str(self.ROOT / "backend/alembic.ini"), command, revision],
            cwd=self.ROOT / "backend", env=environment, check=True,
            capture_output=True, text=True, timeout=900,
        )

    @staticmethod
    def _revision(database_url: str) -> str | None:
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        finally:
            engine.dispose()

    @staticmethod
    def _schema_fingerprint(database_url: str) -> str:
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            inspector = inspect(engine)
            schema = []
            for table in sorted(inspector.get_table_names()):
                columns = [
                    (item["name"], str(item["type"]), bool(item["nullable"]))
                    for item in inspector.get_columns(table)
                ]
                schema.append((table, columns))
        finally:
            engine.dispose()
        return hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


deployment_rollback_service = DeploymentRollbackService()
