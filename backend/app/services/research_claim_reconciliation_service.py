"""Reconcile accepted-paper claims with reproducible system evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.alignment_expert_label import AlignmentExpertLabel
from app.models.curriculum_document import CurriculumDocument
from app.models.curriculum_module import CurriculumModule
from app.models.document_chunk import DocumentChunk
from app.models.generated_report import GeneratedReport
from app.models.job_posting import JobPosting
from app.models.label_dataset_snapshot import LabelDatasetSnapshot
from app.models.labour_market_signal import LabourMarketSignal
from app.models.model_registry import ModelRegistryEntry
from app.models.recommendation_committee_decision import RecommendationCommitteeDecision
from app.models.skill import Skill
from app.models.skill_mapping import SkillMapping
from app.services.model_evaluation_service import payload_hash


class ResearchClaimReconciliationService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    PAPER_PATH = PROJECT_ROOT / "conference/paper.pdf"

    def reconcile(self, db: Session, tenant_id: UUID) -> dict[str, Any]:
        counts = self._counts(db, tenant_id)
        active_models = db.query(ModelRegistryEntry).filter(ModelRegistryEntry.is_active == 1).all()
        active_by_type = {item.model_type: item for item in active_models}
        xgb = active_by_type.get("xgboost")
        lstm = active_by_type.get("lstm")
        locked_snapshot = (
            db.query(LabelDatasetSnapshot)
            .filter(LabelDatasetSnapshot.lifecycle_state == "approved_locked")
            .order_by(LabelDatasetSnapshot.locked_at.desc())
            .first()
        )

        claims = [
            self.claim("C01", "pp. 1-3", "The framework implements a modular Input-Processing-Output pipeline.",
                       "supported", "Implemented portal ingestion, processing, decision outputs, lineage and operational workflows.",
                       ["frontend/data-operations.html", "backend/app/services/processing_orchestrator_service.py", "backend/app/services/pipeline_orchestrator_service.py"],
                       "Retain, but describe it as the implemented prototype architecture."),
            self.claim("C02", "pp. 1, 2 and 4", "The system continuously ingests real-time labour-market APIs.",
                       "partially_supported", f"The portal and durable ingestion jobs exist; current evidence contains {counts['labour_market_signals']} canonical signals. Continuous unattended external API operation has not been demonstrated.",
                       ["backend/app/routers/ingestion.py", "backend/app/services/operational_job_service.py"],
                       "Use 'supports authorised API and scheduled ingestion' rather than claiming continuous real-time operation."),
            self.claim("C03", "pp. 1-3", "Extracted skills are harmonised to ESCO and South African OFO taxonomies.",
                       "supported", f"The database contains {counts['skills']} canonical skills and {counts['skill_mappings']} evidence mappings with ESCO/OFO services and lineage.",
                       ["backend/app/services/skill_harmonisation_service.py", "backend/app/models/esco_skill.py", "backend/app/models/ofo_taxonomy.py"],
                       "Retain as an implemented capability; report live counts only from a locked evidence snapshot."),
            self.claim("C04", "pp. 1, 3-6", "XGBoost achieved F1=0.84 and ROC-AUC=0.87 on N=90.",
                       "reproducibility_blocked" if not xgb else "evidence_available",
                       self._model_evidence(xgb, "No active registry-approved XGBoost model currently reproduces these values. Independent expert labels and a locked training snapshot are still required."),
                       ["backend/app/models/model_registry.py", "backend/app/models/label_dataset_snapshot.py"],
                       "Present the published values only as preliminary/simulated pilot results unless a registered candidate reproduces them."),
            self.claim("C05", "pp. 3-4", "The LSTM achieved RMSE=0.11 and MAPE=13.2% against ARIMA.",
                       "reproducibility_blocked" if not lstm else "evidence_available",
                       self._model_evidence(lstm, "No active registry-approved LSTM model currently reproduces these forecast metrics."),
                       ["backend/app/models/model_registry.py", "backend/app/services/model_service.py"],
                       "Label as preliminary pilot evidence; do not describe it as current portal performance."),
            self.claim("C06", "p. 3", "Evaluation used approximately 450 curriculum records and 2,000 unique job postings.",
                       "historical_claim_unlocked",
                       f"Current tenant-visible evidence: {counts['curriculum_documents']} documents, {counts['curriculum_modules']} modules, {counts['job_postings']} job postings. The paper dataset is not stored as a locked reproducible snapshot.",
                       ["backend/app/models/curriculum_document.py", "backend/app/models/job_posting.py"],
                       "State these as the preliminary paper dataset and explicitly distinguish them from current operational database counts."),
            self.claim("C07", "pp. 1, 4-6", "The intervention reduced the curriculum-labour gap by 38.2%.",
                       "simulation_only", "The paper itself identifies a simulated sandbox intervention; no real curriculum-change outcome or causal deployment evidence is registered.",
                       ["paper Section V-B", "docs/FUTURE_operational_benchmark.md"],
                       "Use 'a simulated sandbox scenario produced a 38.2% reduction'; remove causal or operational outcome wording."),
            self.claim("C08", "p. 2", "Cosine similarity >0.75 is a validated binary alignment threshold.",
                       "not_validated", "No sensitivity analysis or expert-labelled validation currently supports 0.75. The operational design now preserves continuous evidence scores and requires expert labels for supervised classification.",
                       ["backend/app/models/alignment_expert_label.py", "backend/app/services/alignment_labelling_service.py"],
                       "Remove the implication that 0.75 is validated; report sensitivity analysis or describe it as a provisional pilot threshold."),
            self.claim("C09", "pp. 1, 3-5", "TreeSHAP provides XGBoost model explanations.",
                       "partially_supported", "TreeSHAP code and promotion gates exist, but explanation evidence is meaningful only for a trained registered candidate; no active candidate currently supports the paper figures.",
                       ["backend/app/services/model_service.py", "backend/app/services/model_evidence_service.py"],
                       "Describe explanation mechanisms as implemented architecture and figures as illustrative unless tied to a registered model artifact."),
            self.claim("C10", "pp. 2-3", "Demographic parity <=0.1 demonstrates fairness using geographic/socioeconomic proxies.",
                       "claim_must_change", "The operational service explicitly treats faculty/department/geographic group checks as contextual subgroup monitoring, not demographic fairness or protected-attribute evidence.",
                       ["backend/app/services/fairness_audit_service.py", "backend/app/services/model_evidence_service.py"],
                       "Replace 'demographic parity/fairness validated' with 'contextual subgroup monitoring'; state that protected-attribute fairness was not assessed."),
            self.claim("C11", "p. 5", "t-test, Pearson correlation and ANOVA results establish statistically significant efficacy/generalisation.",
                       "reproducibility_blocked", "No immutable analysis dataset, executable statistical run or content-hashed result package currently reproduces t(47)=3.41, r=0.67 or F(2,45)=1.23.",
                       ["backend/app/models/generated_report.py", "backend/app/models/label_dataset_snapshot.py"],
                       "Keep only as preliminary pilot analysis with simulation and sample limitations, or regenerate from a locked analysis package."),
            self.claim("C12", "p. 3", "Automatic retraining triggers deploy models within 48 hours of threshold breaches.",
                       "partially_supported", "Durable candidate-only training, evaluation, promotion and rollback are implemented. Automatic production promotion is deliberately prohibited and no 48-hour operational SLA has been demonstrated.",
                       ["backend/app/services/operational_job_service.py", "backend/app/services/model_lifecycle_coordinator.py"],
                       "State that triggers may queue candidate evaluation; human approval and promotion are mandatory."),
            self.claim("C13", "pp. 3 and 5", "Human-in-the-loop governance preserves academic decision authority.",
                       "supported", f"Expert review, immutable evidence reports and final committee decisions are separated; {counts['committee_decisions']} committee decision(s) are currently recorded.",
                       ["backend/app/services/recommendation_governance_service.py", "backend/app/models/recommendation_committee_decision.py"],
                       "Retain and describe the explicit separation between model recommendation, expert review and committee authority."),
            self.claim("C14", "pp. 1-3 and 6", "The system is privacy-preserving and POPIA-aligned.",
                       "partially_supported", "RBAC, tenant isolation, managed-secret/TLS controls, audit trails and least-privilege boundaries are implemented. These controls do not constitute legal POPIA certification.",
                       ["backend/app/core/tenant_scope.py", "backend/app/services/security_operations_service.py"],
                       "Use 'designed with POPIA-aligned technical controls'; avoid claiming certified compliance."),
            self.claim("C15", "pp. 5-6", "The framework directly enhances graduate employability or placement outcomes.",
                       "future_outcome", "No longitudinal graduate placement outcome has been measured. The system provides curriculum-labour decision support only.",
                       ["paper Section V-E", "docs/FUTURE_operational_benchmark.md"],
                       "Use prospective language: may support future curriculum relevance; longitudinal employability validation remains future work."),
            self.claim("C16", "pp. 3 and 5-6", "Results generalise across institutions or South African universities.",
                       "external_validation_required", "Current deployment and evidence are CPUT-centred and tenant architecture alone does not establish empirical transferability.",
                       ["backend/app/models/tenant.py", "docs/FUTURE_operational_benchmark.md"],
                       "State single-institution scope prominently and retain cross-institutional validation as future work."),
        ]
        status_counts = dict(Counter(item["status"] for item in claims))
        blocking = [item for item in claims if item["status"] not in {"supported", "evidence_available"}]
        reviewer_actions = [
            {"reviewer": 1, "action": "State the single-institution/small-sample limitation and do not claim external validity.", "status": "required"},
            {"reviewer": 1, "action": "Replace the unvalidated 0.75 binary threshold claim or add sensitivity analysis.", "status": "required"},
            {"reviewer": 1, "action": "Describe 38.2% strictly as a simulated sandbox result and remove causal language.", "status": "required"},
            {"reviewer": 1, "action": "Remove citations from the conclusion and make it a source-free summary of this study and its limitations.", "status": "required"},
            {"reviewer": 2, "action": "Replace Figures 1-3 with clear, light-background, publication-resolution diagrams.", "status": "required"},
            {"reviewer": 2, "action": "Standardise paragraph indentation and line spacing.", "status": "required"},
            {"reviewer": 3, "action": "Change objective and implication bullets to IEEE-compatible alphabetic/roman structure.", "status": "required"},
            {"reviewer": 3, "action": "Rebuild Tables I-II to prevent narrow columns, mid-word wrapping and tiny labels.", "status": "required"},
        ]
        paper_hash = self._sha256(self.PAPER_PATH) if self.PAPER_PATH.is_file() else None
        return {
            "paper": {
                "title": "Adaptive AI for Curriculum-Labour Market Alignment in Smart Informatics",
                "paper_id": "1571306094",
                "accepted_pdf": str(self.PAPER_PATH),
                "accepted_pdf_sha256": paper_hash,
                "page_count": 6,
                "camera_ready_due": "2026-08-20",
            },
            "generated_from": {
                "tenant_id": str(tenant_id),
                "current_counts": counts,
                "locked_label_snapshot": {
                    "snapshot_id": str(locked_snapshot.snapshot_id),
                    "row_count": locked_snapshot.row_count,
                    "fingerprint": locked_snapshot.dataset_fingerprint,
                } if locked_snapshot else None,
            },
            "claims": claims,
            "status_counts": status_counts,
            "camera_ready_gate": "revision_required" if blocking else "claims_reconciled",
            "blocking_claim_ids": [item["claim_id"] for item in blocking],
            "reviewer_actions": reviewer_actions,
            "required_camera_ready_positioning": [
                "The paper reports preliminary pilot and simulation evidence, not outcomes from a fully operational institutional deployment.",
                "Current portal capabilities and safeguards must be separated from historical numerical pilot results.",
                "No causal graduate-employability, demographic-fairness or cross-institutional-generalisation claim is supported.",
                "New model metrics may be claimed only from a locked independently reviewed dataset and registered model artifact.",
            ],
        }

    def persist(self, db: Session, tenant_id: UUID, actor_id: str) -> dict[str, Any]:
        payload = self.reconcile(db, tenant_id)
        digest = payload_hash(payload)
        report = GeneratedReport(
            report_type="research_claim_reconciliation",
            source_entity_type="accepted_conference_paper",
            source_entity_id=None,
            generated_by=actor_id,
            status=payload["camera_ready_gate"],
            title="ICSSA 2026 accepted-paper claim reconciliation",
            summary={
                "paper_id": payload["paper"]["paper_id"],
                "claim_count": len(payload["claims"]),
                "blocking_claim_count": len(payload["blocking_claim_ids"]),
                "status_counts": payload["status_counts"],
                "camera_ready_gate": payload["camera_ready_gate"],
            },
            payload=payload,
            payload_hash=digest,
            format_hint="json",
            notes="Claims are constrained to reproducible evidence; this report does not edit the accepted manuscript.",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return {
            "report_id": str(report.report_id),
            "payload_hash": digest,
            "created_at": report.created_at,
            **payload,
        }

    @staticmethod
    def claim(claim_id: str, location: str, claim: str, status: str, evidence: str,
              evidence_sources: list[str], camera_ready_action: str) -> dict[str, Any]:
        return {
            "claim_id": claim_id, "paper_location": location, "claim": claim,
            "status": status, "evidence": evidence, "evidence_sources": evidence_sources,
            "camera_ready_action": camera_ready_action,
        }

    def _counts(self, db: Session, tenant_id: UUID) -> dict[str, int]:
        tenant_docs = or_(CurriculumDocument.tenant_id == tenant_id, CurriculumDocument.tenant_id.is_(None))
        return {
            "curriculum_documents": db.query(func.count(CurriculumDocument.document_id)).filter(tenant_docs).scalar() or 0,
            "curriculum_modules": db.query(func.count(CurriculumModule.module_id)).scalar() or 0,
            "document_chunks": db.query(func.count(DocumentChunk.chunk_id)).filter(
                or_(DocumentChunk.tenant_id == tenant_id, DocumentChunk.tenant_id.is_(None))
            ).scalar() or 0,
            "job_postings": db.query(func.count(JobPosting.posting_id)).scalar() or 0,
            "labour_market_signals": db.query(func.count(LabourMarketSignal.signal_id)).scalar() or 0,
            "skills": db.query(func.count(Skill.skill_id)).scalar() or 0,
            "skill_mappings": db.query(func.count(SkillMapping.mapping_id)).scalar() or 0,
            "expert_labels": db.query(func.count(AlignmentExpertLabel.label_id)).scalar() or 0,
            "locked_label_snapshots": db.query(func.count(LabelDatasetSnapshot.snapshot_id)).scalar() or 0,
            "registered_models": db.query(func.count(ModelRegistryEntry.entry_id)).scalar() or 0,
            "active_models": db.query(func.count(ModelRegistryEntry.entry_id)).filter(ModelRegistryEntry.is_active == 1).scalar() or 0,
            "committee_decisions": db.query(func.count(RecommendationCommitteeDecision.decision_id)).scalar() or 0,
        }

    @staticmethod
    def _model_evidence(entry: ModelRegistryEntry | None, missing: str) -> str:
        if not entry:
            return missing
        return f"Active registered artifact {entry.model_version} has metrics {entry.metrics or {}}."

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


research_claim_reconciliation_service = ResearchClaimReconciliationService()

