"""
Sensitivity analysis router — cosine threshold sensitivity for camera-ready paper.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.sensitivity_analysis_service import SensitivityAnalysisService


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/sensitivity/cosine-threshold", response_model=Dict[str, Any])
async def cosine_threshold_sensitivity(
    limit_skills: int = Query(500, ge=10, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run sensitivity analysis on cosine similarity threshold.

    Tests thresholds from 0.10 to 0.90 and returns match volume,
    confidence distribution, and recommended threshold.
    """
    service = SensitivityAnalysisService(db)
    result = service.analysation_summary(limit_skills=limit_skills)
    return result


@router.get("/sensitivity/cosine-threshold", response_model=Dict[str, Any])
async def get_sensitivity_cache(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return last available sensitivity analysis results.
    (Reruns if no cache exists.)
    """
    service = SensitivityAnalysisService(db)
    result = service.analysation_summary(limit_skills=500)
    return result
