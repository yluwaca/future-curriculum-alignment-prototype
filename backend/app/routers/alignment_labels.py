from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.alignment_labels import AlignmentLabelRequest, RuleAssistedConfirmRequest
from app.services.alignment_labelling_service import alignment_labelling_service
from app.services.label_dataset_snapshot_service import label_dataset_snapshot_service

ALLOWED_DATASET_MODES = (
    "technical_uat_researcher_operated",
    "independent_expert_validation",
    "rule_assisted_confirmed",
)

router = APIRouter(prefix="/alignment-labels", tags=["alignment-labels"])


@router.post("/tasks/generate")
def generate_alignment_review_tasks(
    limit: int = Query(default=100, ge=1, le=2500),
    dataset_mode: str = Query(default="technical_uat_researcher_operated"),
    granularity: str = Query(default="subject", pattern="^(subject|subject_module_group|subject_module_skill|evidence_chunk_skill)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    validate_dataset_mode(dataset_mode)
    try:
        return alignment_labelling_service.generate_tasks(
            db, current_user.identity_id, limit, dataset_mode=dataset_mode, granularity=granularity
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/tasks/sample")
def build_alignment_sample(
    target_size: int = Query(default=12, ge=2, le=500),
    dataset_mode: str = Query(default="technical_uat_researcher_operated"),
    sample_seed: str | None = Query(default=None, max_length=128),
    exclude_sampled: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    validate_dataset_mode(dataset_mode)
    try:
        return alignment_labelling_service.build_sample(
            db=db,
            actor_id=current_user.identity_id,
            dataset_mode=dataset_mode,
            target_size=target_size,
            seed=sample_seed,
            exclude_sampled=exclude_sampled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/tasks")
def alignment_review_queue(
    limit: int = Query(default=100, ge=1, le=500),
    dataset_mode: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    stratum: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if dataset_mode:
        validate_dataset_mode(dataset_mode)
    return alignment_labelling_service.queue(
        db,
        current_user.identity_id,
        limit,
        dataset_mode=dataset_mode,
        status=status_filter,
        search=search,
        stratum=stratum,
    )


@router.get("/tasks/disagreements")
def alignment_disagreements(
    dataset_mode: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if dataset_mode:
        validate_dataset_mode(dataset_mode)
    return {
        "items": alignment_labelling_service.disagreement_items(db, dataset_mode=dataset_mode),
        "dataset_mode": dataset_mode,
    }


@router.get("/quality")
def alignment_label_quality(
    dataset_mode: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if dataset_mode:
        validate_dataset_mode(dataset_mode)
    return alignment_labelling_service.quality_summary(db, dataset_mode=dataset_mode)


@router.post("/tasks/{task_id}/labels", status_code=status.HTTP_201_CREATED)
def submit_alignment_label(
    task_id: UUID,
    payload: AlignmentLabelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    try:
        return alignment_labelling_service.submit_label(
            db=db,
            task_id=task_id,
            reviewer_id=current_user.identity_id,
            alignment_label=payload.alignment_label,
            confidence=payload.confidence,
            justification=payload.justification,
            present_skills=payload.present_skills,
            missing_skills=payload.missing_skills,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/rule-assisted/proposals")
def preview_rule_assisted_proposals(
    target_size: int = Query(default=500, ge=1, le=2500),
    per_class_cap: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    return alignment_labelling_service.rule_assisted_proposals(
        db=db,
        target_size=target_size,
        per_class_cap=per_class_cap,
    )


@router.post("/rule-assisted/confirm")
def confirm_rule_assisted_proposals(
    payload: RuleAssistedConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    try:
        return alignment_labelling_service.confirm_rule_assisted(
            db=db,
            actor_id=current_user.identity_id,
            task_ids=payload.task_ids,
            proposal_fingerprint=payload.proposal_fingerprint,
            dry_run=payload.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/snapshots")
def list_label_dataset_snapshots(
    limit: int = Query(default=25, ge=1, le=100),
    dataset_mode: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if dataset_mode:
        validate_dataset_mode(dataset_mode)
    return {
        "items": [
            label_dataset_snapshot_service.to_dict(snapshot)
            for snapshot in label_dataset_snapshot_service.list_snapshots(db, limit, dataset_mode=dataset_mode)
        ]
    }


@router.get("/snapshots/latest")
def latest_label_dataset_snapshot(
    dataset_mode: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if dataset_mode:
        validate_dataset_mode(dataset_mode)
    snapshot = label_dataset_snapshot_service.latest_locked(db, dataset_mode=dataset_mode)
    return {"latest": label_dataset_snapshot_service.to_dict(snapshot) if snapshot else None}


@router.post("/snapshots/lock", status_code=status.HTTP_201_CREATED)
def lock_label_dataset_snapshot(
    dataset_mode: str = Query(default="technical_uat_researcher_operated"),
    notes: str | None = Query(default=None, max_length=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    validate_dataset_mode(dataset_mode)
    try:
        return label_dataset_snapshot_service.create_locked_snapshot(
            db=db,
            actor_id=current_user.identity_id,
            notes=notes or f"Locked completed alignment reviews for mode {dataset_mode}",
            dataset_mode=dataset_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/snapshots/{snapshot_id}/export")
def export_label_dataset_snapshot(
    snapshot_id: UUID,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    include_text: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    validate_dataset_mode_exports()
    try:
        export = label_dataset_snapshot_service.export_snapshot(db, snapshot_id, include_text=include_text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if format == "csv":
        return csv_export_response(export)
    return export


def validate_dataset_mode(dataset_mode: str) -> None:
    if dataset_mode not in ALLOWED_DATASET_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unsupported dataset mode; allowed: {', '.join(ALLOWED_DATASET_MODES)}",
        )


def validate_dataset_mode_exports() -> None:
    return None


def csv_export_response(export: dict) -> Response:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "row_index",
            "task_id",
            "version_id",
            "document_id",
            "dataset_mode",
            "subject_code",
            "stratum",
            "sample_seed",
            "final_alignment_label",
            "first_reviewer_id",
            "first_label",
            "first_confidence",
            "second_reviewer_id",
            "second_label",
            "second_confidence",
            "agreement",
        ]
    )
    for record in export.get("records", []):
        first = record.get("first_review") or {}
        second = record.get("second_review") or {}
        first_label = first.get("alignment_label")
        second_label = second.get("alignment_label")
        writer.writerow(
            [
                record.get("row_index"),
                record.get("task_id"),
                record.get("version_id"),
                record.get("document_id"),
                record.get("dataset_mode"),
                record.get("subject_code"),
                record.get("stratum"),
                record.get("sample_seed"),
                record.get("final_alignment_label"),
                first.get("reviewer_id"),
                first_label,
                first.get("confidence"),
                second.get("reviewer_id"),
                second_label,
                second.get("confidence"),
                1 if (first_label is not None and first_label == second_label) else 0,
            ]
        )
    content = buffer.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="alignment_labels_{export.get("snapshot_version", "export")}.csv"'
            )
        },
    )
