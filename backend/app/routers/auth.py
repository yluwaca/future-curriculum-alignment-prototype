
# backend/app/routers/auth.py

"""
Authentication router for FUTURE Platform.

Architecture:

- Access Tokens = Stateless JWT
- Refresh Tokens = Stateful
- Session Tracking = Stateful
- Audit Traceability = JTI
"""

from datetime import datetime
from datetime import timezone
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)

from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_user,
)

from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_session_id,
    get_token_expiry_seconds,
    hash_password,
    hash_token,
    verify_password,
    verify_token,
)

from app.db.session import get_db

from app.models.auth_token import (
    AuthToken,
)

from app.models.user import (
    User,
)
from app.models.tenant import Tenant

from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

from app.services.audit_service import (
    log_audit_event,
)

from app.core.rate_limit import limiter, _login_key

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
)

# =========================================================
# Register
# =========================================================


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("3/minute")
def register(
    data: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
):

    existing_user = (
        db.query(User)
        .filter(
            User.identity_id == data.username
        )
        .first()
    )

    if existing_user:

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    existing_email = (
        db.query(User)
        .filter(
            User.email == data.email
        )
        .first()
    )

    if existing_email:

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    default_tenant = db.query(Tenant).filter(Tenant.tenant_key == "cput").first()
    if not default_tenant:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Institution configuration is unavailable",
        )

    user = User(
        identity_id=data.username,
        email=data.email.lower(),
        password_hash=hash_password(
            data.password
        ),
        identity_type="human",
        status="active",
        is_active=True,
        approval_status="pending",
        tenant_id=default_tenant.tenant_id,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="register",
        actor_type="human",
        actor_id=user.identity_id,
        token_id=None,
        source_component="fastapi.auth",
        action="register",
        result="success",
        metadata={
            "email": user.email,
        },
    )

    db.commit()

    return {
        "message": (
            "User registered successfully"
        )
    }

# =========================================================
# Login
# =========================================================


@router.post(
    "/login",
    response_model=TokenResponse,
)
@limiter.limit("10/minute", key_func=_login_key)
def login(
    data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):

    user = (
        db.query(User)
        .filter(
            User.identity_id == data.identifier
        )
        .first()
    )

    if not user:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_password(
        data.password,
        user.password_hash,
    ):

        failed = getattr(user, "failed_login_attempts", 0) or 0
        user.failed_login_attempts = failed + 1
        if user.failed_login_attempts >= 5:
            user.is_active = False
            log_audit_event(
                db=db,
                event_layer="application",
                event_type="security",
                actor_type="human",
                actor_id=user.identity_id,
                token_id=None,
                source_component="fastapi.auth",
                action="account_locked",
                result="success",
                metadata={"reason": "too_many_failed_logins"},
            )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User inactive",
        )

    if user.approval_status == "pending":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending admin approval",
        )

    if user.approval_status == "rejected":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account rejected",
        )

    # -----------------------------------------------------
    # Create Session
    # -----------------------------------------------------

    session_id = create_session_id()

    # -----------------------------------------------------
    # Access Token
    # -----------------------------------------------------

    access_token = create_access_token(
        {
            "sub": user.identity_id,
            "tenant_id": str(user.tenant_id),
        },
        session_id=session_id,
    )

    # -----------------------------------------------------
    # Refresh Token
    # -----------------------------------------------------

    refresh_token = create_refresh_token(
        user.identity_id,
        session_id=session_id,
    )

    refresh_payload = verify_token(
        refresh_token,
        expected_type="refresh",
    )

    refresh_token_hash = hash_token(
        refresh_token
    )

    ip_address = (
        request.client.host
        if request.client
        else None
    )

    db_token = AuthToken(
        token_id=UUID(session_id),
        token_hash=refresh_token_hash,
        token_type="refresh",
        subject_id=user.identity_id,
        subject_type=user.identity_type,
        issued_by="future-platform",
        expires_at=datetime.fromtimestamp(
            refresh_payload["exp"],
            tz=timezone.utc,
        ),
        ip_address=ip_address,
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    db.add(db_token)

    user.last_login_at = datetime.now(
        timezone.utc
    )

    user.failed_login_attempts = 0

    db.commit()

    access_payload = verify_token(
        access_token,
        expected_type="access",
    )

    expires_in = get_token_expiry_seconds(
        access_payload["exp"]
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="login",
        actor_type="human",
        actor_id=user.identity_id,
        token_id=db_token.token_id,
        source_component="fastapi.auth",
        action="login",
        result="success",
        metadata={
            "ip_address": ip_address,
        },
    )

    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )

