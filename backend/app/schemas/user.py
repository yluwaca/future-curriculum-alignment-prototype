"""
User profile and identity management schemas.
Supports RBAC, audit trails, and POPIA-compliant user data handling.
"""

from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class RoleAssignment(BaseModel):
    """Nested schema for role assignment details."""
    role_id: str = Field(..., description="Unique role identifier")
    role_name: str = Field(..., description="Human-readable role name")
    assigned_at: Optional[datetime] = Field(None, description="Timestamp when role was assigned")


class UserProfile(BaseModel):
    """
    Public-facing user profile information (non-sensitive fields only).
    Used for display in dashboards and audit logs (no PII beyond username).
    """
    user_id: str = Field(..., description="Unique user identifier")
    username: str = Field(..., description="Public username/handle")
    display_name: Optional[str] = Field(None, description="Optional display name")
    email: Optional[str] = Field(None, description="Email (masked in non-admin contexts)")
    faculty: Optional[str] = Field(None, description="Associated academic faculty")
    role_names: List[str] = Field(default_factory=list, description="Assigned role names for RBAC display")
    is_active: bool = Field(..., description="Whether account is currently active")
    last_login: Optional[datetime] = Field(None, description="Timestamp of last successful authentication")
    created_at: datetime = Field(..., description="Account creation timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "usr_abc123xyz",
                "username": "yolisa_luwaca",
                "display_name": "Yolisa L.",
                "email": "y***@cput.ac.za",
                "faculty": "Informatics and Design",
                "role_names": ["researcher", "curriculum_reviewer"],
                "is_active": True,
                "last_login": "2024-05-15T08:30:00Z",
                "created_at": "2024-01-10T10:00:00Z"
            }
        }
    )


class UserProfileAdmin(BaseModel):
    """
    Administrative user profile with full details (RBAC: admin_only).
    Used for user management, audit, and compliance reporting.
    """
    user_id: str = Field(..., description="Unique user identifier")
    identity_id: str = Field(..., description="System identity identifier (internal)")
    username: str = Field(..., description="Login username")
    email: Optional[str] = Field(None, description="Verified email address")
    full_name: Optional[str] = Field(None, description="Full legal name")
    faculty: Optional[str] = Field(None, description="Associated academic faculty")
    department: Optional[str] = Field(None, description="Department/unit within faculty")
    employee_number: Optional[str] = Field(None, description="Institutional employee ID (if staff)")
    student_number: Optional[str] = Field(None, description="Institutional student ID (if student)")
    roles: List[RoleAssignment] = Field(default_factory=list, description="Assigned roles with metadata")
    permissions: List[str] = Field(default_factory=list, description="Directly assigned permissions")
    is_active: bool = Field(..., description="Account active status")
    is_approved: bool = Field(..., description="Registration approval status")
    is_locked: bool = Field(default=False, description="Account lock status (failed login attempts)")
    last_login: Optional[datetime] = Field(None)
    last_password_change: Optional[datetime] = Field(None)
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional non-sensitive metadata")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "usr_abc123xyz",
                "identity_id": "idt_def456uvw",
                "username": "yolisa_luwaca",
                "email": "yolisa.luwaca@cput.ac.za",
                "full_name": "Yolisa Luwaca",
                "faculty": "Informatics and Design",
                "department": "Computer Science",
                "employee_number": "EMP000001",
                "roles": [
                    {"role_id": "role_researcher", "role_name": "Researcher", "assigned_at": "2024-01-10T10:00:00Z"}
                ],
                "permissions": ["curriculum:read", "prediction:create", "audit:view"],
                "is_active": True,
                "is_approved": True,
                "is_locked": False,
                "last_login": "2024-05-15T08:30:00Z",
                "last_password_change": "2024-03-01T12:00:00Z",
                "created_at": "2024-01-10T10:00:00Z",
                "updated_at": "2024-05-15T08:30:00Z"
            }
        }
    )


class UserUpdateRequest(BaseModel):
    """
    Request payload for updating user profile fields.
    Supports partial updates; only provided fields are modified.
    """
    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = Field(None, description="New email (requires re-verification)")
    faculty: Optional[str] = Field(None, min_length=1, max_length=100)
    department: Optional[str] = Field(None, min_length=1, max_length=100)

    @field_validator("display_name", "faculty", "department")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.strip()
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "display_name": "Yolisa L.",
                "faculty": "Informatics and Design"
            }
        },
        extra="forbid"
    )


class UserUpdateAdminRequest(BaseModel):
    """
    Administrative request for updating user account settings.
    RBAC: admin_only. Supports role assignment, approval, and account management.
    """
    is_active: Optional[bool] = Field(None, description="Activate or deactivate account")
    is_approved: Optional[bool] = Field(None, description="Approve or reject pending registration")
    is_locked: Optional[bool] = Field(None, description="Lock or unlock account")
    roles_to_add: Optional[List[str]] = Field(None, description="Role IDs to assign")
    roles_to_remove: Optional[List[str]] = Field(None, description="Role IDs to revoke")
    permissions_to_add: Optional[List[str]] = Field(None, description="Direct permissions to grant")
    permissions_to_remove: Optional[List[str]] = Field(None, description="Direct permissions to revoke")
    admin_notes: Optional[str] = Field(None, max_length=1000, description="Internal admin notes for audit trail")

    @model_validator(mode='after')
    def validate_role_changes(self) -> 'UserUpdateAdminRequest':
        """Prevent simultaneous add/remove of same role."""
        if self.roles_to_add and self.roles_to_remove:
            overlap = set(self.roles_to_add) & set(self.roles_to_remove)
            if overlap:
                raise ValueError(f"Cannot both add and remove roles: {overlap}")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "is_approved": True,
                "roles_to_add": ["role_curriculum_reviewer"],
                "admin_notes": "Approved after verification of CPUT staff status"
            }
        }
    )


class AdminUserListItem(BaseModel):
    """User list item for admin panel."""
    identity_id: str
    email: Optional[str] = None
    approval_status: str = "pending"
    is_active: bool = True
    is_admin: bool = False
    roles: List[str] = Field(default_factory=list)
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AdminApproveRequest(BaseModel):
    """Approve a pending user."""
    default_role: str = Field(default="viewer", description="Role to assign on approval")
    notes: Optional[str] = Field(None, max_length=500)


class AdminRejectRequest(BaseModel):
    """Reject a pending user."""
    reason: str = Field(..., min_length=1, max_length=500, description="Rejection reason")


class AdminRoleUpdateRequest(BaseModel):
    """Update a user's roles."""
    roles: List[str] = Field(..., description="Complete list of role IDs to assign")


class AdminStatusUpdateRequest(BaseModel):
    """Update a user's active/locked status."""
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


class AdminResetPasswordRequest(BaseModel):
    """Admin reset a user's password."""
    new_password: str = Field(..., min_length=8, max_length=128, description="New password")
