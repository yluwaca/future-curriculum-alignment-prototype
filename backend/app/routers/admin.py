"""
Admin router for user management.

Endpoints:
- List users with filtering
- Approve / reject pending users
- Assign roles
- Activate / deactivate / lock accounts
"""

from datetime import datetime
from datetime import timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_user,
)
from app.core.permissions import (
    require_permission,
)
from app.core.security import hash_password
from app.db.session import get_db
from app.models.role import Role
from app.models.user import User
from app.models.user_role import UserRole
from app.schemas.user import (
    AdminApproveRequest,
    AdminRejectRequest,
    AdminResetPasswordRequest,
    AdminRoleUpdateRequest,
    AdminStatusUpdateRequest,
)
from app.services.audit_service import (
    log_audit_event,
)
from app.services.rbac_service import (
    invalidate_permission_cache,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
)


# =========================================================
# List Users
# =========================================================


@router.get("/users")
def list_users(
    request: Request,
    approval_status: str = Query(
        None,
        description="Filter by approval_status",
    ),
    search: str = Query(
        None,
        description="Search by identity_id or email",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("system.admin")),
):
    query = db.query(User)

    if approval_status:
        query = query.filter(
            User.approval_status == approval_status
        )

    if search:
        escaped = search.replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        query = query.filter(
            or_(
                User.identity_id.ilike(term),
                User.email.ilike(term),
            )
        )

    total = query.count()
    users = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for u in users:
        role_names = [
            r.role_name
            for r in (u.roles or [])
            if getattr(r, "role_name", None)
        ]
        items.append({
            "identity_id": u.identity_id,
            "email": u.email,
            "approval_status": u.approval_status or "pending",
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "roles": role_names,
            "last_login_at": (
                u.last_login_at.isoformat()
                if u.last_login_at
                else None
            ),
            "created_at": (
                u.created_at.isoformat()
                if u.created_at
                else None
            ),
        })

    return {
        "users": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (
            (total + page_size - 1) // page_size
        ),
    }


# =========================================================
# User Detail
# =========================================================


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("system.admin")),
):
    user = (
        db.query(User)
        .filter(User.identity_id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    role_names = [
        r.role_name
        for r in (user.roles or [])
        if getattr(r, "role_name", None)
    ]

    return {
        "identity_id": user.identity_id,
        "email": user.email,
        "approval_status": user.approval_status or "pending",
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "roles": role_names,
        "approved_by": user.approved_by,
        "approved_at": (
            user.approved_at.isoformat()
            if user.approved_at
            else None
        ),
        "rejection_reason": user.rejection_reason,
        "last_login_at": (
            user.last_login_at.isoformat()
            if user.last_login_at
            else None
        ),
        "created_at": (
            user.created_at.isoformat()
            if user.created_at
            else None
        ),
    }


# =========================================================
# Approve User
# =========================================================


@router.put("/users/{user_id}/approve")
def approve_user(
    user_id: str,
    data: AdminApproveRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("system.admin")),
):
    user = (
        db.query(User)
        .filter(User.identity_id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.approval_status == "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already approved",
        )

    role = (
        db.query(Role)
        .filter(
            Role.role_id == data.default_role,
            Role.is_active.is_(True),
        )
        .first()
    )

    if not role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f'Role "{data.default_role}" is not available. '
                "Refresh the role catalogue and select an active role."
            ),
        )

    now = datetime.now(timezone.utc)
    admin_id = admin.identity_id

    user.approval_status = "approved"
    user.approved_by = admin_id
    user.approved_at = now
    user.rejection_reason = None

    existing = (
        db.query(UserRole)
        .filter(
            UserRole.identity_id == user_id,
            UserRole.role_id == data.default_role,
        )
        .first()
    )

    if existing:
        existing.is_active = True
    else:
        db.add(
            UserRole(
                identity_id=user_id,
                role_id=data.default_role,
                is_active=True,
            )
        )

    user.is_admin = data.default_role == "admin"

    db.commit()

    invalidate_permission_cache(user_id)

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="admin_action",
        actor_type="human",
        actor_id=admin_id,
        token_id=None,
        source_component="fastapi.admin",
        action="approve_user",
        result="success",
        metadata={
            "target_user": user_id,
            "default_role": data.default_role,
            "notes": data.notes,
        },
    )

    return {
        "message": "User approved",
        "identity_id": user_id,
        "approved_by": admin_id,
        "default_role": data.default_role,
    }


# =========================================================
# Reject User
# =========================================================


@router.put("/users/{user_id}/reject")
def reject_user(
    user_id: str,
    data: AdminRejectRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("system.admin")),
):
    user = (
        db.query(User)
        .filter(User.identity_id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.approval_status = "rejected"
    user.rejection_reason = data.reason

    db.commit()

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="admin_action",
        actor_type="human",
        actor_id=admin.identity_id,
        token_id=None,
        source_component="fastapi.admin",
        action="reject_user",
        result="success",
        metadata={
            "target_user": user_id,
            "reason": data.reason,
        },
    )

    return {
        "message": "User rejected",
        "identity_id": user_id,
    }


# =========================================================
# Update Roles
# =========================================================


@router.put("/users/{user_id}/roles")
def update_roles(
    user_id: str,
    data: AdminRoleUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("system.admin")),
):
    user = (
        db.query(User)
        .filter(User.identity_id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not data.roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An approved user must have at least one active role.",
        )

    available_roles = (
        db.query(Role)
        .filter(
            Role.role_id.in_(data.roles),
            Role.is_active.is_(True),
        )
        .all()
    )
    available_role_ids = {role.role_id for role in available_roles}
    unknown_role_ids = sorted(set(data.roles) - available_role_ids)
    if unknown_role_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unknown or inactive role(s): "
                + ", ".join(unknown_role_ids)
            ),
        )

    (
        db.query(UserRole)
        .filter(UserRole.identity_id == user_id)
        .delete()
    )

    for role_id in data.roles:
        db.add(
            UserRole(
                identity_id=user_id,
                role_id=role_id,
                is_active=True,
            )
        )

    user.is_admin = "admin" in data.roles

    db.commit()

    invalidate_permission_cache(user_id)

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="admin_action",
        actor_type="human",
        actor_id=admin.identity_id,
        token_id=None,
        source_component="fastapi.admin",
        action="update_roles",
        result="success",
        metadata={
            "target_user": user_id,
            "roles": data.roles,
        },
    )

    return {
        "message": "Roles updated",
        "identity_id": user_id,
        "roles": data.roles,
    }