# =========================================================
# Refresh
# =========================================================


@router.post(
    "/refresh",
    response_model=TokenResponse,
)
@limiter.limit("10/minute")
def refresh(
    data: RefreshTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
):

    payload = verify_token(
        data.refresh_token,
        expected_type="refresh",
    )

    token_hash = hash_token(
        data.refresh_token
    )

    db_token = (
        db.query(AuthToken)
        .filter(
            AuthToken.token_hash == token_hash,
            AuthToken.revoked.is_(False),
        )
        .first()
    )

    if not db_token:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Rotate: revoke old token
    db_token.revoked = True

    user_id = db_token.subject_id
    refresh_user = db.query(User).filter(User.identity_id == user_id).first()
    if not refresh_user or not refresh_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant assignment required")
    old_session_id = str(db_token.token_id)

    # Issue new tokens
    new_session_id = create_session_id()

    access_token = create_access_token(
        {
            "sub": user_id,
            "tenant_id": str(refresh_user.tenant_id),
        },
        session_id=new_session_id,
    )

    new_refresh_token = create_refresh_token(
        user_id,
        session_id=new_session_id,
    )

    new_refresh_payload = verify_token(
        new_refresh_token,
        expected_type="refresh",
    )

    new_refresh_hash = hash_token(new_refresh_token)

    db.add(
        AuthToken(
            token_id=UUID(new_session_id),
            token_hash=new_refresh_hash,
            token_type="refresh",
            subject_id=user_id,
            subject_type=db_token.subject_type,
            issued_by="future-platform",
            expires_at=datetime.fromtimestamp(
                new_refresh_payload["exp"],
                tz=timezone.utc,
            ),
            ip_address=db_token.ip_address,
            user_agent=db_token.user_agent,
        )
    )

    access_payload = verify_token(
        access_token,
        expected_type="access",
    )

    expires_in = get_token_expiry_seconds(
        access_payload["exp"]
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="refresh",
        actor_type=db_token.subject_type,
        actor_id=user_id,
        token_id=UUID(new_session_id),
        source_component="fastapi.auth",
        action="refresh_rotate",
        result="success",
        metadata={"old_session": old_session_id},
    )

    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )

# =========================================================
# Logout
# =========================================================


@router.post("/logout")
def logout(
    request: Request,
    current_user: User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
):

    token_id = getattr(
        request.state,
        "token_id",
        None,
    )

    if token_id:

        db_token = (
            db.query(AuthToken)
            .filter(
                AuthToken.token_id
                == UUID(token_id)
            )
            .first()
        )

        if db_token:

            db_token.revoked = True

            db_token.revoked_at = (
                datetime.now(
                    timezone.utc
                )
            )

            log_audit_event(
                db=db,
                event_layer="application",
                event_type="logout",
                actor_type=current_user.identity_type,
                actor_id=current_user.identity_id,
                token_id=db_token.token_id,
                source_component="fastapi.auth",
                action="logout",
                result="success",
                metadata={},
            )

            db.commit()

    return {
        "message": "Logout successful"
    }

# =========================================================
# Current User
# =========================================================


@router.get(
    "/me",
    response_model=UserResponse,
)
def get_me(
    current_user: User = Depends(
        get_current_user
    ),
):

    role_names = [
        r.role_name
        for r in (current_user.roles or [])
        if getattr(r, "role_name", None)
    ]

    return UserResponse(
        identity_id=current_user.identity_id,
        tenant_id=current_user.tenant_id,
        email=current_user.email,
        status=current_user.status,
        identity_type=current_user.identity_type,
        is_active=current_user.is_active,
        is_admin=current_user.is_admin,
        approval_status=getattr(
            current_user, "approval_status", "approved"
        ),
        roles=role_names,
    )

# =========================================================
# Change Password
# =========================================================


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
)
def change_password(
    data: PasswordChangeRequest,
    current_user: User = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
):

    if not verify_password(
        data.current_password,
        current_user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(
        data.new_password
    )
    db.commit()

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="security",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="fastapi.auth",
        action="password_changed",
        result="success",
        metadata={},
    )

    return {"message": "Password changed successfully"}
