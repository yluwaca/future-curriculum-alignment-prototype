from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate_forecast_fixture import build_fixture
from run_forecast_functional_verification import validate_panel


def test_generator_is_deterministic():
    assert build_fixture().to_csv(index=False) == build_fixture().to_csv(index=False)


def test_valid_synthetic_panel_is_accepted_for_functional_verification():
    ledger, clean = validate_panel(build_fixture(), allow_synthetic=True)
    assert len(clean) == 192
    assert clean.series_id.nunique() == 4
    assert ledger.included.all()


def _single_series() -> pd.DataFrame:
    return build_fixture().query("series_id == 'level_seasonal'").reset_index(drop=True)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda x: x.drop(index=8), "missing_or_irregular_periods"),
        (lambda x: pd.concat([x, x.iloc[[0]]], ignore_index=True), "duplicate_series_period"),
        (lambda x: x.assign(frequency=["quarterly" if i == 4 else "monthly" for i in range(len(x))]), "mixed_frequency"),
        (lambda x: x.assign(period=["bad-date" if i == 3 else v for i, v in enumerate(x.period)]), "invalid_date"),
        (lambda x: x.assign(value=[-1 if i == 2 else v for i, v in enumerate(x.value)]), "invalid_value"),
        (lambda x: x.assign(value=[np.nan if i == 2 else v for i, v in enumerate(x.value)]), "invalid_value"),
        (lambda x: x.assign(value=0), "all_zero_series"),
        (lambda x: x.assign(value=7), "constant_series"),
        (lambda x: x.iloc[:20], "insufficient_history"),
        (lambda x: x.assign(rights_status="unknown"), "unauthorised_rights"),
    ],
)
def test_invalid_fixture_rejected_with_reason(mutation, expected):
    ledger, clean = validate_panel(mutation(_single_series()), allow_synthetic=True)
    assert clean.empty
    assert expected in set(ledger.exclusion_reason)


def test_synthetic_panel_rejected_when_route_does_not_allow_it():
    ledger, clean = validate_panel(_single_series(), allow_synthetic=False)
    assert clean.empty
    assert set(ledger.exclusion_reason) == {"synthetic_not_permitted"}
