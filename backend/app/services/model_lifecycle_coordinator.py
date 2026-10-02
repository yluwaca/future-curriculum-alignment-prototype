"""Atomic registry/runtime model activation, restart restoration, and rollback."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.model_loader import ModelLoadError
from app.models.model_registry import ModelRegistryEntry
from app.services.model_registry_service import ModelRegistryService
from app.services.model_service import ModelService


class ModelLifecycleCoordinator:
    def __init__(self, model_service: ModelService):
        self.model_service = model_service

    def prepare_entry(self, entry: ModelRegistryEntry) -> tuple[Dict[str, Any], Dict[str, Any]]:
        self._verify_artifact(entry)
        prepared = self.model_service.prepare_artifact_activation(
            entry.model_type,
            entry.artifact_path,
        )
        prepared["registry_entry_id"] = str(entry.entry_id)
        prepared["model_version"] = entry.model_version
        prepared["metrics"] = dict(entry.metrics or {})
        canary = self.model_service.canary_prediction(prepared, prepared["metrics"])
        return prepared, canary

    def promote(self, db: Session, entry_id: UUID, actor_id: str) -> ModelRegistryEntry:
        entry = (
            db.query(ModelRegistryEntry)
            .filter(ModelRegistryEntry.entry_id == entry_id)
            .with_for_update()
            .first()
        )
        if not entry:
            raise ValueError("Registry entry not found")
        registry = ModelRegistryService(db)
        can_promote, gates = registry.can_promote(entry)
        if not can_promote:
            failed = [name for name, result in gates.items() if not result["passed"]]
            raise ValueError(f"Promotion gates failed: {failed}")
        prepared, canary = self.prepare_entry(entry)
        previous = (
            db.query(ModelRegistryEntry)
            .filter(
                ModelRegistryEntry.model_type == entry.model_type,
                ModelRegistryEntry.is_active == 1,
                ModelRegistryEntry.entry_id != entry.entry_id,
            )
            .with_for_update()
            .all()
        )
        runtime_before = self.model_service.capture_serving_state(entry.model_type)
        now = datetime.now(timezone.utc)
        try:
            for old_entry in previous:
                old_entry.is_active = 0
                old_entry.lifecycle_state = "retired"
                old_entry.retired_at = now
            entry.lifecycle_state = "active"
            entry.is_active = 1
            entry.promoted_at = now
            entry.promoted_by = actor_id
            metrics = dict(entry.metrics or {})
            metrics["activation_evidence"] = {
                "action": "promotion",
                "activated_at": now.isoformat(),
                "canary": canary,
                "previous_active_versions": [item.model_version for item in previous],
            }
            entry.metrics = metrics
            db.flush()
            self.model_service.activate_prepared_artifact(prepared)
            db.commit()
            db.refresh(entry)
            return entry
        except Exception:
            db.rollback()
            self.model_service.restore_serving_state(runtime_before)
            raise

    def rollback(self, db: Session, model_type: str, actor_id: str) -> ModelRegistryEntry:
        current = (
            db.query(ModelRegistryEntry)
            .filter(
                ModelRegistryEntry.model_type == model_type,
                ModelRegistryEntry.is_active == 1,
                ModelRegistryEntry.lifecycle_state == "active",
            )
            .with_for_update()
            .first()
        )
        target = (
            db.query(ModelRegistryEntry)
            .filter(
                ModelRegistryEntry.model_type == model_type,
                ModelRegistryEntry.lifecycle_state == "retired",
                ModelRegistryEntry.entry_id != (current.entry_id if current else UUID(int=0)),
            )
            .order_by(ModelRegistryEntry.retired_at.desc())
            .with_for_update()
            .first()
        )
        if not target:
            raise ValueError(f"No retired model to rollback to for type '{model_type}'")
        prepared, canary = self.prepare_entry(target)
        runtime_before = self.model_service.capture_serving_state(model_type)
        now = datetime.now(timezone.utc)
        try:
            if current:
                current.is_active = 0
                current.lifecycle_state = "retired"
                current.retired_at = now
            target.is_active = 1
            target.lifecycle_state = "active"
            target.promoted_at = now
            target.promoted_by = actor_id
            metrics = dict(target.metrics or {})
            metrics["activation_evidence"] = {
                "action": "rollback",
                "activated_at": now.isoformat(),
                "canary": canary,
                "replaced_version": current.model_version if current else None,
            }
            target.metrics = metrics
            db.flush()
            self.model_service.activate_prepared_artifact(prepared)
            db.commit()
            db.refresh(target)
            return target
        except Exception:
            db.rollback()
            self.model_service.restore_serving_state(runtime_before)
            raise

    def restore_active_models(self, db: Session) -> Dict[str, Any]:
        """Fail closed, then load only registry-designated active artifacts."""
        self.model_service.clear_serving_models()
        result: Dict[str, Any] = {"status": "passed", "models": {}}
        for model_type in ("xgboost", "lstm"):
            entries = (
                db.query(ModelRegistryEntry)
                .filter(
                    ModelRegistryEntry.model_type == model_type,
                    ModelRegistryEntry.is_active == 1,
                    ModelRegistryEntry.lifecycle_state == "active",
                )
                .all()
            )
            if not entries:
                result["models"][model_type] = {"status": "no_active_registry_model"}
                continue
            if len(entries) > 1:
                result["status"] = "failed"
                result["models"][model_type] = {
                    "status": "multiple_active_registry_models",
                    "count": len(entries),
                }
                continue
            entry = entries[0]
            try:
                prepared, canary = self.prepare_entry(entry)
                self.model_service.activate_prepared_artifact(prepared)
                result["models"][model_type] = {
                    "status": "restored",
                    "entry_id": str(entry.entry_id),
                    "model_version": entry.model_version,
                    "canary": canary,
                }
            except Exception as exc:
                result["status"] = "failed"
                result["models"][model_type] = {
                    "status": "restore_failed",
                    "entry_id": str(entry.entry_id),
                    "reason": str(exc),
                }
        return result

    @staticmethod
    def _verify_artifact(entry: ModelRegistryEntry) -> None:
        if not entry.artifact_checksum:
            raise ModelLoadError("Registry artifact has no checksum")
        if not entry.artifact_path or not os.path.isfile(entry.artifact_path):
            raise ModelLoadError("Registry artifact is missing")
        digest = hashlib.sha256()
        with open(entry.artifact_path, "rb") as artifact:
            for block in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != entry.artifact_checksum:
            raise ModelLoadError("Registry artifact checksum does not match")
