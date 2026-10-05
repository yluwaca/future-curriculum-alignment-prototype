#!/usr/bin/env python
"""Generate the deterministic, non-empirical forecasting verification fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261005
GENERATOR_VERSION = "forecast_fixture_v1.0.0"
SOURCE_ID = "synthetic_forecast_fixture_20261005"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_fixture() -> pd.DataFrame:
    """Return four monthly 48-period series with fixed, documented functions."""
    rng = np.random.default_rng(SEED)
    periods = pd.date_range("2022-01-01", periods=48, freq="MS")
    definitions = {
        "level_seasonal": "level 32 + annual sine seasonality amplitude 8 + seeded noise",
        "gradual_trend": "level 12 + linear trend 0.65 per month + seeded noise",
        "trend_seasonal": "level 18 + trend 0.45 + annual sine amplitude 6 + seeded noise",
        "step_then_level": "level 16, deterministic level shift +9 at month 25 + seeded noise",
    }
    rows: list[dict] = []
    for series_index, (series_id, definition) in enumerate(definitions.items()):
        t = np.arange(len(periods), dtype=float)
        noise = rng.normal(0.0, 1.4 + series_index * 0.15, len(periods))
        if series_id == "level_seasonal":
            values = 32 + 8 * np.sin(2 * np.pi * t / 12) + noise
        elif series_id == "gradual_trend":
            values = 12 + 0.65 * t + noise
        elif series_id == "trend_seasonal":
            values = 18 + 0.45 * t + 6 * np.sin(2 * np.pi * (t + 2) / 12) + noise
        else:
            values = 16 + np.where(t >= 24, 9, 0) + noise
        values = np.maximum(1, np.rint(values)).astype(int)
        for period, value in zip(periods, values):
            rows.append(
                {
                    "series_id": series_id,
                    "series_definition": definition,
                    "period": period.date().isoformat(),
                    "frequency": "monthly",
                    "value": int(value),
                    "source_id": SOURCE_ID,
                    "provenance": f"deterministic generator {GENERATOR_VERSION}; seed={SEED}",
                    "rights_status": "synthetic_reproducible_fixture",
                    "is_synthetic": True,
                    "eligible": True,
                }
            )
    return pd.DataFrame(rows)


def write_negative_fixtures(base: pd.DataFrame, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    sample = base[base.series_id.eq("level_seasonal")].copy()
    fixtures = {
        "missing_period.csv": sample.drop(index=sample.index[8]),
        "duplicate_period.csv": pd.concat([sample, sample.iloc[[0]]], ignore_index=True),
        "mixed_frequency.csv": sample.assign(
            frequency=["quarterly" if index == 4 else "monthly" for index in range(len(sample))]
        ),
        "invalid_date.csv": sample.assign(
            period=["not-a-date" if index == 3 else value for index, value in enumerate(sample.period)]
        ),
        "negative_value.csv": sample.assign(
            value=[-1 if index == 2 else value for index, value in enumerate(sample.value)]
        ),
        "missing_value.csv": sample.assign(
            value=[np.nan if index == 2 else value for index, value in enumerate(sample.value)]
        ),
        "all_zero.csv": sample.assign(value=0),
        "constant.csv": sample.assign(value=7),
        "insufficient_history.csv": sample.iloc[:20],
        "unauthorised_rights.csv": sample.assign(rights_status="unknown"),
    }
    for name, frame in fixtures.items():
        frame.to_csv(directory / name, index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--negative-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame = build_fixture()
    frame.to_csv(args.output, index=False, lineterminator="\n")
    write_negative_fixtures(frame, args.negative_dir)
    print(
        json.dumps(
            {
                "generator_version": GENERATOR_VERSION,
                "seed": SEED,
                "rows": len(frame),
                "series": frame.series_id.nunique(),
                "period_start": frame.period.min(),
                "period_end": frame.period.max(),
                "dataset_sha256": sha256(args.output),
                "generator_sha256": sha256(Path(__file__)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
