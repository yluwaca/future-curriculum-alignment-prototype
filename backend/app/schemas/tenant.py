"""
Schemas for tenant/institution APIs.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ORM_CONFIG = ConfigDict(from_attributes=True)


class TenantCreate(BaseModel):
    tenant_key: str = Field(..., min_length=1, max_length=150)
    name: str = Field(..., min_length=1, max_length=255)
    tenant_type: str = Field(default="institution", min_length=1, max_length=80)
    country: Optional[str] = None
    region: Optional[str] = None
    status: str = Field(default="active", pattern="^(active|inactive|disabled)$")
    description: Optional[str] = None
    tenant_metadata: Dict[str, Any] = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    tenant_type: Optional[str] = Field(default=None, min_length=1, max_length=80)
    country: Optional[str] = None
    region: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|inactive|disabled)$")
    description: Optional[str] = None
    tenant_metadata: Optional[Dict[str, Any]] = None


class TenantResponse(TenantCreate):
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG
