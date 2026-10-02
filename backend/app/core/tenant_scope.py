"""Fail-closed tenant context and SQLAlchemy query guards."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_


def require_user_tenant(user: Any) -> UUID:
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active tenant assignment is required for institutional data.",
        )
    return UUID(str(tenant_id))


def enforce_requested_tenant(user: Any, requested_tenant_id: UUID | None) -> UUID:
    tenant_id = require_user_tenant(user)
    if requested_tenant_id and UUID(str(requested_tenant_id)) != tenant_id:
        # Return 404 semantics at entity boundaries so another tenant's
        # identifiers cannot be enumerated.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return tenant_id


def scope_query(query, model, user: Any, *, include_shared: bool = True):
    tenant_id = require_user_tenant(user)
    tenant_column = getattr(model, "tenant_id")
    if include_shared:
        return query.filter(or_(tenant_column == tenant_id, tenant_column.is_(None)))
    return query.filter(tenant_column == tenant_id)


def assert_entity_access(entity: Any, user: Any, *, shared_allowed: bool = True) -> UUID:
    tenant_id = require_user_tenant(user)
    entity_tenant = getattr(entity, "tenant_id", None)
    if entity_tenant is None and shared_allowed:
        return tenant_id
    if entity_tenant is None or UUID(str(entity_tenant)) != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return tenant_id
