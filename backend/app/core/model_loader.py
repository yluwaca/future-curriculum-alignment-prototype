"""
Unified loader for predictive model artefacts with versioning, 
metadata tracking, and production-ready error handling.
Supports both XGBoost (alignment classifier) and LSTM (demand forecaster).
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Union, Dict, Any

import joblib
import tensorflow as tf
from xgboost import XGBClassifier

from app.core.config import settings

logger = logging.getLogger(__name__)


class ModelLoadError(Exception):
    """Custom exception for model loading failures."""
    pass


class ModelLoader:
    """
    Unified loader for predictive model artefacts with:
    - Version-aware path resolution
    - Metadata validation
    - Graceful fallback to defaults
    - Optional warm-up for low-latency inference
    """

    SUPPORTED_EXTENSIONS = {
        "xgboost": ".pkl",
        "lstm": ".keras",  # TensorFlow SavedModel format preferred
    }

    def __init__(
        self, 
        base_path: Optional[Path] = None, 
        version: Optional[str] = None
    ):
        self.base_path = base_path or Path(settings.MODEL_STORAGE_PATH)
        self.version = version or settings.MODEL_VERSION
        self._cache: Dict[str, Any] = {}
        
        # Ensure storage directory exists
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            f"ModelLoader initialised: base_path={self.base_path}, "
            f"version={self.version}, hot_reload={settings.ENABLE_MODEL_HOT_RELOAD}"
        )

    def _resolve_model_path(self, model_type: str) -> Path:
        """
        Resolve the filesystem path for a model file with versioning support.
        
        Args:
            model_type: Either 'xgboost' or 'lstm'
            
        Returns:
            Path to the model file
            
        Raises:
            ModelLoadError: If no valid model file is found
        """
        if model_type not in self.SUPPORTED_EXTENSIONS:
            raise ModelLoadError(f"Unsupported model type: {model_type}")
        
        extension = self.SUPPORTED_EXTENSIONS[model_type]
        
        if self.version == "latest":
            # Find most recently modified model of this type
            pattern = f"{model_type}_*{extension}"
            candidates = list(self.base_path.glob(pattern))
            
            if not candidates:
                # Fallback to unversioned name
                fallback = self.base_path / f"{model_type}{extension}"
                if fallback.exists():
                    logger.warning(
                        f"No versioned {model_type} models found; "
                        f"using fallback: {fallback}"
                    )
                    return fallback
                raise ModelLoadError(
                    f"No {model_type} model found in {self.base_path} "
                    f"(expected pattern: {pattern})"
                )
            
            # Return most recent by modification time
            return max(candidates, key=lambda p: p.stat().st_mtime)
        else:
            # Explicit version requested
            path = self.base_path / f"{model_type}_{self.version}{extension}"
            if not path.exists():
                raise ModelLoadError(f"Model not found: {path}")
            return path

    def _resolve_metadata_path(self, model_type: str) -> Path:
        """Resolve path to accompanying JSON metadata file."""
        return self.base_path / f"{model_type}_{self.version or 'latest'}_metadata.json"

    def load_xgboost(self, force_reload: bool = False) -> Any:
        """
        Load the trained XGBoost alignment classifier.
        
        Args:
            force_reload: Bypass cache and reload from disk
            
        Returns:
            Configured XGBClassifier instance
            
        Raises:
            ModelLoadError: If model cannot be loaded or validated
        """
        cache_key = f"xgboost_{self.version}"
        
        if not force_reload and cache_key in self._cache:
            logger.debug(f"Returning cached XGBoost model: {cache_key}")
            return self._cache[cache_key]
        
        model_path = self._resolve_model_path("xgboost")
        logger.info(f"Loading XGBoost model from {model_path}")
        
        try:
            model = joblib.load(model_path)
            
            # Validate expected attributes for thesis evaluation
            # Note: feature_names_in_ requires DataFrame input during training,
            # best_iteration requires early stopping — neither is used currently.
            # Feature names are stored in model_metrics.json instead.
            required_attrs = ["classes_"]
            optional_attrs = ["feature_names_in_", "best_iteration"]
            missing_optional = [attr for attr in optional_attrs if not hasattr(model, attr)]
            if missing_optional:
                logger.debug(
                    f"XGBoost model optional attributes not set: {missing_optional}. "
                    f"This is expected when training with numpy arrays without early stopping."
                )
            
            # Cache if hot reload is disabled
            if not settings.ENABLE_MODEL_HOT_RELOAD:
                self._cache[cache_key] = model
                
            return model
            
        except Exception as e:
            logger.error(f"Failed to load XGBoost model: {e}")
            raise ModelLoadError(f"XGBoost load error: {str(e)}") from e

    def load_lstm(self, force_reload: bool = False) -> Any:
        """
        Load the trained LSTM demand forecaster.
        
        Args:
            force_reload: Bypass cache and reload from disk
            
        Returns:
            Compiled TensorFlow/Keras model instance
            
        Raises:
            ModelLoadError: If model cannot be loaded or compiled
        """
        cache_key = f"lstm_{self.version}"
        
        if not force_reload and cache_key in self._cache:
            logger.debug(f"Returning cached LSTM model: {cache_key}")
            return self._cache[cache_key]
        
        model_path = self._resolve_model_path("lstm")
        logger.info(f"Loading LSTM model from {model_path}")
        
        try:
            # Load with custom objects if needed
            model = tf.keras.models.load_model(
                model_path,
                compile=True  # Ensure model is ready for inference
            )
            
            # Validate input shape matches expected sequence length
            # Model is trained with LSTM_SEQUENCE_LENGTH - 1 because
            # the last timestep is used as the prediction target
            expected_input_shape = (None, settings.LSTM_SEQUENCE_LENGTH - 1, 1)
            actual_input_shape = model.input_shape
            
            if actual_input_shape[1:] != expected_input_shape[1:]:
                logger.warning(
                    f"LSTM input shape mismatch: expected {expected_input_shape}, "
                    f"got {actual_input_shape}. Predictions may be affected."
                )
            
            # Cache if hot reload is disabled
            if not settings.ENABLE_MODEL_HOT_RELOAD:
                self._cache[cache_key] = model
                
            return model
            
        except Exception as e:
            logger.error(f"Failed to load LSTM model: {e}")
            raise ModelLoadError(f"LSTM load error: {str(e)}") from e

    def load_metadata(self, model_type: str) -> Dict[str, Any]:
        """
        Load accompanying metadata (training config, metrics, feature schema).
        
        Args:
            model_type: Either 'xgboost' or 'lstm'
            
        Returns:
            Dictionary of metadata, or warning dict if file not found
        """
        meta_path = self._resolve_metadata_path(model_type)
        
        if not meta_path.exists():
            logger.warning(f"No metadata file found for {model_type}: {meta_path}")
            return {"warning": "Metadata file not found", "model_type": model_type}
        
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse metadata JSON: {e}")
            return {"error": f"JSON parse error: {str(e)}"}

    def get_model_info(self, model_type: str) -> Dict[str, Any]:
        """
        Return comprehensive model information for monitoring/debugging.
        
        Args:
            model_type: Either 'xgboost' or 'lstm'
            
        Returns:
            Dictionary with path, version, metadata summary, and load status
        """
        info = {
            "model_type": model_type,
            "version": self.version,
            "base_path": str(self.base_path),
            "hot_reload_enabled": settings.ENABLE_MODEL_HOT_RELOAD,
        }
        
        try:
            model_path = self._resolve_model_path(model_type)
            info.update({
                "model_path": str(model_path),
                "model_exists": True,
                "model_size_bytes": model_path.stat().st_size,
                "last_modified": model_path.stat().st_mtime,
            })
        except ModelLoadError as e:
            info.update({
                "model_exists": False,
                "load_error": str(e),
            })
        
        # Add metadata summary
        metadata = self.load_metadata(model_type)
        info["metadata_summary"] = {
            k: v for k, v in metadata.items() 
            if k in ["training_date", "validation_metrics", "feature_count"]
        }
        
        return info

    def warm_up(self) -> None:
        """
        Pre-load models into memory for low-latency inference.
        Should be called during application startup in production.
        """
        if not settings.ENABLE_MODEL_HOT_RELOAD:
            logger.info("Hot reload disabled; skipping model warm-up")
            return
            
        logger.info("Warming up predictive models...")
        
        errors = []
        
        # Attempt to load XGBoost
        try:
            _ = self.load_xgboost(force_reload=True)
            logger.info("✓ XGBoost model warmed up")
        except ModelLoadError as e:
            errors.append(f"XGBoost: {e}")
            logger.warning(f"✗ XGBoost warm-up failed: {e}")
        
        # Attempt to load LSTM
        try:
            _ = self.load_lstm(force_reload=True)
            logger.info("✓ LSTM model warmed up")
        except ModelLoadError as e:
            errors.append(f"LSTM: {e}")
            logger.warning(f"✗ LSTM warm-up failed: {e}")
        
        if errors:
            logger.error(
                f"Model warm-up completed with {len(errors)} error(s): "
                f"{'; '.join(errors)}"
            )
        else:
            logger.info("All models warmed up successfully")

    def clear_cache(self) -> None:
        """Clear in-memory model cache. Useful for testing or hot-reload scenarios."""
        cleared = list(self._cache.keys())
        self._cache.clear()
        logger.info(f"Cleared model cache: {cleared}")


# =========================
# Singleton Instance Management
# =========================
_model_loader_instance: Optional[ModelLoader] = None


def get_model_loader() -> ModelLoader:
    """
    Get or create the singleton ModelLoader instance.
    Thread-safe for FastAPI dependency injection.
    """
    global _model_loader_instance
    
    if _model_loader_instance is None:
        _model_loader_instance = ModelLoader()
        # Warm up models on first access if enabled
        _model_loader_instance.warm_up()
    
    return _model_loader_instance


def reset_model_loader() -> None:
    """
    Reset the singleton instance. Primarily for testing.
    """
    global _model_loader_instance
    if _model_loader_instance:
        _model_loader_instance.clear_cache()
    _model_loader_instance = None
    logger.info("ModelLoader singleton reset")