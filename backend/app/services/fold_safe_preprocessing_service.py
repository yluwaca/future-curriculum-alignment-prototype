"""Training-window-only preprocessing for model validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

import numpy as np
import pandas as pd

from app.services.feature_engineering import FeatureEngineer


@dataclass(frozen=True)
class FittedFeatureFilter:
    input_columns: List[str]
    selected_columns: List[str]
    removed_columns: List[str]
    fit_row_count: int
    fit_matrix_hash: str
    method: str = "vif_lt_5_fit_on_training_rows_only"

    def evidence(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "input_columns": self.input_columns,
            "selected_columns": self.selected_columns,
            "removed_columns": self.removed_columns,
            "fit_row_count": self.fit_row_count,
            "fit_matrix_hash": self.fit_matrix_hash,
            "target_used": False,
        }


class FoldSafePreprocessingService:
    """Fit column filtering on training rows and apply it unchanged elsewhere."""

    # These source-evidence features carry the actual curriculum/labour
    # relationship. Pure VIF elimination can discard all of them in favour of
    # a document-length proxy when lexical counts are correlated. Retaining
    # non-constant semantic features is target-independent and remains fitted
    # entirely inside each training fold.
    SEMANTIC_FEATURES = (
        "shared_unique_token_count",
        "vocabulary_jaccard",
        "curriculum_vocabulary_coverage",
        "labour_vocabulary_coverage",
    )

    def fit(self, matrix: np.ndarray, columns: Iterable[str]) -> FittedFeatureFilter:
        input_columns = list(columns)
        frame = pd.DataFrame(np.asarray(matrix, dtype=float), columns=input_columns).fillna(0.0)
        if frame.empty:
            raise ValueError("Cannot fit preprocessing on an empty training window")
        filtered = FeatureEngineer.variance_inflation_factor(frame, threshold=5.0)
        selected = filtered.columns.tolist()
        for column in self.SEMANTIC_FEATURES:
            if column in frame.columns and float(frame[column].var()) > 1e-12 and column not in selected:
                selected.append(column)
        if not selected:
            variances = frame.var(axis=0).sort_values(ascending=False)
            selected = [str(variances.index[0])]
        return FittedFeatureFilter(
            input_columns=input_columns,
            selected_columns=selected,
            removed_columns=[column for column in input_columns if column not in selected],
            fit_row_count=int(len(frame)),
            fit_matrix_hash=hashlib.sha256(
                np.ascontiguousarray(frame[input_columns].values).tobytes()
            ).hexdigest(),
            method="vif_lt_5_plus_nonconstant_semantic_features_fit_on_training_rows_only",
        )

    @staticmethod
    def transform(matrix: np.ndarray, fitted: FittedFeatureFilter) -> np.ndarray:
        frame = pd.DataFrame(
            np.asarray(matrix, dtype=float),
            columns=fitted.input_columns,
        ).fillna(0.0)
        return frame[fitted.selected_columns].values


fold_safe_preprocessing_service = FoldSafePreprocessingService()
