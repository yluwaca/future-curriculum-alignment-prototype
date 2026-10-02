"""
Tenant and institution management endpoints.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantCreate, TenantResponse, TenantUpdate


router = APIRouter(
    prefix="/tenants",
    tags=["tenants"],
)


@router.get("", response_model=List[TenantResponse])
def list_tenants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Tenant).order_by(Tenant.name.asc()).all()


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(Tenant).filter(Tenant.tenant_key == payload.tenant_key).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tenant already exists")
    tenant = Tenant(**payload.model_dump())
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/{tenant_id}", response_model=TenantResponse)
def get_tenant(
    tenant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.put("/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    db.commit()
    db.refresh(tenant)
    return tenant
