
# backend/app/services/audit_service.py

"""
Enterprise Audit Service.

Supports:

- Authentication auditing
- Authorization auditing
- Session auditing
- Predictive analytics auditing
- ETL auditing
- Forecast auditing
- Model training auditing

Architecture:

User
 |
 v
JWT (JTI)
 |
 v
AuditEvent
 |
 v
SEC01_AuthToken
 |
 v
System Identity

This provides full traceability.
"""

from __future__ import annotations

import logging

from typing import Any
from typing import Dict
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)

# =========================================================
# Audit Event Types
# =========================================================

AUTH_LOGIN = "LOGIN"

AUTH_LOGOUT = "LOGOUT"

AUTH_REFRESH = "REFRESH"

AUTH_FAILED_LOGIN = "FAILED_LOGIN"

AUTH_UNAUTHORIZED = "UNAUTHORIZED"

AUTH_FORBIDDEN = "FORBIDDEN"

PREDICT_ALIGNMENT = (
    "ALIGNMENT_PREDICTION"
)

PREDICT_FORECAST = (
    "DEMAND_FORECAST"
)

PREDICT_TRAINING = (
    "MODEL_TRAINING"
)

PREDICT_ETL = (
    "ETL_INGEST"
)

PREDICT_SHAP = (
    "SHAP_EXPLANATION"
)

# =========================================================
# Audit Service
# =========================================================


class AuditService:
    """
    Enterprise audit service.
    """

    def log_event(
        self,
        db: Session,
        user_id: Optional[str],
        action: str,
        resource: str,
        details: Optional[
            Dict[str, Any]
        ] = None,
        severity: str = "info",
        result: str = "success",
        actor_type: str = "human",
        source_component: str = "future_platform",
        token_id: Optional[str] = None,
    ) -> AuditEvent:
        """
        Queue audit event.

        Caller owns transaction lifecycle.
        """

        try:

            metadata = details or {}

            metadata.setdefault(
                "resource",
                resource,
            )

            event = AuditEvent(
                event_layer="application",
                event_type=action,
                actor_type=actor_type,
                actor_id=user_id,
                token_id=token_id,
                source_component=source_component,
                action=action,
                result=result,
                severity=severity,
                event_metadata=metadata,
            )

            db.add(event)

            logger.info(
                "[AUDIT] %s | user=%s | resource=%s",
                action,
                user_id,
                resource,
            )

            return event

        except SQLAlchemyError:

            logger.exception(
                "[AUDIT] Failed to queue audit event"
            )

            raise

    # =====================================================
    # Authentication
    # =====================================================

    def log_login(
        self,
        db: Session,
        user_id: str,
        token_id: Optional[str],
        details: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AuditEvent:

        return self.log_event(
            db=db,
            user_id=user_id,
            action=AUTH_LOGIN,
            resource="auth",
            token_id=token_id,
            details=details,
        )

    def log_logout(
        self,
        db: Session,
        user_id: str,
        token_id: Optional[str],
        details: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AuditEvent:

        return self.log_event(
            db=db,
            user_id=user_id,
            action=AUTH_LOGOUT,
            resource="auth",
            token_id=token_id,
            details=details,
        )

    def log_refresh(
        self,
        db: Session,
        user_id: str,
        token_id: Optional[str],
        details: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AuditEvent:

        return self.log_event(
            db=db,
            user_id=user_id,
            action=AUTH_REFRESH,
            resource="auth",
            token_id=token_id,
            details=details,
        )

    # =====================================================
    # Predictive Platform
    # =====================================================

    def log_prediction(
        self,
        db: Session,
        user_id: Optional[str],
        module_code: str,
        token_id: Optional[str] = None,
        details: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AuditEvent:

        return self.log_event(
            db=db,
            user_id=user_id,
            action=PREDICT_ALIGNMENT,
            resource=module_code,
            token_id=token_id,
            details=details,
        )

    def log_forecast(
        self,
        db: Session,
        user_id: Optional[str],
        module_code: str,
        token_id: Optional[str] = None,
        details: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AuditEvent:

        return self.log_event(
            db=db,
            user_id=user_id,
            action=PREDICT_FORECAST,
            resource=module_code,
            token_id=token_id,
            details=details,
        )

    def log_training(
        self,
        db: Session,
        user_id: Optional[str],
        model_name: str,
        token_id: Optional[str] = None,
        details: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AuditEvent:

        return self.log_event(
            db=db,
            user_id=user_id,
            action=PREDICT_TRAINING,
            resource=model_name,
            token_id=token_id,
            details=details,
        )

    def log_ingestion(
        self,
        db: Session,
        user_id: Optional[str],
        token_id: Optional[str] = None,
        details: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AuditEvent:

        return self.log_event(
            db=db,
            user_id=user_id,
            action=PREDICT_ETL,
            resource="etl_pipeline",
            token_id=token_id,
            details=details,
        )

# =========================================================
# Singleton
# =========================================================

audit_service = AuditService()

# =========================================================
# Backward Compatibility
# =========================================================


def log_audit_event(
    db: Session,
    event_layer: str,
    event_type: str,
    actor_type: str,
    actor_id: Optional[str],
    token_id: Optional[str],
    source_component: str,
    action: str,
    result: str,
    severity: str = "info",
    metadata: Optional[
        Dict[str, Any]
    ] = None,
) -> AuditEvent:
    """
    Legacy compatibility wrapper.
    """

    return audit_service.log_event(
        db=db,
        user_id=actor_id,
        action=action,
        resource=event_type,
        token_id=token_id,
        details=metadata,
        severity=severity,
        result=result,
        actor_type=actor_type,
        source_component=source_component,
    )

def log_access_denied(
    db: Session,
    identity_id: str,
    required_permission: str,
    resource: str,
    method: str,
    reason: str,
) -> None:
    """
    Log an access denied event.
    """
    audit_service.log_event(
        db=db,
        user_id=identity_id,
        action=AUTH_FORBIDDEN,
        resource=resource,
        details={
            "required_permission": required_permission,
            "method": method,
            "reason": reason,
        },
        severity="warning",
        result="denied",
    )
