#!/usr/bin/env python
"""Operational assertions for a completed forecast-verification package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(package: Path) -> list[str]:
    passed: list[str] = []
    status = json.loads((package / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
    manifest = json.loads((package / "metadata/dataset_manifest.json").read_text(encoding="utf-8"))
    output = json.loads((package / "outputs/machine_readable_output.json").read_text(encoding="utf-8"))
    uncertainty = json.loads((package / "evaluation/uncertainty.json").read_text(encoding="utf-8"))
    observations = pd.read_csv(package / "dataset/forecast_observations.csv")
    predictions = pd.read_csv(package / "evaluation/predictions.csv")
    splits = pd.read_csv(package / "splits/split_membership.csv")

    assert status["status"] == "synthetic_functional_verification_not_empirical_accuracy"
    passed.append("package status preserves synthetic evidence boundary")
    assert observations.is_synthetic.astype(str).str.lower().eq("true").all()
    assert predictions.is_synthetic.astype(str).str.lower().eq("true").all()
    passed.append("synthetic status propagates to dataset and predictions")
    assert manifest["dataset_sha256"] == sha(package / "dataset/forecast_observations.csv")
    assert output["dataset_sha256"] == manifest["dataset_sha256"]
    passed.append("dataset manifest and checksum are linked")
    assert pd.to_datetime(splits.training_target_end).lt(pd.to_datetime(splits.target_period)).all()
    passed.append("chronology excludes future targets")
    assert splits[splits.split.eq("final_test")].groupby("series_id").size().eq(3).all()
    passed.append("final three targets per series are isolated")
    record_sets = [set(group.evaluation_record_id) for _, group in predictions.groupby("model")]
    assert len(record_sets) == 5 and all(records == record_sets[0] for records in record_sets)
    passed.append("candidate and baselines share identical evaluation records")
    assert set(predictions.model) == {"prototype_lstm", "ridge_autoregression", "last_value", "seasonal_naive", "drift"}
    passed.append("LSTM, ridge and three baselines executed")
    assert predictions[["prediction", "residual"]].notna().all().all()
    assert all("lower_95" in row and "upper_95" in row for row in uncertainty["methods"].values())
    passed.append("predictions, residuals and uncertainty persist")
    selected = predictions[predictions.forecast_id.eq(output["forecast_id"])]
    assert len(selected) == 1 and selected.iloc[0].run_id == output["run_id"]
    assert output["decision_statement"].lower().startswith("demonstration")
    assert output["origin_period"] == output["training_target_end"]
    assert pd.Timestamp(output["training_target_end"]) < pd.Timestamp(output["forecast_target_period"])
    assert int(output["training_rows"]) > 0
    passed.append("decision-support output links forecast, dataset and run with non-action boundary")
    assert (package / "outputs/decision_support_output.pdf").stat().st_size > 1000
    assert (package / "operational_verification/test_report.md").is_file()
    passed.append("decision-support PDF exists and is non-empty")
    registered = {}
    for line in (package / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        registered[name] = digest
    for name, digest_value in registered.items():
        assert sha(package / name) == digest_value
    passed.append("SHA-256 register verifies every packaged file")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    results = verify(args.package.resolve())
    for index, result in enumerate(results, 1):
        print(f"PASS {index:02d}: {result}")
    print(f"RESULT: {len(results)} passed, 0 failed")


if __name__ == "__main__":
    main()
