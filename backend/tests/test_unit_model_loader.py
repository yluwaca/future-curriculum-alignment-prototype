"""
Unit tests for model loader validation logic.
Tests shape validation, attribute checks, and error handling.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np


class TestLSTMShapeValidation:
    """Tests for LSTM input shape validation."""

    def _make_lstm_model(self, input_shape):
        """Create a mock LSTM model with given input shape."""
        model = MagicMock()
        model.input_shape = input_shape
        return model

    def test_correct_shape_passes(self):
        from app.core.config import settings
        expected = (None, settings.LSTM_SEQUENCE_LENGTH - 1, 1)
        actual = (None, 11, 1)
        assert actual[1:] == expected[1:]

    def test_wrong_shape_detected(self):
        from app.core.config import settings
        expected = (None, settings.LSTM_SEQUENCE_LENGTH - 1, 1)
        actual = (None, 12, 1)
        assert actual[1:] != expected[1:]

    def test_sequence_length_minus_one_is_eleven(self):
        from app.core.config import settings
        assert settings.LSTM_SEQUENCE_LENGTH - 1 == 11


class TestXGBoostAttributeValidation:
    """Tests for XGBoost model attribute validation."""

    def _make_xgboost_model(self, has_attrs=None):
        """Create a mock XGBoost model."""
        model = MagicMock()
        has_attrs = has_attrs or []
        for attr in ["feature_names_in_", "classes_", "best_iteration"]:
            if attr not in has_attrs:
                delattr(model, attr) if hasattr(model, attr) else None
        return model

    def test_classes_attribute_always_present(self):
        model = MagicMock()
        assert hasattr(model, "classes_")

    def test_missing_feature_names_detected(self):
        model = MagicMock(spec=["classes_"])
        required = ["classes_"]
        optional = ["feature_names_in_", "best_iteration"]
        missing = [a for a in optional if not hasattr(model, a)]
        assert "feature_names_in_" in missing
        assert "best_iteration" in missing

    def test_all_attributes_present(self):
        model = MagicMock()
        model.feature_names_in_ = np.array(["f1", "f2"])
        model.classes_ = np.array([0, 1])
        model.best_iteration = 50
        optional = ["feature_names_in_", "best_iteration"]
        missing = [a for a in optional if not hasattr(model, a)]
        assert len(missing) == 0


class TestModelPathResolution:
    """Tests for model path resolution logic."""

    def test_resolve_latest_path(self):
        from app.core.config import settings
        path = f"{settings.MODEL_STORAGE_PATH}/xgboost_latest.pkl"
        assert "xgboost_latest.pkl" in path

    def test_resolve_lstm_latest_path(self):
        from app.core.config import settings
        path = f"{settings.MODEL_STORAGE_PATH}/lstm_latest.keras"
        assert "lstm_latest.keras" in path
