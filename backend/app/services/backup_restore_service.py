"""Encrypted PostgreSQL/file/model backup and non-destructive restore verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings


class BackupRestoreService:
    MAGIC = b"FUTUREBK1"
    BACKUP_ROOT = Path("data/backups/snapshots")
    QUARANTINE_ROOT = Path("data/backups/quarantine")
    COUNT_TABLES = (
        "tenant", "jus01_systemidentity", "data_source", "ingestion_job",
        "curriculum_document", "curriculum_document_version", "document_chunk",
        "skill", "recommendation", "pipeline_run", "operational_job",
    )

    def create_backup(self, actor_id: str | None = None) -> Dict[str, Any]:
        self.BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        backup_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        target = self.BACKUP_ROOT / backup_id
        target.mkdir(parents=True, exist_ok=False)

        with tempfile.TemporaryDirectory(prefix="future-backup-") as temporary:
            work = Path(temporary)
            database_dump = work / "database.dump"
            files_archive = work / "files-and-models.tar.gz"
            self._dump_database(database_dump)
            archive_summary = self._archive_files(files_archive)

            encrypted_database = target / "database.dump.enc"
            encrypted_files = target / "files-and-models.tar.gz.enc"
            self._encrypt_file(database_dump, encrypted_database)
            self._encrypt_file(files_archive, encrypted_files)

        manifest = {
            "backup_id": backup_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": actor_id,
            "backup_mode": "encrypted_database_files_models",
            "encryption": "AES-256-GCM",
            "database_counts": self._database_counts(settings.DATABASE_URL),
            "components": {
                "database": self._component_manifest(encrypted_database),
                "files_and_models": {
                    **self._component_manifest(encrypted_files),
                    **archive_summary,
                },
            },
        }
        manifest_path = target / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        verification = self.verify_backup(manifest_path)
        manifest["verification"] = verification
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return {**manifest, "manifest_path": str(manifest_path)}

    def retention_policy(self) -> Dict[str, int]:
        return {
            "daily": max(1, int(os.getenv("FUTURE_BACKUP_RETENTION_DAILY", "7"))),
            "weekly": max(1, int(os.getenv("FUTURE_BACKUP_RETENTION_WEEKLY", "4"))),
            "monthly": max(1, int(os.getenv("FUTURE_BACKUP_RETENTION_MONTHLY", "6"))),
            "quarantine_days": max(1, int(os.getenv("FUTURE_BACKUP_QUARANTINE_DAYS", "30"))),
        }

    def retention_plan(self) -> Dict[str, Any]:
        manifests = self._manifests()
        policy = self.retention_policy()
        records = []
        for path in manifests:
            payload = json.loads(path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
            records.append((path, payload, created))
        records.sort(key=lambda item: item[2], reverse=True)
        keep: set[Path] = set()
        now = datetime.now(timezone.utc)
        daily: set[str] = set()
        weekly: set[str] = set()
        monthly: set[str] = set()
        for path, _payload, created in records:
            age = now - created
            day_key = created.date().isoformat()
            week_key = f"{created.isocalendar().year}-W{created.isocalendar().week:02d}"
            month_key = created.strftime("%Y-%m")
            if age <= timedelta(days=policy["daily"]) and len(daily) < policy["daily"] and day_key not in daily:
                daily.add(day_key)
                keep.add(path)
            if age <= timedelta(weeks=policy["weekly"]) and len(weekly) < policy["weekly"] and week_key not in weekly:
                weekly.add(week_key)
                keep.add(path)
            if len(monthly) < policy["monthly"] and month_key not in monthly:
                monthly.add(month_key)
                keep.add(path)
        if records:
            keep.add(records[0][0])
        return {
            "policy": policy,
            "backup_count": len(records),
            "keep": [item[1]["backup_id"] for item in records if item[0] in keep],
            "quarantine": [item[1]["backup_id"] for item in records if item[0] not in keep],
            "destructive_delete": False,
        }

    def apply_retention(self, actor_id: str | None = None) -> Dict[str, Any]:
        plan = self.retention_plan()
        if not plan["quarantine"]:
            return {**plan, "moved": [], "applied_by": actor_id}
        batch = self.QUARANTINE_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        batch.mkdir(parents=True, exist_ok=True)
        moved = []
        root = self.BACKUP_ROOT.resolve()
        for backup_id in plan["quarantine"]:
            source = (self.BACKUP_ROOT / backup_id).resolve()
            if source.parent != root or source.name != backup_id or not (source / "manifest.json").is_file():
                raise ValueError(f"Refusing to move unmanaged backup path: {backup_id}")
            destination = batch / backup_id
            if destination.exists():
                raise FileExistsError(f"Retention destination already exists: {destination}")
            shutil.move(str(source), str(destination))
            moved.append(backup_id)
        evidence = {
            **plan,
            "moved": moved,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "applied_by": actor_id,
            "quarantine_batch": str(batch),
            "recoverable": True,
        }
        (batch / "retention-evidence.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        return evidence

    def run_isolated_restore_drill(self, manifest_path: str | Path | None = None, actor_id: str | None = None) -> Dict[str, Any]:
        path = Path(manifest_path) if manifest_path else self._latest_manifest()
        if not path:
            raise FileNotFoundError("No encrypted backup is available for a restore drill")
        path = path.resolve()
        root = self.BACKUP_ROOT.resolve()
        if path.parent.parent != root or path.name != "manifest.json":
            raise ValueError("Restore drill manifest is outside the managed backup directory")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        verification = self.verify_backup(path)
        drill_id = f"restore_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        database_name = f"future_restore_{uuid.uuid4().hex[:12]}"
        if not database_name.startswith("future_restore_"):
            raise ValueError("Unsafe restore database name")
        readiness = self.restore_drill_readiness()
        if not readiness["ready"]:
            raise PermissionError(readiness["reason"])
        url = make_url(readiness["administrative_database_url"])
        environment = self._pg_environment(url)
        created = False
        try:
            self._run_pg(
                "createdb.exe",
                ["--host", str(url.host or "127.0.0.1"), "--port", str(url.port or 5432),
                 "--username", str(url.username or ""), database_name],
                environment, 120,
            )
            created = True
            with tempfile.TemporaryDirectory(prefix="future-isolated-restore-") as temporary:
                work = Path(temporary)
                database_dump = work / "database.dump"
                files_archive = work / "files-and-models.tar.gz"
                self._decrypt_file(path.parent / manifest["components"]["database"]["filename"], database_dump)
                self._decrypt_file(path.parent / manifest["components"]["files_and_models"]["filename"], files_archive)
                self._run_pg(
                    "pg_restore.exe",
                    ["--no-owner", "--no-privileges", "--exit-on-error",
                     "--host", str(url.host or "127.0.0.1"), "--port", str(url.port or 5432),
                     "--username", str(url.username or ""), "--dbname", database_name, str(database_dump)],
                    environment, 900,
                )
                restored_url = url.set(database=database_name)
                restored_counts = self._database_counts(str(restored_url))
                expected_counts = manifest.get("database_counts") or {}
                count_mismatches = {
                    key: {"expected": value, "restored": restored_counts.get(key)}
                    for key, value in expected_counts.items()
                    if restored_counts.get(key) != value
                }
                with tarfile.open(files_archive, "r:gz") as archive:
                    members = [item for item in archive.getmembers() if item.isfile()]
                    restored_file_count = len(members)
                    restored_source_bytes = sum(item.size for item in members)
                expected_files = manifest["components"]["files_and_models"].get("source_file_count")
                expected_bytes = manifest["components"]["files_and_models"].get("source_bytes")
                archive_matches = (
                    (expected_files is None or expected_files == restored_file_count)
                    and (expected_bytes is None or expected_bytes == restored_source_bytes)
                )
                if count_mismatches or not archive_matches:
                    raise ValueError(f"Restore drill validation mismatch: counts={count_mismatches}, archive={archive_matches}")
            result = {
                "drill_id": drill_id,
                "status": "passed",
                "backup_id": manifest["backup_id"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "completed_by": actor_id,
                "temporary_database": database_name,
                "temporary_database_removed": False,
                "live_database_modified": False,
                "database_counts": restored_counts,
                "count_mismatches": {},
                "archive_file_count": restored_file_count,
                "archive_source_bytes": restored_source_bytes,
                "archive_matches_manifest": True,
                "pre_restore_verification": verification,
            }
        finally:
            if created:
                self._run_pg(
                    "dropdb.exe",
                    ["--if-exists", "--force", "--host", str(url.host or "127.0.0.1"),
                     "--port", str(url.port or 5432), "--username", str(url.username or ""), database_name],
                    environment, 120,
                )
        result["temporary_database_removed"] = True
        evidence_path = path.parent / f"{drill_id}.json"
        result["evidence_path"] = str(evidence_path)
        evidence_path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return result

    def restore_drill_readiness(self) -> Dict[str, Any]:
        configured = os.getenv("FUTURE_RESTORE_ADMIN_DATABASE_URL", "").strip()
        candidate = configured or settings.DATABASE_URL
        engine = create_engine(candidate, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                current_user, can_create = connection.execute(
                    text(
                        "SELECT current_user, "
                        "COALESCE((SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user), false)"
                    )
                ).one()
        finally:
            engine.dispose()
        ready = bool(can_create)
        return {
            "ready": ready,
            "database_role": current_user,
            "can_create_isolated_database": ready,
            "admin_connection_configured": bool(configured),
            "reason": (
                "Restore drill database authority is available."
                if ready
                else "Configure FUTURE_RESTORE_ADMIN_DATABASE_URL with a managed PostgreSQL role that has CREATEDB. "
                     "The application role remains least-privileged and must not be elevated."
            ),
            # Internal-only field consumed by the service and removed at the API.
            "administrative_database_url": candidate,
        }

    def verify_backup(self, manifest_path: str | Path) -> Dict[str, Any]:
        path = Path(manifest_path).resolve()
        root = self.BACKUP_ROOT.resolve()
        if path.parent.parent != root or path.name != "manifest.json":
            raise ValueError("Backup manifest is outside the managed backup directory")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        target = path.parent
        database_encrypted = target / manifest["components"]["database"]["filename"]
        files_encrypted = target / manifest["components"]["files_and_models"]["filename"]
        self._verify_component(database_encrypted, manifest["components"]["database"])
        self._verify_component(files_encrypted, manifest["components"]["files_and_models"])

        with tempfile.TemporaryDirectory(prefix="future-restore-verify-") as temporary:
            work = Path(temporary)
            database_dump = work / "database.dump"
            files_archive = work / "files-and-models.tar.gz"
            self._decrypt_file(database_encrypted, database_dump)
            self._decrypt_file(files_encrypted, files_archive)
            restore = subprocess.run(
                [str(self._pg_tool("pg_restore.exe")), "--list", str(database_dump)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            with tarfile.open(files_archive, "r:gz") as archive:
                members = archive.getmembers()
                unsafe = [
                    item.name
                    for item in members
                    if Path(item.name).is_absolute() or ".." in Path(item.name).parts
                ]
                if unsafe:
                    raise ValueError(f"Unsafe archive members found: {unsafe[:5]}")

        return {
            "status": "passed",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "database_restore_list_entries": len(
                [line for line in restore.stdout.splitlines() if line and not line.startswith(";")]
            ),
            "archive_members": len(members),
            "live_database_modified": False,
        }

    def latest_summary(self) -> Dict[str, Any]:
        self.BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        manifests = self._manifests()
        latest = manifests[-1] if manifests else None
        drills = sorted(self.BACKUP_ROOT.glob("*/restore_*.json"))
        return {
            "backup_mode": "encrypted_database_files_models",
            "backup_count": len(manifests),
            "latest_manifest": str(latest) if latest else None,
            "latest": json.loads(latest.read_text(encoding="utf-8")) if latest else None,
            "retention": self.retention_plan(),
            "restore_drill_count": len(drills),
            "latest_restore_drill": json.loads(drills[-1].read_text(encoding="utf-8")) if drills else None,
        }

    def _manifests(self) -> list[Path]:
        self.BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        return sorted(self.BACKUP_ROOT.glob("*/manifest.json"))

    def _latest_manifest(self) -> Path | None:
        manifests = self._manifests()
        return manifests[-1] if manifests else None

    @staticmethod
    def _database_counts(database_url: str) -> Dict[str, int]:
        engine = create_engine(database_url, pool_pre_ping=True)
        counts: Dict[str, int] = {}
        try:
            with engine.connect() as connection:
                for table in BackupRestoreService.COUNT_TABLES:
                    exists = connection.execute(
                        text("SELECT to_regclass(:table_name) IS NOT NULL"),
                        {"table_name": f"public.{table}"},
                    ).scalar()
                    if exists:
                        counts[table] = int(connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0)
        finally:
            engine.dispose()
        return counts

    @staticmethod
    def _pg_environment(url) -> Dict[str, str]:
        environment = os.environ.copy()
        if url.password:
            environment["PGPASSWORD"] = url.password
        return environment

    def _run_pg(self, tool: str, arguments: list[str], environment: Dict[str, str], timeout: int):
        return subprocess.run(
            [str(self._pg_tool(tool)), *arguments],
            check=True, capture_output=True, text=True, env=environment, timeout=timeout,
        )

    def _dump_database(self, destination: Path) -> None:
        url = make_url(settings.DATABASE_URL)
        environment = os.environ.copy()
        if url.password:
            environment["PGPASSWORD"] = url.password
        command = [
            str(self._pg_tool("pg_dump.exe")),
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(destination),
            "--host",
            str(url.host or "127.0.0.1"),
            "--port",
            str(url.port or 5432),
            "--username",
            str(url.username or ""),
            str(url.database or ""),
        ]
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            timeout=600,
        )

    def _archive_files(self, destination: Path) -> Dict[str, Any]:
        roots: Iterable[tuple[Path, str]] = (
            (Path("data/raw"), "data/raw"),
            (Path("data/generic_intake"), "data/generic_intake"),
            (Path(settings.MODEL_STORAGE_PATH), "models"),
        )
        file_count = 0
        source_bytes = 0
        with tarfile.open(destination, "w:gz") as archive:
            for root, archive_root in roots:
                if not root.exists():
                    continue
                for item in root.rglob("*"):
                    if not item.is_file() or "_staging" in item.parts:
                        continue
                    relative = item.relative_to(root)
                    archive.add(item, arcname=str(Path(archive_root) / relative), recursive=False)
                    file_count += 1
                    source_bytes += item.stat().st_size
        return {"source_file_count": file_count, "source_bytes": source_bytes}

    def _key(self) -> bytes:
        return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()

    def _encrypt_file(self, source: Path, destination: Path) -> None:
        nonce = os.urandom(12)
        encryptor = Cipher(algorithms.AES(self._key()), modes.GCM(nonce)).encryptor()
        with source.open("rb") as reader, destination.open("wb") as writer:
            writer.write(self.MAGIC)
            writer.write(nonce)
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(encryptor.update(chunk))
            encryptor.finalize()
            writer.write(encryptor.tag)

    def _decrypt_file(self, source: Path, destination: Path) -> None:
        size = source.stat().st_size
        with source.open("rb") as reader:
            if reader.read(len(self.MAGIC)) != self.MAGIC:
                raise ValueError("Backup encryption header is invalid")
            nonce = reader.read(12)
            reader.seek(size - 16)
            tag = reader.read(16)
            reader.seek(len(self.MAGIC) + 12)
            remaining = size - len(self.MAGIC) - 12 - 16
            decryptor = Cipher(algorithms.AES(self._key()), modes.GCM(nonce, tag)).decryptor()
            with destination.open("wb") as writer:
                while remaining:
                    chunk = reader.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Encrypted backup is truncated")
                    writer.write(decryptor.update(chunk))
                    remaining -= len(chunk)
                decryptor.finalize()

    @staticmethod
    def _component_manifest(path: Path) -> Dict[str, Any]:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
        }

    @staticmethod
    def _verify_component(path: Path, expected: Dict[str, Any]) -> None:
        actual = BackupRestoreService._component_manifest(path)
        if actual["sha256"] != expected["sha256"] or actual["size_bytes"] != expected["size_bytes"]:
            raise ValueError(f"Backup component checksum mismatch: {path.name}")

    @staticmethod
    def _pg_tool(name: str) -> Path:
        located = shutil.which(name)
        if located:
            return Path(located)
        candidate = Path("C:/Program Files/PostgreSQL/17/bin") / name
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"Required PostgreSQL tool not found: {name}")


backup_restore_service = BackupRestoreService()