# =========================================================
# Update Status
# =========================================================


@router.put("/users/{user_id}/status")
def update_status(
    user_id: str,
    data: AdminStatusUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("system.admin")),
):
    user = (
        db.query(User)
        .filter(User.identity_id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if data.is_active is not None:
        user.is_active = data.is_active
        if data.is_active:
            user.failed_login_attempts = 0

    if data.is_admin is not None:
        user.is_admin = data.is_admin

    db.commit()

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="admin_action",
        actor_type="human",
        actor_id=admin.identity_id,
        token_id=None,
        source_component="fastapi.admin",
        action="update_user_status",
        result="success",
        metadata={
            "target_user": user_id,
            "is_active": data.is_active,
            "is_admin": data.is_admin,
        },
    )

    return {
        "message": "Status updated",
        "identity_id": user_id,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
    }


# =========================================================
# Reset Password
# =========================================================


@router.put("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    data: AdminResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("system.admin")),
):
    user = (
        db.query(User)
        .filter(User.identity_id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.password_hash = hash_password(
        data.new_password
    )
    user.failed_login_attempts = 0
    if not user.is_active:
        user.is_active = True

    db.commit()

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="admin_action",
        actor_type="human",
        actor_id=admin.identity_id,
        token_id=None,
        source_component="fastapi.admin",
        action="reset_password",
        result="success",
        metadata={
            "target_user": user_id,
        },
    )

    return {
        "message": f"Password reset for {user_id}",
        "identity_id": user_id,
    }


# =========================================================
# List Roles
# =========================================================


@router.get("/roles")
def list_roles(
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("system.admin")),
):
    roles = (
        db.query(Role)
        .filter(Role.is_active == True)
        .order_by(Role.role_id)
        .all()
    )

    return {
        "roles": [
            {
                "role_id": r.role_id,
                "role_name": r.role_name,
                "description": r.description,
            }
            for r in roles
        ]
    }


# =========================================================
# Audit Logs
# =========================================================


@router.get("/audit-logs")
def list_audit_logs(
    event_type: str | None = Query(None, description="Filter by event type"),
    username: str | None = Query(None, description="Filter by username"),
    limit: int = Query(50, ge=1, le=500),
    _admin=Depends(require_permission("system.admin")),
    db: Session = Depends(get_db),
):
    """List audit log entries with optional filters."""
    from app.models.audit_event import AuditEvent

    query = db.query(AuditEvent)

    if event_type:
        query = query.filter(AuditEvent.event_type == event_type)
    if username:
        query = query.filter(AuditEvent.actor_id == username)

    logs = query.order_by(AuditEvent.event_time.desc()).limit(limit).all()

    return {
        "logs": [
            {
                "id": str(log.event_id),
                "event_type": log.event_type,
                "actor_id": log.actor_id,
                "action": log.action,
                "result": log.result,
                "metadata": log.event_metadata,
                "created_at": log.event_time.isoformat() if log.event_time else None,
            }
            for log in logs
        ],
        "count": len(logs),
    }


# =========================================================
# Platform Stats
# =========================================================


@router.get("/stats")
def platform_stats(
    _admin=Depends(require_permission("system.admin")),
    db: Session = Depends(get_db),
):
    """Platform usage statistics for monitoring dashboard."""
    from datetime import timedelta
    from sqlalchemy import func
    from app.models.audit_event import AuditEvent

    now = datetime.now(timezone.utc)

    # User counts
    total_users = db.query(User).count()
    pending_users = db.query(User).filter(User.approval_status == "pending").count()
    active_users = db.query(User).filter(User.is_active == True).count()
    locked_users = db.query(User).filter(User.failed_login_attempts >= 5).count()

    # Audit events (last 24h and 7d)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    events_24h = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_time >= day_ago)
        .count()
    )
    events_7d = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_time >= week_ago)
        .count()
    )

    # Login attempts (last 24h)
    logins_24h = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "user_login",
            AuditEvent.event_time >= day_ago,
        )
        .count()
    )

    failed_logins_24h = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "login_failed",
            AuditEvent.event_time >= day_ago,
        )
        .count()
    )

    # Role distribution
    role_counts = (
        db.query(Role.role_name, func.count(UserRole.identity_id))
        .join(UserRole, Role.role_id == UserRole.role_id)
        .group_by(Role.role_name)
        .all()
    )

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "pending": pending_users,
            "locked": locked_users,
        },
        "activity": {
            "events_24h": events_24h,
            "events_7d": events_7d,
            "logins_24h": logins_24h,
            "failed_logins_24h": failed_logins_24h,
        },
        "roles": {name: count for name, count in role_counts},
        "timestamp": now.isoformat(),
    }
