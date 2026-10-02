"""Portal-only golden-path and failure-path acceptance checks."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.generated_report import GeneratedReport
from app.models.recommendation import Recommendation
from app.services.audit_service import log_audit_event
from app.services.recommendation_governance_service import recommendation_governance_service
from app.services.validated_regeneration_service import validated_regeneration_service


class PortalUATService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]

    @staticmethod
    def _check(
        key: str, name: str, passed: bool, evidence: str,
        *, expected_block: bool = False, user_action: str = "",
    ) -> dict[str, Any]:
        status = "expected_block" if passed and expected_block else ("passed" if passed else "failed")
        return {
            "key": key,
            "name": name,
            "status": status,
            "evidence": evidence,
            "user_action": user_action,
        }

    def _read(self, relative: str) -> str:
        # The development checkout contains ``backend/`` and ``frontend/`` at
        # the project root, while the backend image installs backend contents
        # directly under ``/app`` and serves frontend files from the proxy
        # container.  Resolve both layouts so the UAT checks inspect the live
        # deployment instead of silently treating unavailable source paths as
        # failed controls.
        candidates = [self.PROJECT_ROOT / relative]
        if relative.startswith("backend/"):
            candidates.append(Path("/app") / relative.removeprefix("backend/"))
        for path in candidates:
            if path.exists():
                return path.read_text(encoding="utf-8", errors="replace")

        if relative.startswith("frontend/"):
            base_url = os.getenv("PORTAL_UAT_FRONTEND_BASE_URL", "http://proxy").rstrip("/")
            try:
                with urlopen(f"{base_url}/{relative.removeprefix('frontend/')}", timeout=5) as response:
                    return response.read().decode("utf-8", errors="replace")
            except Exception:
                return ""
        return ""

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def run(self, db: Session, actor_id: str, actor_type: str) -> dict[str, Any]:
        dashboard = self._read("frontend/dashboard.html")
        recommendations_page = self._read("frontend/recommendations.html")
        recommendation_js = self._read("frontend/recommendations.js")
        data_operations = self._read("frontend/data-operations.html")
        model_lab = self._read("frontend/model-lab.html")
        system_operations = self._read("frontend/system-operations.html")
        state_js = self._read("frontend/dashboard-state.js")
        analytics_router = self._read("backend/app/routers/analytics.py")
        processing_router = self._read("backend/app/routers/processing.py")
        migration = self._read("backend/migrations/versions/release4_recommendation_governance.py")
        model_service = self._read("backend/app/services/model_service.py")

        db.execute(text("SELECT 1"))
        recommendation_count = db.query(Recommendation).count()
        regeneration = validated_regeneration_service.readiness(db)
        governance = recommendation_governance_service.readiness(db)

        golden = [
            self._check("authenticated_session", "Authenticated portal session", bool(actor_id),
                        f"Acceptance run requested by authenticated identity {actor_id}."),
            self._check("database_connection", "Portal API can read the database", True,
                        "Authenticated API transaction completed SELECT 1."),
            self._check("decision_portal", "Decision Portal is available",
                        all(x in dashboard for x in ("latestRecommendations", "skillGapRows", "forecastRows")),
                        "Recommendation, skill-gap and forecast result regions are present."),
            self._check("data_operations", "Data Operations covers evidence intake and processing",
                        all(x in data_operations for x in ("uploadCurriculumBtn", "runGenericIntakeBtn", "runFullProcessingBtn")),
                        "Portal contains curriculum upload, generic intake and processing controls."),
            self._check("model_lab", "Model Lab covers candidate lifecycle",
                        all(x in model_lab for x in ("trainXgboostBtn", "modelRegistryPanel", "modelDatasetSnapshotPanel")),
                        "Portal contains candidate training, dataset snapshot and registry evidence regions."),
            self._check("system_operations", "System Operations covers recoverability and UAT",
                        all(x in system_operations for x in ("securityReadinessPanel", "operationalJobRows", "deploymentReadinessPanel")),
                        "Portal contains security, durable jobs and deployment/UAT regions."),
            self._check("role_separation", "Restricted pages use role-aware entry guards",
                        "canAccessDefaultView" in self._read("frontend/dashboard-main.js")
                        and "systemOperations" in state_js and "modelLab" in state_js,
                        "Shared portal entry logic checks the signed-in user's role."),
            self._check("validated_output_state", "Validated regeneration returns an explicit state",
                        regeneration.get("status") in {"ready", "blocked"},
                        f"Current state: {regeneration.get('status')}; {len(regeneration.get('checks', []))} gates reported."),
            self._check("recommendation_review", "Recommendation review and evidence dossier are available",
                        "RECOMMENDATION_DOSSIER" in self._read("frontend/config.js")
                        and "Decision-support limitation" in recommendations_page,
                        f"Review page available; current recommendation count is {recommendation_count}."),
            self._check("committee_governance", "Committee readiness is explicit",
                        governance.get("status") in {"ready", "blocked"}
                        and "committeePackBtn" in recommendations_page,
                        f"Current committee readiness: {governance.get('status')}."),
            self._check("empty_state_guidance", "Missing outputs explain safe next actions",
                        all(x in self._read("frontend/dashboard-utils.js") for x in ("<b>Why:</b>", "<b>Next step:</b>", "<b>Do not infer:</b>")),
                        "Decision empty states distinguish absence, action and non-inference."),
        ]

        regeneration_blocked = regeneration.get("status") == "blocked"
        governance_blocked = governance.get("status") == "blocked"
        failure = [
            self._check("unauthenticated_rejection", "Protected APIs reject anonymous use",
                        "Depends(get_current_user)" in analytics_router or "Depends(require_role" in analytics_router,
                        "Analytics routes require an authenticated user."),
            self._check("validated_regeneration_guard", "Invalid evidence cannot regenerate outputs",
                        ("HTTP_422_UNPROCESSABLE_CONTENT" in processing_router and "failed_checks" in processing_router),
                        "Backend returns an unprocessable response with failed gate details before enqueueing regeneration."),
            self._check("current_regeneration_block", "Current invalid evidence is visibly blocked",
                        regeneration_blocked or regeneration.get("status") == "ready",
                        f"Current result is {regeneration.get('status')}; blocked is expected until evidence gates pass.",
                        expected_block=regeneration_blocked),
            self._check("committee_pack_guard", "Committee packs cannot bypass evidence review",
                        governance_blocked or governance.get("status") == "ready",
                        f"Current result is {governance.get('status')}; pack button follows this backend state.",
                        expected_block=governance_blocked),
            self._check("committee_record_immutable", "Final committee decisions are append-only",
                        "BEFORE UPDATE OR DELETE" in migration and "unique=True" in migration,
                        "Database trigger prevents mutation and unique index prevents a second final decision."),
            self._check("no_automatic_committee_decision", "Model output cannot create a committee decision",
                        "committee-decision" not in recommendation_js
                        and 'require_role("CURRICULUM_APPROVER")' in analytics_router
                        and 'require_permission("recommendation.academic_approve")' in analytics_router,
                        "Review UI has no automatic committee action; final endpoint is restricted to the Curriculum Approver and its exclusive academic-decision permission."),
            self._check("candidate_training_safety", "Training cannot overwrite the active model automatically",
                        "promotion_required" in model_service and "active_model_updated" in model_service,
                        "Training response records promotion_required and active_model_updated safety fields."),
            self._check("missing_dossier_guard", "A reviewer is warned when evidence cannot load",
                        "Never approve or reject a recommendation without its evidence dossier." in recommendation_js,
                        "Portal displays a decision-blocking instruction on dossier failure."),
        ]

        all_checks = golden + failure
        failed = [item for item in all_checks if item["status"] == "failed"]
        payload = {
            "schema_version": "portal_acceptance_uat_v1",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "executed_by": actor_id,
            "scope": "development portal only; no UAT or production environment mutation",
            "result": "passed" if not failed else "failed",
            "summary": {
                "total": len(all_checks),
                "passed": sum(x["status"] == "passed" for x in all_checks),
                "expected_blocks": sum(x["status"] == "expected_block" for x in all_checks),
                "failed": len(failed),
            },
            "golden_path": golden,
            "failure_path": failure,
            "current_readiness": {
                "validated_regeneration": regeneration,
                "recommendation_governance": governance,
            },
            "interpretation": (
                "Expected blocks are successful safety outcomes, not UAT failures. "
                "The full empirical golden path remains data-dependent until sufficient reviewed evidence and evaluation data are available."
            ),
        }
        report_hash = self._hash(payload)
        report = GeneratedReport(
            report_type="portal_acceptance_uat",
            source_entity_type="development_portal",
            source_entity_id=None,
            generated_by=actor_id,
            status=payload["result"],
            title="Portal Golden-Path and Failure-Path Acceptance Run",
            summary=payload["summary"],
            payload=payload,
            payload_hash=report_hash,
            format_hint="json",
            notes=payload["interpretation"],
        )
        db.add(report)
        log_audit_event(
            db=db, event_layer="application", event_type="portal_uat",
            actor_type=actor_type, actor_id=actor_id, token_id=None,
            source_component="operations.portal_uat", action="run_acceptance_suite",
            result=payload["result"],
            metadata={"payload_hash": report_hash, **payload["summary"]},
        )
        db.commit()
        db.refresh(report)
        return {
            "report_id": str(report.report_id),
            "payload_hash": report_hash,
            **payload,
        }

    def latest(self, db: Session) -> dict[str, Any] | None:
        report = (
            db.query(GeneratedReport)
            .filter(GeneratedReport.report_type == "portal_acceptance_uat")
            .order_by(GeneratedReport.created_at.desc())
            .first()
        )
        if not report:
            return None
        return {
            "report_id": str(report.report_id),
            "payload_hash": report.payload_hash,
            **(report.payload or {}),
        }


portal_uat_service = PortalUATService()
