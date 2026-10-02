import numpy as np

from app.services.fold_safe_preprocessing_service import FoldSafePreprocessingService


def test_validation_and_holdout_values_cannot_change_fitted_columns():
    service = FoldSafePreprocessingService()
    train = np.array(
        [
            [1.0, 2.0, 0.0],
            [2.0, 4.0, 1.0],
            [3.0, 6.0, 0.0],
            [4.0, 8.0, 1.0],
            [5.0, 10.0, 0.0],
        ]
    )
    fitted = service.fit(train, ["a", "a_duplicate", "signal"])
    hostile_holdout = np.array([[999999.0, -999999.0, 42.0]])
    transformed = service.transform(hostile_holdout, fitted)
    fitted_again = service.fit(train, ["a", "a_duplicate", "signal"])
    assert fitted.selected_columns == fitted_again.selected_columns
    assert fitted.fit_matrix_hash == fitted_again.fit_matrix_hash
    assert transformed.shape == (1, len(fitted.selected_columns))


def test_preprocessor_evidence_proves_training_only_fit():
    service = FoldSafePreprocessingService()
    train = np.array([[0.0, 1.0], [1.0, 0.0], [2.0, 1.0], [3.0, 0.0]])
    fitted = service.fit(train, ["first", "second"])
    evidence = fitted.evidence()
    assert evidence["fit_row_count"] == 4
    assert evidence["target_used"] is False
    assert evidence["method"] == (
        "vif_lt_5_plus_nonconstant_semantic_features_fit_on_training_rows_only"
    )
    assert set(evidence["selected_columns"]).isdisjoint(evidence["removed_columns"])


def test_constant_or_collinear_training_window_keeps_at_least_one_feature():
    service = FoldSafePreprocessingService()
    train = np.ones((6, 3), dtype=float)
    fitted = service.fit(train, ["one", "two", "three"])
    transformed = service.transform(train, fitted)
    assert len(fitted.selected_columns) >= 1
    assert transformed.shape[1] == len(fitted.selected_columns)


def test_nonconstant_semantic_features_are_retained_after_vif_filtering():
    service = FoldSafePreprocessingService()
    train = np.array(
        [
            [10.0, 1.0, 0.10],
            [20.0, 2.0, 0.20],
            [30.0, 3.0, 0.30],
            [40.0, 4.0, 0.40],
            [50.0, 5.0, 0.50],
        ]
    )
    fitted = service.fit(
        train,
        ["curriculum_character_count", "shared_unique_token_count", "vocabulary_jaccard"],
    )
    assert "shared_unique_token_count" in fitted.selected_columns
    assert "vocabulary_jaccard" in fitted.selected_columns
