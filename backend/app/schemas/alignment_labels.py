from typing import List
from uuid import UUID

from pydantic import BaseModel, Field


class AlignmentLabelRequest(BaseModel):
    alignment_label: int = Field(ge=1, le=5)
    confidence: int = Field(ge=1, le=5)
    justification: str = Field(min_length=20, max_length=5000)
    present_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)


class RuleAssistedConfirmRequest(BaseModel):
    task_ids: List[UUID] = Field(min_length=1, max_length=500)
    proposal_fingerprint: str = Field(min_length=64, max_length=64)
    dry_run: bool = True
