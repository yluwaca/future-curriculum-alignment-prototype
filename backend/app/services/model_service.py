# backend/app/services/model_service.py

"""
Enterprise Predictive Model Service for FUTURE Platform.

Responsibilities:
- XGBoost training/inference
- LSTM forecasting
- SHAP explainability
- prediction persistence
- forecasting persistence
- model lineage
- reproducibility
- model governance

Aligned with:
- PostgreSQL schema
- SQLAlchemy 2.0
- SHAP explainability
- XGBoost
- LSTM forecasting
- FUTURE thesis architecture
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from datetime import datetime, timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np
import pandas as pd
import joblib
import shap
import tensorflow as tf
from tensorflow.keras.layers import Dense, Dropout, Input, LSTM
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.optimizers import Adam
import xgboost as xgb

from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import (
    train_test_split,
    TimeSeriesSplit,
)

from sqlalchemy.orm import Session

from app.models.curriculum_module import (
    CurriculumModule,
)
from app.models.job_posting import (
    JobPosting,
)
from app.models.predictive_output import (
    PredictiveOutput,
)

from app.services.etl_pipeline import (
    ETLPipeline,
)
from app.services.feature_engineering import (
    FeatureEngineer,
)

from app.services.fairness_audit_service import (
    FairnessAuditService,
)
from app.models.label_dataset_snapshot import LabelDatasetSnapshot
from app.services.reviewed_alignment_training_dataset_service import (
    reviewed_alignment_training_dataset_service,
)
from app.services.fold_safe_preprocessing_service import (
    fold_safe_preprocessing_service,
)
from app.services.model_evidence_service import model_evidence_service

from app.core.model_loader import (
    ModelLoadError,
    get_model_loader,
)

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)

# =========================================================
# Model Service
# =========================================================


class ModelService:
    """
    Enterprise predictive model service.
    """

    @staticmethod
    def classify_alignment_score(score: float, metrics: Dict[str, Any]) -> bool:
        """Classify with the operating point persisted beside the artifact."""
        contract = metrics.get("serving_feature_contract") or {}
        threshold = contract.get("operating_threshold")
        if not isinstance(threshold, (int, float)) or not 0.0 <= float(threshold) <= 1.0:
            raise ModelLoadError("Active XGBoost contract has no valid operating threshold")
        return float(score) >= float(threshold)

    # =====================================================
    # Initialization
    # =====================================================

    def __init__(
        self,
        model_dir: Optional[str] = None,
    ) -> None:

        self.model_loader = get_model_loader()

        self.model_dir = model_dir or str(self.model_loader.base_path)

        os.makedirs(
            self.model_dir,
            exist_ok=True,
        )

        self.feature_engineer = (
            FeatureEngineer()
        )

        self.etl_pipeline = (
            ETLPipeline()
        )

        self.xgboost_model: Optional[Any] = None

        self.lstm_model: Optional[Any] = None

        self.shap_explainer = None

        self.xgboost_loaded = False

        self.lstm_loaded = False

        self.xgboost_metrics: Dict[
            str,
            Any,
        ] = {}

        self.lstm_metrics: Dict[
            str,
            Any,
        ] = {}

        self.model_version = "1.0.0"

        self.feature_schema_version = "1.0.0"

        self.dataset_version = "2026.01"

        self._load_models()

        logger.info(
            "[MODEL] Model service initialized"
        )

    # =====================================================
    # Model Loading
    # =====================================================

    def _load_models(self) -> None:
        """
        Load persisted models from disk via ModelLoader.
        """

        # -------------------------------------------------
        # XGBoost
        # -------------------------------------------------

        try:
            self.xgboost_model = self.model_loader.load_xgboost()
            self.shap_explainer = shap.TreeExplainer(self.xgboost_model)
            self.xgboost_loaded = True
            logger.info("[MODEL] XGBoost model loaded via ModelLoader")
        except ModelLoadError as exc:
            logger.warning("[MODEL] Failed to load XGBoost model: %s", str(exc))

        # -------------------------------------------------
        # LSTM
        # -------------------------------------------------

        try:
            self.lstm_model = self.model_loader.load_lstm()
            self.lstm_loaded = True
            logger.info("[MODEL] LSTM model loaded via ModelLoader")
        except ModelLoadError as exc:
            logger.warning("[MODEL] Failed to load LSTM model: %s", str(exc))

        self._load_metrics()

    def prepare_artifact_activation(
        self,
        model_type: str,
        artifact_path: str,
    ) -> Dict[str, Any]:
        """
        Load and validate a registry artifact without changing the serving model.

        The returned object may be activated only after the registry transaction
        succeeds.  This keeps candidate evaluation isolated from live inference.
        """
        if not artifact_path or not os.path.isfile(artifact_path):
            raise ModelLoadError(f"Model artifact not found: {artifact_path}")

        if model_type == "xgboost":
            try:
                candidate_model = joblib.load(artifact_path)
                if not hasattr(candidate_model, "predict_proba"):
                    raise ModelLoadError(
                        "XGBoost artifact does not expose predict_proba"
                    )
                candidate_explainer = (
                    shap.TreeExplainer(candidate_model) if shap else None
                )
                return {
                    "model_type": model_type,
                    "model": candidate_model,
                    "explainer": candidate_explainer,
                    "artifact_path": artifact_path,
                }
            except ModelLoadError:
                raise
            except Exception as exc:
                raise ModelLoadError(
                    f"Unable to load XGBoost artifact: {exc}"
                ) from exc

        if model_type == "lstm":
            try:
                candidate_model = tf.keras.models.load_model(
                    artifact_path,
                    compile=True,
                )
                if not hasattr(candidate_model, "predict"):
                    raise ModelLoadError("LSTM artifact does not expose predict")
                return {
                    "model_type": model_type,
                    "model": candidate_model,
                    "explainer": None,
                    "artifact_path": artifact_path,
                }
            except ModelLoadError:
                raise
            except Exception as exc:
                raise ModelLoadError(
                    f"Unable to load LSTM artifact: {exc}"
                ) from exc

        raise ModelLoadError(f"Unsupported model type: {model_type}")

    def activate_prepared_artifact(self, prepared: Dict[str, Any]) -> None:
        """Atomically replace the in-process serving reference."""
        model_type = prepared.get("model_type")
        if model_type == "xgboost":
            self.xgboost_model = prepared["model"]
            self.shap_explainer = prepared.get("explainer")
            self.xgboost_metrics = dict(prepared.get("metrics") or {})
            self.xgboost_loaded = True
        elif model_type == "lstm":
            self.lstm_model = prepared["model"]
            self.lstm_loaded = True
        else:
            raise ModelLoadError(f"Unsupported model type: {model_type}")

        self.model_loader.clear_cache()
        if not hasattr(self, "active_registry_models"):
            self.active_registry_models = {}
        self.active_registry_models[model_type] = {
            "entry_id": prepared.get("registry_entry_id"),
            "model_version": prepared.get("model_version"),
            "artifact_path": prepared.get("artifact_path"),
        }
        logger.info(
            "[MODEL] Activated registry artifact for %s: %s",
            model_type,
            prepared.get("artifact_path"),
        )

    def capture_serving_state(self, model_type: str) -> Dict[str, Any]:
        """Capture the selected serving reference so a failed transaction can restore it."""
        if model_type == "xgboost":
            return {
                "model_type": model_type,
                "model": self.xgboost_model,
                "explainer": self.shap_explainer,
                "loaded": self.xgboost_loaded,
                "registry_identity": dict(
                    getattr(self, "active_registry_models", {}).get(model_type) or {}
                ),
                "metrics": dict(getattr(self, "xgboost_metrics", {}) or {}),
            }
        if model_type == "lstm":
            return {
                "model_type": model_type,
                "model": self.lstm_model,
                "explainer": None,
                "loaded": self.lstm_loaded,
                "registry_identity": dict(
                    getattr(self, "active_registry_models", {}).get(model_type) or {}
                ),
            }
        raise ModelLoadError(f"Unsupported model type: {model_type}")

    def restore_serving_state(self, state: Dict[str, Any]) -> None:
        """Restore a serving reference after an activation/commit failure."""
        model_type = state.get("model_type")
        if model_type == "xgboost":
            self.xgboost_model = state.get("model")
            self.shap_explainer = state.get("explainer")
            self.xgboost_metrics = dict(state.get("metrics") or {})
            self.xgboost_loaded = bool(state.get("loaded"))
        elif model_type == "lstm":
            self.lstm_model = state.get("model")
            self.lstm_loaded = bool(state.get("loaded"))
        else:
            raise ModelLoadError(f"Unsupported model type: {model_type}")
        if not hasattr(self, "active_registry_models"):
            self.active_registry_models = {}
        identity = state.get("registry_identity") or {}
        if identity:
            self.active_registry_models[model_type] = identity
        else:
            self.active_registry_models.pop(model_type, None)

    def clear_serving_models(self) -> None:
        """Fail closed until registry-designated active artifacts are restored."""
        self.xgboost_model = None
        self.lstm_model = None
        self.shap_explainer = None
        self.xgboost_loaded = False
        self.lstm_loaded = False
        self.xgboost_metrics = {}
        self.lstm_metrics = {}
        self.active_registry_models = {}
        self.active_registry_models: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def canary_prediction(prepared: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Run a deterministic zero-input canary without changing serving state."""
        model_type = prepared.get("model_type")
        model = prepared.get("model")
        if model_type == "xgboost":
            contract = metrics.get("serving_feature_contract") or {}
            feature_names = contract.get("selected_columns") or metrics.get("feature_names") or []
            if not feature_names:
                raise ModelLoadError("XGBoost canary requires recorded feature names")
            if contract:
                if contract.get("contract_id") != reviewed_alignment_training_dataset_service.FEATURE_CONTRACT_ID:
                    raise ModelLoadError("Unsupported XGBoost serving feature contract")
                threshold = contract.get("operating_threshold")
                if not isinstance(threshold, (int, float)) or not 0.0 <= float(threshold) <= 1.0:
                    raise ModelLoadError("XGBoost serving contract requires an operating threshold in [0, 1]")
            probability = np.asarray(
                model.predict_proba(np.zeros((1, len(feature_names)), dtype=float)),
                dtype=float,
            )
            output = probability.reshape(-1).tolist()
        elif model_type == "lstm":
            input_shape = getattr(model, "input_shape", None)
            if not input_shape or any(value is None for value in input_shape[1:]):
                raise ModelLoadError("LSTM canary requires a concrete recorded input shape")
            prediction = model.predict(
                np.zeros((1, *input_shape[1:]), dtype=float),
                verbose=0,
            )
            output = np.asarray(prediction, dtype=float).reshape(-1).tolist()
        else:
            raise ModelLoadError(f"Unsupported model type: {model_type}")
        payload = json.dumps(output, separators=(",", ":"), sort_keys=True)
        return {
            "status": "passed",
            "input_policy": "deterministic_zero_vector",
            "output": output,
            "output_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }

    # =====================================================
    # Metrics Loading
    # =====================================================

    def _load_metrics(self) -> None:
        """
        Load metrics from disk.
        """

        metrics_path = os.path.join(
            self.model_dir,
            "model_metrics.json",
        )

        if not os.path.exists(
            metrics_path
        ):

            return

        try:

            with open(
                metrics_path,
                "r",
                encoding="utf-8",
            ) as handle:

                metrics = json.load(
                    handle
                )

            self.xgboost_metrics = (
                metrics.get(
                    "xgboost",
                    {},
                )
            )

            self.lstm_metrics = (
                metrics.get(
                    "lstm",
                    {},
                )
            )

            logger.info(
                "[MODEL] Metrics loaded"
            )

        except Exception as exc:

            logger.warning(
                "[MODEL] Failed to load metrics: %s",
                str(exc),
            )

    # =====================================================
    # Metrics Persistence
    # =====================================================

    def _save_metrics(self) -> None:
        """
        Persist metrics to disk.
        Merges with existing file data so that training one model
        does not clobber metrics from the other model.
        """

        metrics_path = os.path.join(
            self.model_dir,
            "model_metrics.json",
        )

        existing: Dict[str, Any] = {}
        if os.path.exists(metrics_path):
            try:
                with open(
                    metrics_path, "r", encoding="utf-8"
                ) as handle:
                    existing = json.load(handle)
            except (json.JSONDecodeError, OSError):
                existing = {}

        if self.xgboost_metrics:
            existing["xgboost"] = self.xgboost_metrics
        elif "xgboost" not in existing:
            existing["xgboost"] = {}

        if self.lstm_metrics:
            existing["lstm"] = self.lstm_metrics
        elif "lstm" not in existing:
            existing["lstm"] = {}

        try:

            with open(
                metrics_path,
                "w",
                encoding="utf-8",
            ) as handle:

                json.dump(
                    existing,
                    handle,
                    indent=2,
                    default=str,
                )

            logger.info(
                "[MODEL] Metrics saved"
            )

        except Exception as exc:

            logger.warning(
                "[MODEL] Failed to save metrics: %s",
                str(exc),
            )

    # =====================================================
    # Prototype Inference Fallbacks
    # =====================================================

    def _run_heuristic_alignment(
        self,
        db: Session,
        curriculum_module_code: str,
        region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Produce explainable alignment output when no trained model exists.
        """

        curriculum = (
            db.query(CurriculumModule)
            .filter(
                CurriculumModule.module_code
                == curriculum_module_code
            )
            .first()
        )

        if not curriculum:
            raise ValueError(
                f"Curriculum module "
                f"{curriculum_module_code} "
                f"not found."
            )

        features, metadata = (
            self.feature_engineer
            .create_xgboost_features(
                db=db,
                curriculum=curriculum,
                region=region,
            )
        )

        gap_score = float(
            metadata.get(
                "gap_score",
                features.get("gap_score", 0.5),
            )
        )

        alignment_score = max(
            0.0,
            min(1.0, 1.0 - gap_score),
        )

        job_count = int(
            metadata.get(
                "num_job_postings_analyzed",
                0,
            )
        )

        confidence_score = min(
            0.95,
            0.55 + min(job_count, 100) / 250,
        )

        top_skills = metadata.get(
            "skill_demand_ranking",
            [],
        )

        identified_skills = metadata.get(
            "identified_skills",
            [],
        )

        shap_summary = [
            {
                "feature_name": "text_similarity_gap",
                "shap_value": round(
                    1.0 - gap_score,
                    4,
                ),
                "feature_value": round(
                    gap_score,
                    4,
                ),
            },
            {
                "feature_name": "job_postings_analyzed",
                "shap_value": round(
                    min(job_count, 100) / 100,
                    4,
                ),
                "feature_value": float(job_count),
            },
            {
                "feature_name": "curriculum_skills_identified",
                "shap_value": round(
                    min(len(identified_skills), 10) / 10,
                    4,
                ),
                "feature_value": float(len(identified_skills)),
            },
        ]

        prediction_record = PredictiveOutput(
            curriculum_module_code=curriculum.module_code,
            curriculum_nqf_level=curriculum.nqf_level,
            faculty=curriculum.faculty,
            model_type="heuristic_alignment",
            model_version=self.model_version,
            alignment_score=alignment_score,
            is_aligned=alignment_score >= 0.70,
            confidence_score=confidence_score,
            gap_score=gap_score,
            gap_flag=gap_score > 0.40,
            shap_summary=shap_summary,
            top_influencing_skills=top_skills,
            data_region=region,
            input_features_hash=metadata.get(
                "feature_hash",
            ),
            dataset_version=self.dataset_version,
        )

        db.add(prediction_record)
        db.commit()
        db.refresh(prediction_record)

        return {
            "prediction_id": prediction_record.prediction_id,
            "module_code": curriculum.module_code,
            "alignment_score": alignment_score,
            "is_aligned": alignment_score >= 0.70,
            "confidence_score": confidence_score,
            "gap_score": gap_score,
            "gap_flag": gap_score > 0.40,
            "shap_summary": shap_summary,
            "top_influencing_skills": top_skills,
            "prediction_timestamp": (
                prediction_record.prediction_timestamp
            ),
            "model_version": self.model_version,
            "dataset_version": self.dataset_version,
        }

    def _run_heuristic_forecast(
        self,
        db: Session,
        curriculum_module_code: str,
        forecast_horizon: int = 12,
        region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Produce demand forecast output when no trained LSTM exists.
        """

        curriculum = (
            db.query(CurriculumModule)
            .filter(
                CurriculumModule.module_code
                == curriculum_module_code
            )
            .first()
        )

        if not curriculum:
            raise ValueError(
                f"Curriculum module "
                f"{curriculum_module_code} "
                f"not found."
            )

        sequence, metadata = (
            self.feature_engineer
            .create_lstm_sequence_features(
                db=db,
                curriculum=curriculum,
                sequence_length=12,
                region=region,
            )
        )

        values = sequence.flatten()
        current = float(values[-1]) if len(values) else 0.0
        previous = float(values[-2]) if len(values) > 1 else current
        trend = current - previous

        forecast_trajectory = []

        for month in range(1, forecast_horizon + 1):
            predicted = float(
                np.clip(
                    current + (trend * month * 0.5),
                    0.0,
                    1.0,
                )
            )

            band = min(0.30, 0.10 + month * 0.01)

            forecast_trajectory.append(
                {
                    "month": month,
                    "predicted_demand": predicted,
                    "confidence_lower": max(
                        0.0,
                        predicted - band,
                    ),
                    "confidence_upper": min(
                        1.0,
                        predicted + band,
                    ),
                }
            )

        prediction_record = PredictiveOutput(
            curriculum_module_code=curriculum.module_code,
            curriculum_nqf_level=curriculum.nqf_level,
            faculty=curriculum.faculty,
            model_type="heuristic_forecast",
            model_version=self.model_version,
            forecast_horizon_months=forecast_horizon,
            forecast_data={
                "trajectory": forecast_trajectory,
                "identified_skills": metadata.get(
                    "identified_skills",
                    [],
                ),
            },
            forecast_rmse=None,
            forecast_mape=None,
            data_region=region,
            input_features_hash=metadata.get(
                "feature_hash",
            ),
            dataset_version=self.dataset_version,
        )

        db.add(prediction_record)
        db.commit()
        db.refresh(prediction_record)

        return {
            "prediction_id": prediction_record.prediction_id,
            "module_code": curriculum.module_code,
            "forecast_horizon_months": forecast_horizon,
            "forecast_trajectory": forecast_trajectory,
            "rmse": None,
            "mape": None,
            "prediction_timestamp": (
                prediction_record.prediction_timestamp
            ),
            "model_version": self.model_version,
            "dataset_version": self.dataset_version,
            "data_region": region,
        }

    # =====================================================
    # XGBoost Training
    # =====================================================

    @staticmethod
    def _lstm_observation_counts(db: Session) -> Dict[str, Any]:
        try:
            from app.models.cleaned_ingestion_record import CleanedIngestionRecord
            from app.models.job_posting import JobPosting
            from app.models.labour_market_signal import LabourMarketSignal
            from app.models.raw_ingestion_record import RawIngestionRecord
            from sqlalchemy import func as sql_func

            raw_count = int(db.query(sql_func.count(RawIngestionRecord.record_id)).scalar() or 0)
            cleaned_count = int(db.query(sql_func.count(CleanedIngestionRecord.cleaned_record_id)).scalar() or 0)
            posting_count = int(db.query(sql_func.count(JobPosting.posting_id)).scalar() or 0)
            signal_count = int(db.query(sql_func.count(LabourMarketSignal.signal_id)).scalar() or 0)
            signal_date_rows = (
                db.query(
                    sql_func.min(LabourMarketSignal.observed_at),
                    sql_func.max(LabourMarketSignal.observed_at),
                    sql_func.min(LabourMarketSignal.year),
                    sql_func.max(LabourMarketSignal.year),
                )
                .first()
            )
            return {
                "raw_ingestion_records": raw_count or 0,
                "cleaned_ingestion_records": cleaned_count or 0,
                "job_postings": posting_count or 0,
                "labour_market_signals": signal_count or 0,
                "signal_observed_range": (
                    [
                        (
                            signal_date_rows[0].isoformat() if signal_date_rows[0] else None
                        ),
                        (
                            signal_date_rows[1].isoformat() if signal_date_rows[1] else None
                        ),
                    ]
                ),
                "signal_year_range": (
                    [signal_date_rows[2], signal_date_rows[3]]
                    if signal_date_rows and signal_date_rows[2] is not None
                    else []
                ),
                "counts_note": "Observation context for the demand-scored time series used by this LSTM candidate; metrics alone are not comparable without this context.",
            }
        except Exception as exc:
            return {
                "counts_note": f"Observation counts unavailable during training context capture: {type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _group_safe_boundary(
        group_ids: List[str],
        target_index: int,
        lo: int,
        hi: int,
    ) -> Optional[int]:
        """Return an index in [lo, hi] closest to target where no source group crosses."""
        best = None
        best_distance = None
        for candidate in range(lo, hi + 1):
            left = set(group_ids[:candidate])
            if any(group_id in left for group_id in group_ids[candidate:]):
                continue
            distance = abs(candidate - target_index)
            if best_distance is None or distance < best_distance:
                best = candidate
                best_distance = distance
        return best

    @staticmethod
    def _chronological_group_folds(
        group_ids: List[str],
        requested_splits: int,
    ) -> List[tuple[np.ndarray, np.ndarray]]:
        """Expanding-window folds over chronologically ordered source groups.

        Records are already sorted by genuine evidence chronology by the
        reviewed-dataset service.  Whole source-version groups are assigned to
        contiguous time blocks so a group never crosses train/validation and
        validation always follows training.
        """
        ordered_groups = list(dict.fromkeys(group_ids))
        if len(ordered_groups) < 3:
            return []
        block_count = min(requested_splits + 1, len(ordered_groups))
        blocks = [list(block) for block in np.array_split(np.array(ordered_groups, dtype=object), block_count) if len(block)]
        folds: List[tuple[np.ndarray, np.ndarray]] = []
        for index in range(1, len(blocks)):
            train_groups = {str(value) for block in blocks[:index] for value in block}
            val_groups = {str(value) for value in blocks[index]}
            train_idx = np.array([i for i, value in enumerate(group_ids) if value in train_groups], dtype=int)
            val_idx = np.array([i for i, value in enumerate(group_ids) if value in val_groups], dtype=int)
            if len(train_idx) and len(val_idx):
                folds.append((train_idx, val_idx))
        return folds

    def train_xgboost_alignment_model(
        self,
        db: Session,
        label_snapshot_id: Any,
        hyperparams: Optional[
            Dict[str, Any]
        ] = None,
        test_size: float = 0.2,
    ) -> Dict[str, Any]:
        """
        Train an XGBoost alignment candidate with Phase 4 validation safeguards.

        The scientific target is a continuous curriculum-labour alignment score
        in [0, 1]. A binary aligned/not-aligned label is retained only for the
        operational decision requirement of prioritising human review. Its
        target threshold is selected by chronological validation sensitivity,
        not by a fixed cosine value or by blindly using the full-dataset median.
        """

        logger.info("[MODEL] Training Phase 4 XGBoost alignment candidate")

        if hyperparams is None:
            hyperparams = {
                "max_depth": 4,
                "learning_rate": 0.05,
                "n_estimators": 200,
                "objective": "binary:logistic",
                "eval_metric": "logloss",
                "random_state": 42,
                "scale_pos_weight": 1.0,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.1,
                "reg_lambda": 1.0,
                "min_child_weight": 3,
            }

        label_snapshot = db.query(LabelDatasetSnapshot).filter(
            LabelDatasetSnapshot.snapshot_id == label_snapshot_id,
            LabelDatasetSnapshot.lifecycle_state == "approved_locked",
        ).first()
        if not label_snapshot:
            raise RuntimeError("Approved locked reviewed-label snapshot was not found")
        training_dataset = reviewed_alignment_training_dataset_service.load(db, label_snapshot)

        X_raw: List[Dict[str, float]] = []
        y_continuous: List[float] = []
        faculty_values: List[str] = []
        group_ids: List[str] = []
        leakage_warnings: List[str] = []

        for record in training_dataset["records"]:
            X_raw.append(record["features"])
            y_continuous.append(record["continuous_target"])
            faculty_values.append(record["faculty"])
            group_ids.append(str(record.get("group_id") or record["task_id"]))

        if len(X_raw) < 10:
            dataset_mode = getattr(label_snapshot, "dataset_mode", "technical_uat_researcher_operated")
            if dataset_mode == "independent_expert_validation":
                raise RuntimeError(
                    "Locked reviewed-label snapshot contains fewer than 10 eligible rows; "
                    "collect more independent expert labels before training XGBoost."
                )
            raise RuntimeError(
                "Locked label snapshot contains fewer than 10 eligible rows; complete more "
                "researcher-operated UAT review tasks (technical_uat_researcher_operated) "
                "before experimental XGBoost candidate training."
            )

        raw_feature_names = sorted(set().union(*(f.keys() for f in X_raw)))
        X_raw_matrix = np.array(
            [[float(f.get(k, 0.0) or 0.0) for k in raw_feature_names] for f in X_raw]
        )
        y_score = np.array(y_continuous, dtype=float)

        logger.info(
            "[XGB] alignment continuous target: n=%d min=%.4f max=%.4f median=%.4f",
            len(y_score), float(y_score.min()), float(y_score.max()), float(np.median(y_score)),
        )

        if float(y_score.max() - y_score.min()) < 0.01:
            leakage_warnings.append(
                "Alignment target has very low variance; binary classification is not stable yet."
            )

        def safe_auc(y_true: np.ndarray, y_prob: np.ndarray) -> Optional[float]:
            try:
                if len(np.unique(y_true)) < 2:
                    return None
                value = roc_auc_score(y_true, y_prob)
                return None if np.isnan(value) else float(value)
            except Exception:
                return None

        def safe_pr_auc(y_true: np.ndarray, y_prob: np.ndarray) -> Optional[float]:
            try:
                if len(np.unique(y_true)) < 2:
                    return None
                value = average_precision_score(y_true, y_prob)
                return None if np.isnan(value) else float(value)
            except Exception:
                return None

        def safe_brier(y_true: np.ndarray, y_prob: np.ndarray) -> Optional[float]:
            try:
                return float(brier_score_loss(y_true, np.clip(y_prob, 0.0, 1.0)))
            except Exception:
                return None

        def evaluate_binary(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> Dict[str, Any]:
            y_pred = (y_prob >= threshold).astype(int)
            cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
            tn, fp, fn, tp = [int(v) for v in cm.ravel()]
            total = int(tn + fp + fn + tp)
            expected = int(len(y_true))
            return {
                "precision": float(precision_score(y_true, y_pred, zero_division=0)),
                "recall": float(recall_score(y_true, y_pred, zero_division=0)),
                "f1": float(f1_score(y_true, y_pred, zero_division=0)),
                "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
                "roc_auc": safe_auc(y_true, y_prob),
                "pr_auc": safe_pr_auc(y_true, y_prob),
                "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
                "brier_score": safe_brier(y_true, y_prob),
                "confusion_matrix": {
                    "true_negative": tn,
                    "false_positive": fp,
                    "false_negative": fn,
                    "true_positive": tp,
                    "total": total,
                    "expected_total": expected,
                    "denominator_check": total == expected,
                },
                "operating_threshold": float(threshold),
            }

        def model_params(y_train_local: np.ndarray) -> Dict[str, Any]:
            params = dict(hyperparams)
            n_pos = int(y_train_local.sum())
            n_neg = int(len(y_train_local) - n_pos)
            if n_pos > 0 and n_neg > 0:
                params["scale_pos_weight"] = n_neg / n_pos
            return params

        target_thresholds = [round(float(v), 2) for v in np.arange(0.35, 0.86, 0.05)]
        cv_splits = min(5, max(2, len(X_raw_matrix) // 12))
        distinct_groups = len(set(group_ids))
        if distinct_groups < cv_splits:
            cv_splits = max(2, distinct_groups)
        group_fold_splits = self._chronological_group_folds(group_ids, cv_splits)
        if len(group_fold_splits) < 2:
            raise RuntimeError(
                "At least three chronologically ordered curriculum source-version groups are required "
                "for expanding-window grouped validation."
            )
        threshold_sensitivity: List[Dict[str, Any]] = []

        for target_threshold in target_thresholds:
            y_candidate = (y_score >= target_threshold).astype(int)
            fold_rows = []
            fold_f1s = []
            fold_aucs = []
            if len(np.unique(y_candidate)) < 2:
                threshold_sensitivity.append({
                    "target_threshold": float(target_threshold),
                    "status": "rejected_single_class",
                    "positive_rate": float(y_candidate.mean()) if len(y_candidate) else 0.0,
                    "folds": [],
                    "mean_f1": 0.0,
                    "std_f1": 0.0,
                    "worst_f1": 0.0,
                    "mean_roc_auc": None,
                })
                continue

            for fold_idx, (train_idx, val_idx) in enumerate(group_fold_splits):
                fold_preprocessor = fold_safe_preprocessing_service.fit(
                    X_raw_matrix[train_idx],
                    raw_feature_names,
                )
                X_train_fold = fold_safe_preprocessing_service.transform(
                    X_raw_matrix[train_idx],
                    fold_preprocessor,
                )
                X_val_fold = fold_safe_preprocessing_service.transform(
                    X_raw_matrix[val_idx],
                    fold_preprocessor,
                )
                y_train_fold, y_val_fold = y_candidate[train_idx], y_candidate[val_idx]
                if len(np.unique(y_train_fold)) < 2 or len(np.unique(y_val_fold)) < 2:
                    fold_rows.append({
                        "fold": fold_idx + 1,
                        "status": "skipped_single_class",
                        "train_size": int(len(train_idx)),
                        "test_size": int(len(val_idx)),
                        "preprocessing": fold_preprocessor.evidence(),
                    })
                    continue

                fold_model = xgb.XGBClassifier(**model_params(y_train_fold))
                fold_model.fit(X_train_fold, y_train_fold, verbose=False)
                fold_prob = fold_model.predict_proba(X_val_fold)[:, 1]
                fold_metrics = evaluate_binary(y_val_fold, fold_prob, 0.5)
                fold_rows.append({
                    "fold": fold_idx + 1,
                    "status": "evaluated",
                    "train_size": int(len(train_idx)),
                    "test_size": int(len(val_idx)),
                    "train_groups": len({group_ids[int(i)] for i in train_idx}),
                    "val_groups": len({group_ids[int(i)] for i in val_idx}),
                    "group_disjoint": bool(
                        set(group_ids[int(i)] for i in train_idx)
                        & set(group_ids[int(i)] for i in val_idx)
                    ) is False,
                    "temporal_order_preserved": bool(max(train_idx) < min(val_idx)),
                    "preprocessing": fold_preprocessor.evidence(),
                    **fold_metrics,
                })
                fold_f1s.append(fold_metrics["f1"])
                if fold_metrics["roc_auc"] is not None:
                    fold_aucs.append(fold_metrics["roc_auc"])

            threshold_sensitivity.append({
                "target_threshold": float(target_threshold),
                "status": "evaluated" if fold_f1s else "insufficient_fold_classes",
                "positive_rate": float(y_candidate.mean()),
                "folds": fold_rows,
                "mean_f1": float(np.mean(fold_f1s)) if fold_f1s else 0.0,
                "std_f1": float(np.std(fold_f1s)) if fold_f1s else 0.0,
                "worst_f1": float(np.min(fold_f1s)) if fold_f1s else 0.0,
                "mean_roc_auc": float(np.mean(fold_aucs)) if fold_aucs else None,
            })

        viable_thresholds = [r for r in threshold_sensitivity if r["status"] == "evaluated"]
        if not viable_thresholds:
            raise RuntimeError("Unable to derive a two-class alignment target from current data.")

        selected_target = max(
            viable_thresholds,
            key=lambda r: (r["mean_f1"], r["worst_f1"], -abs(r["positive_rate"] - 0.5)),
        )
        threshold = float(selected_target["target_threshold"])
        y = (y_score >= threshold).astype(int)

        split_idx = int(len(X_raw_matrix) * (1.0 - test_size))
        split_idx = min(max(split_idx, 4), len(X_raw_matrix) - 2)
        desired_train_end = max(2, split_idx - max(1, int(split_idx * 0.15)))
        group_safe_split = self._group_safe_boundary(group_ids, split_idx, lo=4, hi=len(X_raw_matrix) - 2)
        if group_safe_split is not None:
            split_idx = group_safe_split
        else:
            leakage_warnings.append(
                "Holdout boundary could not be made group-safe without sacrificing required splits; "
                "kept the chronological boundary and recorded this leakage risk."
            )
        val_size = max(1, int(split_idx * 0.15))
        train_end = max(2, split_idx - val_size)
        group_safe_train_end = self._group_safe_boundary(
            group_ids[:split_idx], desired_train_end, lo=2, hi=split_idx - 1
        )
        if group_safe_train_end is not None:
            train_end = group_safe_train_end
        else:
            leakage_warnings.append(
                "Validation boundary could not be made group-safe without lost class coverage; kept the chronological boundary."
            )

        final_validation_preprocessor = fold_safe_preprocessing_service.fit(
            X_raw_matrix[:train_end],
            raw_feature_names,
        )
        X_train = fold_safe_preprocessing_service.transform(
            X_raw_matrix[:train_end],
            final_validation_preprocessor,
        )
        X_val = fold_safe_preprocessing_service.transform(
            X_raw_matrix[train_end:split_idx],
            final_validation_preprocessor,
        )
        y_train, y_val, y_test = y[:train_end], y[train_end:split_idx], y[split_idx:]
        y_score_test = y_score[split_idx:]

        if len(np.unique(y_train)) < 2:
            raise RuntimeError("Training split has a single alignment class; collect more labelled/mapped data before training XGBoost.")
        if len(np.unique(y_val)) < 2 or len(np.unique(y_test)) < 2:
            leakage_warnings.append(
                "Validation or holdout split has a single class; AUC-style metrics may be unavailable until more evidence exists."
            )

        validation_model = xgb.XGBClassifier(**model_params(y_train))
        validation_model.fit(X_train, y_train, verbose=False)
        val_prob = validation_model.predict_proba(X_val)[:, 1]
        operating_threshold_results = []
        for op_threshold in [round(float(v), 2) for v in np.arange(0.25, 0.76, 0.05)]:
            operating_threshold_results.append({
                "threshold": float(op_threshold),
                **evaluate_binary(y_val, val_prob, op_threshold),
            })
        selected_operating_row = max(
            operating_threshold_results,
            key=lambda r: (r["f1"], r["balanced_accuracy"], r["recall"]),
        )
        operating_threshold = float(selected_operating_row["threshold"])

        candidate_preprocessor = fold_safe_preprocessing_service.fit(
            X_raw_matrix[:split_idx],
            raw_feature_names,
        )
        X_train_final = fold_safe_preprocessing_service.transform(
            X_raw_matrix[:split_idx],
            candidate_preprocessor,
        )
        X_test = fold_safe_preprocessing_service.transform(
            X_raw_matrix[split_idx:],
            candidate_preprocessor,
        )
        all_keys = candidate_preprocessor.selected_columns
        y_train_final = np.concatenate([y_train, y_val])
        final_params = model_params(y_train_final)
        candidate_xgboost_model = xgb.XGBClassifier(**final_params)
        candidate_xgboost_model.fit(X_train_final, y_train_final, verbose=False)

        candidate_shap_explainer = (
            shap.TreeExplainer(candidate_xgboost_model) if shap else None
        )

        shap_global_summary = []
        try:
            if candidate_shap_explainer is not None and len(X_train_final):
                sample_size = min(100, len(X_train_final))
                shap_values = candidate_shap_explainer.shap_values(
                    X_train_final[:sample_size]
                )
                shap_array = shap_values[1] if isinstance(shap_values, list) and len(shap_values) > 1 else shap_values
                shap_array = np.asarray(shap_array)
                if shap_array.ndim == 3:
                    shap_array = shap_array[:, :, -1]
                mean_abs = np.mean(np.abs(shap_array), axis=0)
                for idx in np.argsort(mean_abs)[::-1][:15]:
                    shap_global_summary.append({
                        "feature_name": all_keys[int(idx)],
                        "mean_abs_shap": float(mean_abs[int(idx)]),
                    })
        except Exception as exc:
            logger.warning("[XGB] Global SHAP summary failed: %s", str(exc))

        y_pred_proba = candidate_xgboost_model.predict_proba(X_test)[:, 1]
        holdout_metrics = evaluate_binary(y_test, y_pred_proba, operating_threshold)
        calibration_evidence = model_evidence_service.classification_calibration(
            y_test,
            y_pred_proba,
        )

        baseline_results: Dict[str, Any] = {}
        try:
            from sklearn.dummy import DummyClassifier
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler

            lr_validation_model = make_pipeline(
                StandardScaler(),
                LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42),
            )
            lr_validation_model.fit(X_train, y_train)
            lr_val_proba = lr_validation_model.predict_proba(X_val)[:, 1]
            lr_threshold_rows = [
                {"threshold": value, **evaluate_binary(y_val, lr_val_proba, value)}
                for value in [round(float(v), 2) for v in np.arange(0.25, 0.76, 0.05)]
            ]
            lr_threshold = float(max(
                lr_threshold_rows,
                key=lambda row: (row["f1"], row["balanced_accuracy"], row["recall"]),
            )["threshold"])
            lr_model = make_pipeline(
                StandardScaler(),
                LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42),
            )
            lr_model.fit(X_train_final, y_train_final)
            lr_proba = lr_model.predict_proba(X_test)[:, 1]
            baseline_results["logistic_regression"] = evaluate_binary(y_test, lr_proba, lr_threshold)

            baseline_results["logistic_regression"]["eligible_for_promotion_comparison"] = True
            baseline_results["logistic_regression"]["threshold_selection"] = "own_training_validation_rows_only"

            train_feature_mean = X_train_final.mean(axis=1) if X_train_final.size else np.array([])
            test_feature_mean = X_test.mean(axis=1) if X_test.size else np.array([])
            if train_feature_mean.size and float(train_feature_mean.max() - train_feature_mean.min()) > 1e-9:
                train_min = float(train_feature_mean.min())
                train_range = float(train_feature_mean.max() - train_min)
                rules_proba = np.clip((test_feature_mean - train_min) / train_range, 0.0, 1.0)
            else:
                rules_proba = np.full(len(y_test), float(y_train_final.mean()))
            validation_train_mean = X_train.mean(axis=1) if X_train.size else np.array([])
            validation_mean = X_val.mean(axis=1) if X_val.size else np.array([])
            if validation_train_mean.size and float(validation_train_mean.max() - validation_train_mean.min()) > 1e-9:
                validation_min = float(validation_train_mean.min())
                validation_range = float(validation_train_mean.max() - validation_min)
                rules_val_proba = np.clip((validation_mean - validation_min) / validation_range, 0.0, 1.0)
            else:
                rules_val_proba = np.full(len(y_val), float(y_train.mean()))
            rules_threshold_rows = [
                {"threshold": value, **evaluate_binary(y_val, rules_val_proba, value)}
                for value in [round(float(v), 2) for v in np.arange(0.25, 0.76, 0.05)]
            ]
            rules_threshold = float(max(
                rules_threshold_rows,
                key=lambda row: (row["f1"], row["balanced_accuracy"], row["recall"]),
            )["threshold"])
            baseline_results["simple_rules_feature_mean"] = {
                **evaluate_binary(y_test, rules_proba, rules_threshold),
                "eligible_for_promotion_comparison": True,
                "normalisation_fit": "nonholdout_training_rows_only",
                "threshold_selection": "own_training_validation_rows_only",
            }

            majority = DummyClassifier(strategy="most_frequent", random_state=42)
            majority.fit(X_train_final, y_train_final)
            majority_proba = majority.predict_proba(X_test)[:, 1]
            baseline_results["majority_class"] = evaluate_binary(y_test, majority_proba, 0.5)
            baseline_results["majority_class"]["eligible_for_promotion_comparison"] = True
        except Exception as exc:
            logger.warning("[XGB] Baseline comparison failed: %s", exc)
            baseline_results["error"] = str(exc)

        importances = getattr(
            candidate_xgboost_model,
            "feature_importances_",
            np.array([]),
        )
        top_features = []
        if len(importances):
            for idx in np.argsort(importances)[::-1][:15]:
                top_features.append({
                    "feature": all_keys[int(idx)],
                    "importance": float(importances[int(idx)]),
                })

        selected_cv_folds = [f for f in selected_target.get("folds", []) if f.get("status") == "evaluated"]
        f1_values = [float(f["f1"]) for f in selected_cv_folds]
        auc_values = [float(f["roc_auc"]) for f in selected_cv_folds if f.get("roc_auc") is not None]
        pr_auc_values = [float(f["pr_auc"]) for f in selected_cv_folds if f.get("pr_auc") is not None]
        brier_values = [float(f["brier_score"]) for f in selected_cv_folds if f.get("brier_score") is not None]

        positive_rate = float(y.mean())
        if positive_rate < 0.2 or positive_rate > 0.8:
            leakage_warnings.append(f"Class imbalance after threshold selection: positive rate {positive_rate:.2f}.")
        leakage_warnings.append(
            "Review ESCO/OFO mapping confidence as an input feature; it must not become a hidden label proxy."
        )
        if training_dataset["undated_row_count"]:
            leakage_warnings.append(
                f"{training_dataset['undated_row_count']} reviewed rows lack usable evidence dates; "
                "their locked row order was used for validation ordering."
            )

        model_version_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        versioned_path = os.path.join(self.model_dir, f"xgboost_{model_version_stamp}.pkl")
        joblib.dump(candidate_xgboost_model, versioned_path)

        fingerprint_hasher = hashlib.sha256()
        fingerprint_hasher.update(np.ascontiguousarray(X_train_final).tobytes())
        fingerprint_hasher.update(np.ascontiguousarray(X_test).tobytes())
        fingerprint_hasher.update(np.ascontiguousarray(y_score).tobytes())
        fingerprint_hasher.update(
            json.dumps(
                {
                    "feature_shape": [
                        int(len(X_raw_matrix)),
                        int(len(candidate_preprocessor.selected_columns)),
                    ],
                    "target_rows": int(len(y)),
                    "continuous_target_min": float(y_score.min()),
                    "continuous_target_max": float(y_score.max()),
                    "selected_target_threshold": threshold,
                    "operating_threshold": operating_threshold,
                    "positive_targets": int(np.sum(y)),
                    "feature_names": all_keys,
                    "split_policy": "expanding_window_chronological_source_groups_plus_group_safe_holdout",
                    "cv_strategy": "expanding_window_chronological_source_groups",
                    "random_state": hyperparams.get("random_state"),
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        training_matrix_fingerprint = fingerprint_hasher.hexdigest()
        dataset_fingerprint = training_dataset["dataset_fingerprint"]

        self.xgboost_metrics = {
            "trained": True,
            "phase": "phase4_alignment_validation",
            "f1_score": holdout_metrics["f1"],
            "precision": holdout_metrics["precision"],
            "recall": holdout_metrics["recall"],
            "roc_auc": holdout_metrics["roc_auc"],
            "pr_auc": holdout_metrics["pr_auc"],
            "balanced_accuracy": holdout_metrics["balanced_accuracy"],
            "brier_score": holdout_metrics["brier_score"],
            "calibration_evidence": calibration_evidence,
            "confusion_matrix": holdout_metrics["confusion_matrix"],
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "training_samples": int(len(X_train_final)),
            "validation_samples": int(len(X_val)),
            "test_samples": int(len(X_test)),
            "model_version": self.model_version,
            "candidate_artifact": versioned_path,
            "model_path": versioned_path,
            "dataset_fingerprint": dataset_fingerprint,
            "training_matrix_fingerprint": training_matrix_fingerprint,
            "reviewed_label_snapshot_id": training_dataset["snapshot_id"],
            "reviewed_label_snapshot_version": training_dataset["snapshot_version"],
            "training_data_contract": training_dataset["feature_contract"],
            "training_ordering_policy": training_dataset["ordering_policy"],
            "preprocessing_evidence": {
                "cross_validation": "fitted independently on each fold training window",
                "operating_threshold_validation": final_validation_preprocessor.evidence(),
                "candidate_fit": candidate_preprocessor.evidence(),
                "holdout_rows_used_during_fit": 0,
                "holdout_transform_only": True,
            },
            "feature_names": all_keys,
            "serving_feature_contract": {
                "contract_id": reviewed_alignment_training_dataset_service.FEATURE_CONTRACT_ID,
                "contract_version": 1,
                "input_columns": list(candidate_preprocessor.input_columns),
                "selected_columns": list(candidate_preprocessor.selected_columns),
                "removed_columns": list(candidate_preprocessor.removed_columns),
                "missing_feature_policy": "zero",
                "operating_threshold": operating_threshold,
            },
            "feature_importance": top_features,
            "explainability": {
                "status": "passed" if shap_global_summary else "insufficient_data",
                "method": "TreeSHAP global and local feature attribution",
                "global_shap_summary": shap_global_summary,
                "background_sample_count": int(min(100, len(X_train_final))),
                "local_explanations_available": bool(candidate_shap_explainer),
                "feature_labels_verified": bool(all_keys),
                "limitations": [
                    "SHAP values explain this candidate model only and must be reviewed with source evidence.",
                    "Local TreeSHAP explanations use the same feature schema as the global attribution.",
                    "Explanation labels are generated from the model feature schema recorded with the candidate.",
                    "Human curriculum review remains central before recommendations are acted on.",
                ],
            },
            "target_definition": {
                "continuous_target": "immutable reviewed snapshot label transformed as (final_alignment_label - 1) / 4",
                "binary_target": "operational aligned/not-aligned label for review prioritisation only",
                "target_threshold_selection": "Expanding-window chronological source-group sensitivity over 0.35-0.85; selected by mean F1, worst-fold F1 and class balance",
                "selected_target_threshold": threshold,
                "fixed_cosine_0_75_rejected": True,
                "full_dataset_median_rejected": True,
            },
            "cv_strategy": "expanding_window_chronological_source_groups",
            "cv_distinct_source_groups": int(distinct_groups),
            "cv_group_isolation": "expanding chronological windows; source versions never cross train and validation folds; validation groups always follow training groups",
            "chronology_evidence": {
                "ordering_policy": training_dataset["ordering_policy"],
                "dated_rows": training_dataset["dated_row_count"],
                "undated_rows": training_dataset["undated_row_count"],
                "distinct_values": training_dataset["distinct_chronology_values"],
                "range": training_dataset["chronology_range"],
            },
            "cv_folds": [
                {
                    "fold": fold_number,
                    "train_rows": int(len(train_indexes)),
                    "val_rows": int(len(val_indexes)),
                }
                for fold_number, (train_indexes, val_indexes) in enumerate(group_fold_splits, start=1)
            ],
            "threshold": threshold,
            "threshold_method": "group_cv_sensitivity_selected",
            "operating_threshold": operating_threshold,
            "operating_threshold_objective": "maximise validation F1, then balanced accuracy, then recall",
            "threshold_sensitivity": threshold_sensitivity,
            "validation_threshold_sensitivity": operating_threshold_results,
            "timeseries_cv_folds": selected_cv_folds,
            "cv_fold_metrics": selected_cv_folds,
            "cv_mean_f1": float(np.mean(f1_values)) if f1_values else None,
            "cv_std_f1": float(np.std(f1_values)) if f1_values else None,
            "cv_worst_f1": float(np.min(f1_values)) if f1_values else None,
            "cv_mean_roc_auc": float(np.mean(auc_values)) if auc_values else None,
            "cv_mean_pr_auc": float(np.mean(pr_auc_values)) if pr_auc_values else None,
            "cv_mean_brier_score": float(np.mean(brier_values)) if brier_values else None,
            "class_balance": {
                "positive": int(np.sum(y)),
                "negative": int(len(y) - np.sum(y)),
                "positive_rate": positive_rate,
            },
            "baseline_comparisons": baseline_results,
            "baselines": baseline_results,
            "leakage_risks": leakage_warnings,
            "leakage_note": "Cross-validation uses expanding chronological source-group windows: source versions never cross train and validation folds and every validation group follows its training groups. Holdout and validation boundaries are nudged to group-safe boundaries when possible. VIF filtering, class weighting and each baseline threshold are fitted independently inside training/validation windows; holdout rows are transform-only.",
            "promotion_gate": {
                "status": "blocked_pending_full_validation",
                "reason": "Phase 4 produces an evaluated candidate only; do not promote from one favourable holdout split.",
            },
        }

        try:
            fairness_svc = FairnessAuditService(db)
            fairness_records = [
                {
                    "faculty": faculty_values[min(i + split_idx, len(faculty_values) - 1)] or "unknown",
                    "alignment_score": float(score),
                }
                for i, score in enumerate(y_pred_proba)
            ]
            fairness_result = fairness_svc.audit_alignment_predictions(fairness_records, threshold=0.1)
            self.xgboost_metrics["fairness_audit"] = fairness_result
            self.xgboost_metrics["fairness_blocked"] = fairness_result.get("status") in {"flagged", "review_required"}
        except Exception as exc:
            logger.warning("[XGB] Fairness audit failed: %s", str(exc))
            self.xgboost_metrics["fairness_audit"] = {"status": "not_available", "reason": str(exc)}
            self.xgboost_metrics["fairness_blocked"] = True

        metadata = {
            "model_type": "xgboost",
            "version": model_version_stamp,
            "lifecycle_state": "candidate",
            "active_model_updated": False,
            "promotion_required": True,
            "training_date": datetime.now(timezone.utc).isoformat(),
            "dataset_fingerprint": dataset_fingerprint,
            "training_matrix_fingerprint": training_matrix_fingerprint,
            "reviewed_label_snapshot_id": training_dataset["snapshot_id"],
            "reviewed_label_snapshot_version": training_dataset["snapshot_version"],
            "training_data_contract": training_dataset["feature_contract"],
            "preprocessing_evidence": self.xgboost_metrics["preprocessing_evidence"],
            "target_definition": self.xgboost_metrics["target_definition"],
            "dataset_snapshot": {
                "feature_rows": int(len(X_raw_matrix)),
                "feature_columns": int(len(candidate_preprocessor.selected_columns)),
                "target_rows": int(len(y)),
                "positive_targets": int(np.sum(y)),
                "negative_targets": int(len(y) - np.sum(y)),
                "split_policy": "chronological_threshold_sensitivity_validation_holdout",
                "final_test_size": float(test_size),
            },
            "validation_metrics": {
                "precision": holdout_metrics["precision"],
                "recall": holdout_metrics["recall"],
                "f1_score": holdout_metrics["f1"],
                "roc_auc": holdout_metrics["roc_auc"],
                "pr_auc": holdout_metrics["pr_auc"],
                "balanced_accuracy": holdout_metrics["balanced_accuracy"],
                "brier_score": holdout_metrics["brier_score"],
                "confusion_matrix": holdout_metrics["confusion_matrix"],
            },
            "baselines": baseline_results,
            "explainability": self.xgboost_metrics.get("explainability", {}),
            "threshold_sensitivity": threshold_sensitivity,
            "training_samples": int(len(X_train_final)),
            "validation_samples": int(len(X_val)),
            "test_samples": int(len(X_test)),
            "hyperparams": final_params,
            "promotion_gate": self.xgboost_metrics["promotion_gate"],
        }
        meta_path = os.path.join(self.model_dir, f"xgboost_{model_version_stamp}_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, default=str)

        self._save_metrics()

        logger.info(
            "[MODEL] Phase 4 XGBoost candidate complete (f1=%s roc_auc=%s target_threshold=%s operating_threshold=%s)",
            round(holdout_metrics["f1"], 4),
            None if holdout_metrics["roc_auc"] is None else round(holdout_metrics["roc_auc"], 4),
            threshold,
            operating_threshold,
        )

        return self.xgboost_metrics

    # =====================================================
    # LSTM Training
    # =====================================================

    def train_lstm_forecast_model(
        self,
        db: Session,
        sequence_length: int = 12,
        epochs: int = 15,
        batch_size: int = 16,
    ) -> Dict[str, Any]:
        """
        Train an LSTM forecast candidate with Phase 5 walk-forward validation.

        The LSTM remains experimental unless the available time series is long
        enough and it beats transparent forecasting baselines with stable folds.
        Scaling is fitted within each training fold only and then applied to
        validation/holdout data to avoid future-period leakage.
        """

        logger.info("[MODEL] Training Phase 5 LSTM forecast candidate")

        curricula = (
            db.query(CurriculumModule)
            .filter(
                CurriculumModule.is_active.is_(True),
                CurriculumModule.data_source != "synthetic_training",
            )
            .order_by(CurriculumModule.created_at.asc(), CurriculumModule.module_id.asc())
            .all()
        )

        X_sequences: List[np.ndarray] = []
        y_targets: List[float] = []

        for curriculum in curricula[:600]:
            sequence, _ = self.feature_engineer.create_lstm_sequence_features(
                db=db,
                curriculum=curriculum,
                sequence_length=sequence_length,
            )
            flattened = sequence.flatten().astype(float)
            if len(flattened) <= 1:
                continue
            X_sequences.append(flattened[:-1].reshape(sequence_length - 1, 1))
            y_targets.append(float(flattened[-1]))

        if len(X_sequences) < 5:
            raise RuntimeError("Insufficient LSTM training data.")

        X_sequences = np.array(X_sequences, dtype=float)
        y_targets = np.array(y_targets, dtype=float)

        def build_lstm_model() -> Sequential:
            model = Sequential([
                Input(shape=(sequence_length - 1, 1)),
                LSTM(64, activation="relu", return_sequences=True),
                Dropout(0.2),
                LSTM(32, activation="relu"),
                Dense(1),
            ])
            model.compile(optimizer=Adam(learning_rate=0.001), loss="mse")
            return model

        def fit_scaler(X_train_local: np.ndarray, y_train_local: np.ndarray) -> Tuple[float, float]:
            values = np.concatenate([X_train_local.reshape(-1), y_train_local.reshape(-1)])
            min_value = float(np.min(values))
            max_value = float(np.max(values))
            if abs(max_value - min_value) < 1e-9:
                max_value = min_value + 1.0
            return min_value, max_value

        def scale_values(values: np.ndarray, min_value: float, max_value: float) -> np.ndarray:
            return (values - min_value) / (max_value - min_value)

        def inverse_scale(values: np.ndarray, min_value: float, max_value: float) -> np.ndarray:
            return values * (max_value - min_value) + min_value

        def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, Any]:
            y_true = np.asarray(y_true, dtype=float).reshape(-1)
            y_pred = np.asarray(y_pred, dtype=float).reshape(-1)
            error = y_true - y_pred
            rmse_value = float(np.sqrt(np.mean(error ** 2)))
            mae_value = float(np.mean(np.abs(error)))
            denom = np.abs(y_true) + np.abs(y_pred)
            smape_value = float(np.mean(2.0 * np.abs(error) / (denom + 1e-8)) * 100)
            safe_mask = np.abs(y_true) > 1e-8
            mape_value = float(np.mean(np.abs(error[safe_mask] / y_true[safe_mask])) * 100) if np.any(safe_mask) else None
            direction_true = np.sign(np.diff(y_true)) if len(y_true) > 1 else np.array([])
            direction_pred = np.sign(np.diff(y_pred)) if len(y_pred) > 1 else np.array([])
            direction_accuracy = float(np.mean(direction_true == direction_pred)) if len(direction_true) else None
            return {
                "rmse": rmse_value,
                "mae": mae_value,
                "smape": smape_value,
                "mape": mape_value,
                "direction_accuracy": direction_accuracy,
            }

        def baseline_predictions(X_eval: np.ndarray) -> Dict[str, np.ndarray]:
            series = X_eval[:, :, 0]
            last_value = series[:, -1]
            moving_average = np.array([np.mean(row[-min(3, len(row)):]) for row in series])
            expanding_average = np.array([np.mean(row) for row in series])
            seasonal_lag = series[:, -min(12, series.shape[1])] if series.shape[1] >= 2 else last_value
            exp_smoothing = []
            for row in series:
                level = float(row[0])
                alpha = 0.3
                for value in row[1:]:
                    level = alpha * float(value) + (1.0 - alpha) * level
                exp_smoothing.append(level)
            linear_trend = []
            for row in series:
                try:
                    xs = np.arange(len(row))
                    coeffs = np.polyfit(xs, row, 1)
                    linear_trend.append(float(np.polyval(coeffs, len(row))))
                except Exception:
                    linear_trend.append(float(row[-1]))
            return {
                "naive_last_value": last_value,
                "seasonal_naive_lag": seasonal_lag,
                "moving_average_w3": moving_average,
                "expanding_average": expanding_average,
                "exponential_smoothing_alpha_0_3": np.array(exp_smoothing),
                "linear_trend": np.array(linear_trend),
            }

        cv_splits = min(5, max(2, len(X_sequences) // 12))
        tscv = TimeSeriesSplit(n_splits=cv_splits)
        walk_forward_folds: List[Dict[str, Any]] = []
        fold_baselines: Dict[str, List[Dict[str, Any]]] = {}

        for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X_sequences)):
            X_train_fold, X_test_fold = X_sequences[train_idx], X_sequences[test_idx]
            y_train_fold, y_test_fold = y_targets[train_idx], y_targets[test_idx]
            min_value, max_value = fit_scaler(X_train_fold, y_train_fold)
            X_train_scaled = scale_values(X_train_fold, min_value, max_value)
            y_train_scaled = scale_values(y_train_fold, min_value, max_value)
            X_test_scaled = scale_values(X_test_fold, min_value, max_value)

            fold_model = build_lstm_model()
            fold_model.fit(X_train_scaled, y_train_scaled, epochs=epochs, batch_size=batch_size, verbose=0)
            fold_scaled_pred = fold_model.predict(X_test_scaled, verbose=0).flatten()
            fold_preds = inverse_scale(fold_scaled_pred, min_value, max_value)
            fold_metrics = regression_metrics(y_test_fold, fold_preds)

            baselines = baseline_predictions(X_test_fold)
            baseline_metrics = {name: regression_metrics(y_test_fold, preds) for name, preds in baselines.items()}
            for name, row in baseline_metrics.items():
                fold_baselines.setdefault(name, []).append(row)

            walk_forward_folds.append({
                "fold": fold_idx + 1,
                "validation_type": "expanding_window_walk_forward",
                "rmse": fold_metrics["rmse"],
                "mae": fold_metrics["mae"],
                "smape": fold_metrics["smape"],
                "mape": fold_metrics["mape"],
                "direction_accuracy": fold_metrics["direction_accuracy"],
                "train_size": int(len(train_idx)),
                "test_size": int(len(test_idx)),
                "scaling": "minmax_fitted_on_training_fold_only",
                "baselines": baseline_metrics,
            })
            logger.info(
                "[LSTM-WALK] Fold %d: RMSE=%.4f MAE=%.4f SMAPE=%.2f%% (train=%d test=%d)",
                fold_idx + 1,
                fold_metrics["rmse"],
                fold_metrics["mae"],
                fold_metrics["smape"],
                len(train_idx),
                len(test_idx),
            )

        split_idx = int(len(X_sequences) * 0.8)
        split_idx = min(max(split_idx, 2), len(X_sequences) - 1)
        X_train = X_sequences[:split_idx]
        X_test = X_sequences[split_idx:]
        y_train = y_targets[:split_idx]
        y_test = y_targets[split_idx:]
        min_value, max_value = fit_scaler(X_train, y_train)
        X_train_scaled = scale_values(X_train, min_value, max_value)
        y_train_scaled = scale_values(y_train, min_value, max_value)
        X_test_scaled = scale_values(X_test, min_value, max_value)

        candidate_lstm_model = build_lstm_model()
        candidate_lstm_model.fit(
            X_train_scaled,
            y_train_scaled,
            epochs=epochs,
            batch_size=batch_size,
            validation_data=(X_test_scaled, scale_values(y_test, min_value, max_value)),
            verbose=0,
        )

        scaled_predictions = candidate_lstm_model.predict(
            X_test_scaled,
            verbose=0,
        ).flatten()
        predictions = inverse_scale(scaled_predictions, min_value, max_value)
        holdout_metrics = regression_metrics(y_test, predictions)

        holdout_baselines = {
            name: regression_metrics(y_test, preds)
            for name, preds in baseline_predictions(X_test).items()
        }
        best_baseline_name, best_baseline = min(
            holdout_baselines.items(),
            key=lambda item: item[1]["rmse"],
        )
        rmse_improvement_pct = (
            (best_baseline["rmse"] - holdout_metrics["rmse"]) / best_baseline["rmse"] * 100
            if best_baseline["rmse"] > 0 else 0.0
        )

        rmse_values = [row["rmse"] for row in walk_forward_folds]
        mae_values = [row["mae"] for row in walk_forward_folds]
        smape_values = [row["smape"] for row in walk_forward_folds]
        direction_values = [row["direction_accuracy"] for row in walk_forward_folds if row.get("direction_accuracy") is not None]

        baseline_summary = {}
        for name, rows in fold_baselines.items():
            baseline_summary[name] = {
                "cv_mean_rmse": float(np.mean([r["rmse"] for r in rows])),
                "cv_worst_rmse": float(np.max([r["rmse"] for r in rows])),
                "cv_mean_mae": float(np.mean([r["mae"] for r in rows])),
                "cv_mean_smape": float(np.mean([r["smape"] for r in rows])),
                "holdout": holdout_baselines.get(name),
            }

        readiness_warnings = []
        if len(X_sequences) < 200:
            readiness_warnings.append(
                f"Only {len(X_sequences)} sequence rows are available; LSTM remains experimental until a longer time series is available."
            )
        if sequence_length < 12:
            readiness_warnings.append("Sequence length is shorter than a 12-period annual window.")
        if rmse_improvement_pct <= 0:
            readiness_warnings.append("LSTM did not outperform the strongest transparent holdout baseline by RMSE.")
        if rmse_values and float(np.std(rmse_values)) > float(np.mean(rmse_values)):
            readiness_warnings.append("Walk-forward RMSE is unstable across folds.")

        maturity_status = "experimental_lstm" if readiness_warnings else "candidate_ready_for_review"

        model_version_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        versioned_path = os.path.join(self.model_dir, f"lstm_{model_version_stamp}.keras")
        candidate_lstm_model.save(versioned_path)

        fingerprint_hasher = hashlib.sha256()
        fingerprint_hasher.update(np.ascontiguousarray(X_sequences).tobytes())
        fingerprint_hasher.update(np.ascontiguousarray(y_targets).tobytes())
        fingerprint_hasher.update(
            json.dumps(
                {
                    "sequence_shape": list(X_sequences.shape),
                    "target_rows": int(len(y_targets)),
                    "sequence_length": int(sequence_length),
                    "forecast_horizon": 1,
                    "split_policy": "expanding_window_walk_forward_plus_holdout",
                    "scaling": "minmax_train_fold_only",
                    "epochs": int(epochs),
                    "batch_size": int(batch_size),
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        dataset_fingerprint = fingerprint_hasher.hexdigest()

        observation_counts = self._lstm_observation_counts(db)

        self.lstm_metrics = {
            "trained": True,
            "phase": "phase5_forecast_validation",
            "maturity_status": maturity_status,
            "rmse": holdout_metrics["rmse"],
            "mae": holdout_metrics["mae"],
            "smape": holdout_metrics["smape"],
            "mape": holdout_metrics["mape"],
            "direction_accuracy": holdout_metrics["direction_accuracy"],
            "baseline_rmse": best_baseline["rmse"],
            "baseline_smape": best_baseline["smape"],
            "best_baseline": best_baseline_name,
            "baseline_comparisons": holdout_baselines,
            "baseline_summary": baseline_summary,
            "rmse_improvement_pct": round(float(rmse_improvement_pct), 2),
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "model_version": self.model_version,
            "candidate_artifact": versioned_path,
            "model_path": versioned_path,
            "dataset_fingerprint": dataset_fingerprint,
            "timeseries_cv_folds": walk_forward_folds,
            "walk_forward_backtest_folds": walk_forward_folds,
            "cv_mean_rmse": float(np.mean(rmse_values)) if rmse_values else None,
            "cv_std_rmse": float(np.std(rmse_values)) if rmse_values else None,
            "cv_worst_rmse": float(np.max(rmse_values)) if rmse_values else None,
            "cv_mean_mae": float(np.mean(mae_values)) if mae_values else None,
            "cv_mean_smape": float(np.mean(smape_values)) if smape_values else None,
            "cv_worst_smape": float(np.max(smape_values)) if smape_values else None,
            "cv_mean_direction_accuracy": float(np.mean(direction_values)) if direction_values else None,
            "training_samples": int(len(X_train)),
            "test_samples": int(len(X_test)),
            "sequence_length": int(sequence_length),
            "forecast_horizon": 1,
            "data_window": {
                "sequence_rows": int(len(X_sequences)),
                "sequence_length": int(sequence_length),
                "granularity": "model_sequence_step",
                "observation_counts": observation_counts,
                "history_length": "Each sequence is reshaped from {sequence_length} consecutive demand-score steps; aggregate history length is {sequence_length} steps per row (see observation counts and signal date range).".format(sequence_length=sequence_length),
            },
            "scaling_policy": "Min-max scaler fitted on each training fold only; final holdout scaler fitted on train split only.",
            "readiness_warnings": readiness_warnings,
            "promotion_gate": {
                "status": "blocked_pending_full_validation" if readiness_warnings else "candidate_review_required",
                "reason": "Phase 5 produces a forecast candidate only; do not promote without longer backtesting, registry review and authorised approval.",
            },
        }

        metadata = {
            "model_type": "lstm",
            "version": model_version_stamp,
            "lifecycle_state": "candidate",
            "active_model_updated": False,
            "promotion_required": True,
            "training_date": datetime.now(timezone.utc).isoformat(),
            "dataset_fingerprint": dataset_fingerprint,
            "dataset_snapshot": {
                "sequence_rows": int(len(X_sequences)),
                "target_rows": int(len(y_targets)),
                "sequence_length": int(sequence_length),
                "forecast_horizon": 1,
                "split_policy": "expanding_window_walk_forward_plus_holdout",
                "scaling_policy": "minmax_train_fold_only",
            },
            "validation_metrics": holdout_metrics,
            "baseline_comparisons": holdout_baselines,
            "walk_forward_backtest_folds": walk_forward_folds,
            "readiness_warnings": readiness_warnings,
            "promotion_gate": self.lstm_metrics["promotion_gate"],
            "epochs": epochs,
            "batch_size": batch_size,
            "sequence_length": sequence_length,
        }
        meta_path = os.path.join(self.model_dir, f"lstm_{model_version_stamp}_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, default=str)

        self._save_metrics()

        logger.info(
            "[MODEL] Phase 5 LSTM candidate complete (rmse=%s smape=%s best_baseline=%s improvement=%s%%)",
            round(holdout_metrics["rmse"], 4),
            round(holdout_metrics["smape"], 2),
            best_baseline_name,
            round(float(rmse_improvement_pct), 2),
        )

        return self.lstm_metrics

    # =====================================================
    # Alignment Prediction
    # =====================================================

    def run_alignment_prediction(
        self,
        db: Session,
        curriculum_module_code: str,
        region: Optional[str] = None,
        triggered_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run alignment prediction with TreeSHAP explainability.
        """

        if not self.xgboost_loaded:
            return self._run_heuristic_alignment(
                db=db,
                curriculum_module_code=curriculum_module_code,
                region=region,
            )

        curriculum = (
            db.query(
                CurriculumModule
            )
            .filter(
                CurriculumModule.module_code
                == curriculum_module_code
            )
            .first()
        )

        if not curriculum:

            raise ValueError(
                f"Curriculum module "
                f"{curriculum_module_code} "
                f"not found."
            )

        contract = self.xgboost_metrics.get("serving_feature_contract") or {}
        if contract.get("contract_id") != reviewed_alignment_training_dataset_service.FEATURE_CONTRACT_ID:
            logger.warning("[MODEL] Active XGBoost has no supported serving feature contract; using heuristic")
            return self._run_heuristic_alignment(
                db=db,
                curriculum_module_code=curriculum_module_code,
                region=region,
            )

        labour_query = db.query(JobPosting)
        if region:
            labour_query = labour_query.filter(JobPosting.region == region)
        labour_records = labour_query.order_by(JobPosting.posted_date.desc()).limit(1000).all()
        features = reviewed_alignment_training_dataset_service.build_serving_features(
            curriculum,
            labour_records,
        )
        metadata = {
            "feature_contract_id": contract["contract_id"],
            "num_job_postings_analyzed": len(labour_records),
        }

        feature_names = contract.get("selected_columns")

        if feature_names:

            ordered_keys = list(feature_names)

            feature_array = np.array(
                [
                    features.get(
                        k,
                        0.0,
                    )
                    for k in ordered_keys
                ]
            ).reshape(1, -1)

        else:

            ordered_keys = sorted(
                features.keys()
            )

            feature_array = np.array(
                [
                    features.get(
                        key,
                        0.0,
                    )
                    for key in ordered_keys
                ]
            ).reshape(1, -1)

        prediction_proba = (
            self.xgboost_model
            .predict_proba(
                feature_array
            )[0]
        )

        alignment_score = float(
            prediction_proba[1]
        )

        operating_threshold = float(contract["operating_threshold"])
        is_aligned = self.classify_alignment_score(alignment_score, self.xgboost_metrics)

        confidence_score = float(
            max(prediction_proba)
        )

        gap_score = metadata.get(
            "gap_score",
            0.5,
        )

        # -------------------------------------------------
        # SHAP Explainability
        # -------------------------------------------------

        shap_summary = []

        if self.shap_explainer:
            try:
                shap_values = (
                    self.shap_explainer
                    .shap_values(
                        feature_array
                    )
                )

                feature_impacts = list(
                    zip(
                        ordered_keys,
                        shap_values[0],
                    )
                )

                feature_impacts.sort(
                    key=lambda x: abs(
                        x[1]
                    ),
                    reverse=True,
                )

                shap_summary = [
                    {
                        "feature_name": fname,
                        "shap_value": float(
                            fvalue
                        ),
                    }
                    for fname, fvalue in (
                        feature_impacts[:10]
                    )
                ]

            except Exception as exc:

                logger.warning(
                    "[MODEL] SHAP failed: %s",
                    str(exc),
                )

        # Legacy database column retained empty; TreeSHAP is exclusive.
        lime_summary = []

        # -------------------------------------------------
        # Persist Prediction
        # -------------------------------------------------

        prediction_record = (
            PredictiveOutput(
                curriculum_module_code=curriculum.module_code,
                curriculum_nqf_level=curriculum.nqf_level,
                faculty=curriculum.faculty,
                model_type="xgboost",
                model_version=self.model_version,
                alignment_score=alignment_score,
                is_aligned=is_aligned,
                confidence_score=confidence_score,
                gap_score=gap_score,
                gap_flag=gap_score > 0.40,
                shap_summary=shap_summary,
                lime_summary=lime_summary,
                top_influencing_skills=metadata.get(
                    "skill_demand_ranking",
                    [],
                ),
                data_region=region,
                input_features_hash=metadata.get(
                    "feature_hash",
                ),
                inference_duration_ms=None,
                dataset_version=self.dataset_version,
                triggered_by=triggered_by,
                action_taken="predicted",
            )
        )

        db.add(
            prediction_record
        )

        db.commit()

        db.refresh(
            prediction_record
        )

        result = {
            "prediction_id": (
                prediction_record.prediction_id
            ),
            "module_code": curriculum.module_code,
            "alignment_score": alignment_score,
            "is_aligned": is_aligned,
            "confidence_score": confidence_score,
            "gap_score": gap_score,
            "gap_flag": gap_score > 0.40,
            "shap_summary": shap_summary,
            "explainability_context": {
                "method": "TreeSHAP global and local feature attribution",
                "feature_labels_verified": bool(ordered_keys),
                "limitations": [
                    "Explanations support review; they do not replace curriculum committee judgement.",
                    "Faculty/department context is not treated as demographic fairness evidence by itself.",
                    "Local explanations should be checked against source curriculum and labour-market evidence.",
                ],
            },
            "top_influencing_skills": metadata.get(
                "skill_demand_ranking",
                [],
            ),
            "prediction_timestamp": (
                prediction_record.prediction_timestamp
            ),
            "model_version": self.model_version,
            "dataset_version": self.dataset_version,
        }

        logger.info(
            "[MODEL] Alignment prediction complete "
            "(module=%s score=%s)",
            curriculum.module_code,
            round(alignment_score, 4),
        )

        return result

    # =====================================================
    # Demand Forecasting
    # =====================================================

    def run_demand_forecast(
        self,
        db: Session,
        curriculum_module_code: str,
        forecast_horizon: int = 12,
        region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run LSTM demand forecast.
        """

        if not self.lstm_loaded:
            return self._run_heuristic_forecast(
                db=db,
                curriculum_module_code=curriculum_module_code,
                forecast_horizon=forecast_horizon,
                region=region,
            )

        curriculum = (
            db.query(
                CurriculumModule
            )
            .filter(
                CurriculumModule.module_code
                == curriculum_module_code
            )
            .first()
        )

        if not curriculum:

            raise ValueError(
                f"Curriculum module "
                f"{curriculum_module_code} "
                f"not found."
            )

        sequence, metadata = (
            self.feature_engineer
            .create_lstm_sequence_features(
                db=db,
                curriculum=curriculum,
                sequence_length=12,
                region=region,
            )
        )

        current_sequence = (
            sequence.flatten()
        )

        forecast_trajectory = []

        for month in range(
            1,
            forecast_horizon + 1,
        ):

            input_sequence = (
                current_sequence[-11:]
                .reshape(1, 11, 1)
            )

            next_prediction = (
                self.lstm_model.predict(
                    input_sequence,
                    verbose=0,
                )[0][0]
            )

            next_prediction = float(
                np.clip(
                    next_prediction,
                    0.0,
                    1.0,
                )
            )

            forecast_trajectory.append(
                {
                    "month": month,
                    "predicted_demand": next_prediction,
                    "confidence_lower": max(
                        0.0,
                        next_prediction - 0.15,
                    ),
                    "confidence_upper": min(
                        1.0,
                        next_prediction + 0.15,
                    ),
                }
            )

            current_sequence = np.append(
                current_sequence,
                next_prediction,
            )

        prediction_record = (
            PredictiveOutput(
                curriculum_module_code=curriculum.module_code,
                curriculum_nqf_level=curriculum.nqf_level,
                faculty=curriculum.faculty,
                model_type="lstm",
                model_version=self.model_version,
                forecast_horizon_months=forecast_horizon,
                forecast_data={
                    "trajectory": forecast_trajectory,
                },
                forecast_rmse=self.lstm_metrics.get(
                    "rmse"
                ),
                forecast_mape=self.lstm_metrics.get(
                    "smape",
                    0.0,
                ),
                data_region=region,
                dataset_version=self.dataset_version,
            )
        )

        db.add(
            prediction_record
        )

        db.commit()

        db.refresh(
            prediction_record
        )

        result = {
            "prediction_id": (
                prediction_record.prediction_id
            ),
            "module_code": curriculum.module_code,
            "forecast_horizon_months": forecast_horizon,
            "forecast_trajectory": forecast_trajectory,
            "rmse": self.lstm_metrics.get(
                "rmse"
            ),
            "mape": self.lstm_metrics.get(
                "smape",
                0.0,
            ),
            "prediction_timestamp": (
                prediction_record.prediction_timestamp
            ),
            "model_version": self.model_version,
            "dataset_version": self.dataset_version,
            "data_region": region,
        }

        logger.info(
            "[MODEL] Forecast completed "
            "(module=%s)",
            curriculum.module_code,
        )

        return result

    # =====================================================
    # Model Status
    # =====================================================

    def get_model_status(
        self,
        db: Session,
    ) -> Dict[str, Any]:
        """
        Get predictive model status.
        """

        total_curricula = (
            db.query(
                CurriculumModule
            ).count()
        )

        total_jobs = (
            db.query(
                JobPosting
            ).count()
        )

        return {
            "xgboost_model_loaded": self.xgboost_loaded,
            "lstm_model_loaded": self.lstm_loaded,
            "xgboost_last_trained": self.xgboost_metrics.get(
                "trained_at"
            ),
            "lstm_last_trained": self.lstm_metrics.get(
                "trained_at"
            ),
            "xgboost_metrics": self.xgboost_metrics,
            "lstm_metrics": self.lstm_metrics,
            "total_curriculum_records": total_curricula,
            "total_job_postings": total_jobs,
            "model_directory": self.model_dir,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "dataset_version": self.dataset_version,
        }

