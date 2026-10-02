"""
Contextual fairness and subgroup assessment service for FUTURE Platform.

Phase 6 clarification:
- Faculty/department are institutional context groups, not demographic or
  protected attributes by themselves.
- The service therefore reports subgroup parity/rate differences as contextual
  monitoring evidence with limitations, not as a demographic-fairness claim.
- If future datasets include legally/methodologically valid protected groups,
  those groups must be assessed explicitly with ethics/POPIA justification.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class FairnessAuditService:
    """
    Evaluates contextual subgroup behaviour of alignment and forecast models.

    This intentionally avoids overclaiming demographic fairness. In the current
    FUTURE data model, faculty/department are academic-operational categories.
    They can reveal uneven model behaviour across institutional units, but they
    are not automatically protected demographic attributes.
    """

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def subgroup_rate_difference(
        y_pred: np.ndarray,
        group_a_mask: np.ndarray,
        group_b_mask: np.ndarray,
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Compute |P(predicted positive|A) - P(predicted positive|B)|.

        This is a contextual subgroup rate-difference check. It is related to
        demographic-parity style monitoring, but Phase 6 requires that it not be
        described as demographic fairness unless the grouping variable is a
        justified protected/proxy attribute.
        """
        rate_a = float(y_pred[group_a_mask].mean()) if group_a_mask.sum() > 0 else 0.0
        rate_b = float(y_pred[group_b_mask].mean()) if group_b_mask.sum() > 0 else 0.0
        disparity = abs(rate_a - rate_b)
        passed = disparity <= threshold
        return {
            "metric": "contextual_subgroup_rate_difference",
            "legacy_metric_equivalent": "demographic_parity_rate_difference",
            "group_a_rate": round(rate_a, 4),
            "group_b_rate": round(rate_b, 4),
            "disparity": round(disparity, 4),
            "threshold": threshold,
            "passed": passed,
            "interpretation": "Contextual monitoring only; not a demographic fairness claim.",
        }

    def audit_alignment_predictions(
        self,
        alignment_scores: List[Dict[str, Any]],
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Audit alignment predictions across available institutional context groups.
        """
        limitations = [
            "Faculty/department are institutional context groups, not protected demographic groups by default.",
            "No protected attributes are used in this assessment.",
            "Subgroup differences should trigger review of data coverage, curriculum mix, and model behaviour, not automated exclusion or promotion.",
            "Human curriculum review remains central before recommendations are acted on.",
        ]
        if not alignment_scores:
            return {
                "status": "no_data",
                "assessment_type": "contextual_subgroup_monitoring",
                "protected_attribute_assessment": "not_available",
                "checks": [],
                "limitations": limitations,
            }

        groups: Dict[str, List[int]] = {}
        for score in alignment_scores:
            proxy = score.get("faculty") or score.get("department") or "unknown"
            y = 1 if float(score.get("alignment_score", 0) or 0) >= 0.70 else 0
            groups.setdefault(str(proxy), []).append(y)

        results = []
        proxies = list(groups.keys())
        for i in range(len(proxies)):
            for j in range(i + 1, len(proxies)):
                a = np.array(groups[proxies[i]], dtype=float)
                b = np.array(groups[proxies[j]], dtype=float)
                result = self.subgroup_rate_difference(
                    np.concatenate([a, b]),
                    np.array([True] * len(a) + [False] * len(b)),
                    np.array([False] * len(a) + [True] * len(b)),
                    threshold=threshold,
                )
                result["group_a_label"] = proxies[i]
                result["group_b_label"] = proxies[j]
                result["group_a_n"] = int(len(a))
                result["group_b_n"] = int(len(b))
                if len(a) < 5 or len(b) < 5:
                    result["sample_warning"] = "Small subgroup sample; interpret cautiously."
                results.append(result)

        adequate_groups = len(proxies) >= 2 and all(len(values) >= 5 for values in groups.values())
        all_passed = adequate_groups and all(row["passed"] for row in results)
        return {
            "status": (
                "passed"
                if all_passed
                else ("insufficient_data" if not adequate_groups else "review_required")
            ),
            "assessment_type": "contextual_subgroup_monitoring",
            "protected_attribute_assessment": "not_available_current_dataset",
            "groups_used": proxies,
            "group_variable": "faculty_or_department_when_available",
            "checks": results,
            "minimum_group_sample": 5,
            "adequate_group_coverage": adequate_groups,
            "limitations": limitations,
            "human_review_required": True,
        }

    @staticmethod
    def demographic_parity(
        y_pred: np.ndarray,
        group_a_mask: np.ndarray,
        group_b_mask: np.ndarray,
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Backwards-compatible alias for earlier tests and API clients.

        The platform now reports this as contextual subgroup monitoring unless
        the supplied groups are explicitly justified protected/proxy attributes.
        """
        result = FairnessAuditService.subgroup_rate_difference(
            y_pred=y_pred,
            group_a_mask=group_a_mask,
            group_b_mask=group_b_mask,
            threshold=threshold,
        )
        result["metric"] = "demographic_parity"
        return result
