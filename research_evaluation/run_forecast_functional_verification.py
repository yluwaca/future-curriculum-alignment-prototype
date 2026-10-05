#!/usr/bin/env python
"""Build the separate, publication-safe forecast functional-verification package."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import random
import subprocess
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")
os.environ.setdefault("PYTHONHASHSEED", "20261005")

import numpy as np
import pandas as pd
import sklearn
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import tensorflow as tf
from tensorflow.keras import Sequential
from tensorflow.keras.layers import Dense, Input, LSTM
import reportlab

from generate_forecast_fixture import GENERATOR_VERSION, SEED, build_fixture, sha256, write_negative_fixtures

STATUS = "synthetic_functional_verification_not_empirical_accuracy"
RUN_ID = "forecast-functional-verification-20261005-v1"
HORIZON = 3
SEQUENCE_LENGTH = 12
LAGS = SEQUENCE_LENGTH - 1
DEV_ORIGINS = 6
BOOTSTRAP_SEED = 20261005
METHODS = ("prototype_lstm", "ridge_autoregression", "last_value", "seasonal_naive", "drift")
REQUIRED = {
    "series_id", "series_definition", "period", "frequency", "value", "source_id",
    "provenance", "rights_status", "is_synthetic", "eligible",
}


def digest(path: Path) -> str:
    return sha256(path)


def configure_accelerator(require_gpu: bool) -> dict:
    """Configure TensorFlow and make accelerator selection auditable.

    ``--require-gpu`` is deliberately fail-closed: a verification run must not
    silently fall back to CPU when it is intended to demonstrate CUDA use.
    """
    physical_gpus = tf.config.list_physical_devices("GPU")
    for device in physical_gpus:
        try:
            tf.config.experimental.set_memory_growth(device, True)
        except RuntimeError:
            # TensorFlow has already initialised the device. The device remains
            # usable, but memory-growth can no longer be changed in this process.
            pass
    if require_gpu and not physical_gpus:
        raise RuntimeError(
            "CUDA GPU required but TensorFlow detected no GPU. Run this command "
            "inside the configured WSL2 TensorFlow environment."
        )
    logical_gpus = tf.config.list_logical_devices("GPU")
    return {
        "requested": "gpu" if require_gpu else "automatic",
        "physical_gpus": [device.name for device in physical_gpus],
        "logical_gpus": [device.name for device in logical_gpus],
        "cuda_build": bool(tf.test.is_built_with_cuda()),
        "selected": "gpu" if logical_gpus else "cpu",
    }


def json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def truth(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def validate_panel(frame: pd.DataFrame, allow_synthetic: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"missing_columns:{','.join(sorted(missing))}")
    ledger = frame.copy()
    ledger["exclusion_reason"] = ""
    parsed = pd.to_datetime(ledger.period, errors="coerce", utc=True)
    values = pd.to_numeric(ledger.value, errors="coerce")
    checks = [
        ("declared_ineligible", ~truth(ledger.eligible)),
        ("invalid_date", parsed.isna()),
        ("invalid_value", values.isna() | values.lt(0)),
        ("invalid_frequency", ~ledger.frequency.astype(str).str.lower().isin({"monthly", "quarterly"})),
        ("duplicate_series_period", ledger.duplicated(["series_id", "period"], keep=False)),
        ("unauthorised_rights", ~ledger.rights_status.astype(str).isin(
            {"public", "examiner_only", "redistributable", "synthetic_reproducible_fixture"}
        )),
        ("synthetic_not_permitted", truth(ledger.is_synthetic) & (not allow_synthetic)),
    ]
    for reason, mask in checks:
        ledger.loc[mask & ledger.exclusion_reason.eq(""), "exclusion_reason"] = reason
    duplicate_series = set(
        ledger.loc[ledger.duplicated(["series_id", "period"], keep=False), "series_id"].astype(str)
    )
    for series_id in duplicate_series:
        ledger.loc[ledger.series_id.astype(str).eq(series_id), "exclusion_reason"] = "duplicate_series_period"
    ledger["period_parsed"] = parsed
    ledger["value_parsed"] = values
    ledger["included"] = ledger.exclusion_reason.eq("")

    accepted: list[pd.DataFrame] = []
    for series_id, group in ledger[ledger.included].groupby("series_id", sort=True):
        frequency_values = group.frequency.astype(str).str.lower().unique()
        if len(frequency_values) != 1:
            reason = "mixed_frequency"
        else:
            frequency = frequency_values[0]
            periods = group.period_parsed.dt.tz_convert(None).dt.to_period("M" if frequency == "monthly" else "Q")
            expected = pd.period_range(periods.min(), periods.max(), freq="M" if frequency == "monthly" else "Q")
            minimum = 30 if frequency == "monthly" else 14
            if len(periods) != len(expected) or periods.nunique() != len(expected):
                reason = "missing_or_irregular_periods"
            elif len(group) < minimum:
                reason = "insufficient_history"
            elif float(group.value_parsed.sum()) == 0:
                reason = "all_zero_series"
            elif group.value_parsed.nunique() < 2:
                reason = "constant_series"
            else:
                reason = ""
        if reason:
            ledger.loc[ledger.series_id.eq(series_id) & ledger.exclusion_reason.eq(""), "exclusion_reason"] = reason
            ledger.loc[ledger.series_id.eq(series_id), "included"] = False
        else:
            accepted.append(group.sort_values("period_parsed"))
    clean = pd.concat(accepted, ignore_index=True) if accepted else ledger.iloc[:0].copy()
    return ledger, clean


def supervised(values: np.ndarray, end: int) -> tuple[np.ndarray, np.ndarray]:
    x, y = [], []
    for target_index in range(LAGS, end):
        x.append(values[target_index - LAGS:target_index])
        y.append(values[target_index])
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def lstm_prediction(values: np.ndarray, target_index: int, seed: int) -> tuple[float, Sequential]:
    x_train, y_train = supervised(values, target_index)
    minimum = float(min(x_train.min(), y_train.min()))
    maximum = float(max(x_train.max(), y_train.max()))
    scale = maximum - minimum if maximum > minimum else 1.0
    x_scaled = ((x_train - minimum) / scale).reshape((-1, LAGS, 1))
    y_scaled = (y_train - minimum) / scale
    tf.keras.backend.clear_session()
    random.seed(seed)
    np.random.seed(seed)
    tf.keras.utils.set_random_seed(seed)
    try:
        tf.config.experimental.enable_op_determinism()
    except Exception:
        pass
    model = Sequential([
        Input(shape=(LAGS, 1)),
        LSTM(64, activation="relu", return_sequences=True),
        tf.keras.layers.Dropout(0.2),
        LSTM(32, activation="relu"),
        Dense(1),
    ])
    model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.001), loss="mse")
    model.fit(x_scaled, y_scaled, epochs=12, batch_size=8, shuffle=False, verbose=0)
    query = ((values[target_index - LAGS:target_index] - minimum) / scale).reshape((1, LAGS, 1))
    prediction = float(model.predict(query, verbose=0).reshape(-1)[0] * scale + minimum)
    return max(0.0, prediction), model


def metrics(frame: pd.DataFrame) -> dict:
    actual = frame.actual.to_numpy(float)
    prediction = frame.prediction.to_numpy(float)
    denominator = np.abs(actual) + np.abs(prediction)
    smape_terms = np.where(denominator == 0, 0.0, 200 * np.abs(actual - prediction) / denominator)
    return {
        "records": int(len(frame)),
        "mae": float(mean_absolute_error(actual, prediction)),
        "rmse": float(np.sqrt(mean_squared_error(actual, prediction))),
        "smape_pct": float(np.mean(smape_terms)),
        "smape_zero_denominator_rule": "term is 0 when actual and prediction are both 0",
    }


def bootstrap_mae(frame: pd.DataFrame) -> dict:
    """Cluster bootstrap: resample independent series, retaining all their test targets."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    series = sorted(frame.series_id.unique())
    values: list[float] = []
    for _ in range(2000):
        sampled = rng.choice(series, size=len(series), replace=True)
        actual: list[float] = []
        prediction: list[float] = []
        for item in sampled:
            rows = frame[frame.series_id.eq(item)]
            actual.extend(rows.actual.astype(float).tolist())
            prediction.extend(rows.prediction.astype(float).tolist())
        values.append(float(mean_absolute_error(actual, prediction)))
    return {
        "metric": "MAE",
        "method": "percentile cluster bootstrap",
        "bootstrap_unit": "series (all final-horizon targets retained within a sampled series)",
        "seed": BOOTSTRAP_SEED,
        "replicates": 2000,
        "lower_95": float(np.quantile(values, 0.025)),
        "upper_95": float(np.quantile(values, 0.975)),
        "interpretation": "exploratory because only four independent synthetic series exist",
    }


def evaluate(panel: pd.DataFrame, native_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict, dict]:
    prediction_rows: list[dict] = []
    membership_rows: list[dict] = []
    native_dir.mkdir(parents=True, exist_ok=True)
    for series_number, (series_id, group) in enumerate(panel.groupby("series_id", sort=True)):
        group = group.sort_values("period_parsed").reset_index(drop=True)
        values = group.value_parsed.to_numpy(float)
        test_start = len(group) - HORIZON
        dev_start = test_start - DEV_ORIGINS
        last_model: Sequential | None = None
        for target_index in range(dev_start, len(group)):
            split = "final_test" if target_index >= test_start else "development"
            x_train, y_train = supervised(values, target_index)
            ridge = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=1.0))]).fit(x_train, y_train)
            lstm_value, last_model = lstm_prediction(
                values, target_index, SEED + series_number * 100 + target_index
            )
            history = values[:target_index]
            candidate_predictions = {
                "prototype_lstm": lstm_value,
                "ridge_autoregression": float(ridge.predict(history[-LAGS:].reshape(1, -1))[0]),
                "last_value": float(history[-1]),
                "seasonal_naive": float(history[-12]),
                "drift": float(history[-1] + (history[-1] - history[0]) / max(1, len(history) - 1)),
            }
            record_id = f"{series_id}|{group.period.iloc[target_index]}"
            membership_rows.append(
                {
                    "evaluation_record_id": record_id,
                    "series_id": series_id,
                    "origin_period": group.period.iloc[target_index - 1],
                    "target_period": group.period.iloc[target_index],
                    "training_target_end": group.period.iloc[target_index - 1],
                    "training_rows": int(len(y_train)),
                    "split": split,
                }
            )
            for method, prediction in candidate_predictions.items():
                actual = float(values[target_index])
                prediction_rows.append(
                    {
                        "forecast_id": hashlib.sha256(f"{RUN_ID}|{record_id}|{method}".encode()).hexdigest()[:24],
                        "run_id": RUN_ID,
                        "dataset_id": "synthetic-forecast-panel-20261005-v1",
                        "evaluation_record_id": record_id,
                        "series_id": series_id,
                        "origin_period": group.period.iloc[target_index - 1],
                        "target_period": group.period.iloc[target_index],
                        "training_target_end": group.period.iloc[target_index - 1],
                        "training_rows": int(len(y_train)),
                        "split": split,
                        "model": method,
                        "actual": actual,
                        "prediction": float(prediction),
                        "residual": actual - float(prediction),
                        "evidence_class": "synthetic_functional_verification",
                        "is_synthetic": True,
                    }
                )
        if last_model is not None:
            last_model.save(native_dir / f"{series_id}_final_origin.keras")
    predictions = pd.DataFrame(prediction_rows)
    membership = pd.DataFrame(membership_rows)
    expected = set(membership.evaluation_record_id)
    for method, group in predictions.groupby("model"):
        if set(group.evaluation_record_id) != expected:
            raise RuntimeError(f"evaluation record mismatch for {method}")
    chronology = pd.to_datetime(membership.training_target_end) < pd.to_datetime(membership.target_period)
    if not chronology.all():
        raise RuntimeError("future leakage detected")
    final = predictions[predictions.split.eq("final_test")]
    development = predictions[predictions.split.eq("development")]
    metric_payload = {
        "run_id": RUN_ID,
        "status": STATUS,
        "final_test": {method: metrics(group) for method, group in final.groupby("model")},
        "development": {method: metrics(group) for method, group in development.groupby("model")},
        "per_series_final_test": {
            method: {series: metrics(rows) for series, rows in group.groupby("series_id")}
            for method, group in final.groupby("model")
        },
    }
    uncertainty = {
        "status": STATUS,
        "methods": {method: bootstrap_mae(group) for method, group in final.groupby("model")},
    }
    return predictions, membership, metric_payload, uncertainty


def create_pdf(path: Path, output: dict, comparison: pd.DataFrame, metric_payload: dict) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.HexColor("#17365D"), spaceAfter=7))
    styles.add(ParagraphStyle(name="Subhead", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#1F4E79"), spaceBefore=7, spaceAfter=4))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=8.5, leading=11, spaceAfter=4))
    styles.add(ParagraphStyle(name="IdentityCell", parent=styles["BodyText"], fontName="Helvetica", fontSize=6.6, leading=8, splitLongWords=1))
    styles.add(ParagraphStyle(name="IdentityLabel", parent=styles["IdentityCell"], fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Banner", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#7F1D1D"), backColor=colors.HexColor("#FDECEC"), borderColor=colors.HexColor("#E8A0A0"), borderWidth=0.6, borderPadding=6, spaceAfter=7))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=14*mm, bottomMargin=17*mm, title="FUTURE Forecast Functional Verification")
    story = [Paragraph("FUTURE | Forecast Functional Verification", styles["ReportTitle"]), Paragraph("DEMONSTRATION DECISION-SUPPORT OUTPUT - NO INSTITUTIONAL ACTION AUTHORISED", styles["Banner"]), Paragraph("Evidence identity", styles["Subhead"])]
    identity_values = [
        ["Run ID", output["run_id"], "Output ID", output["output_id"]],
        ["Evidence class", output["evidence_class"], "Review status", output["human_review_status"]],
        ["Dataset", output["dataset_id"], "Model", f"{output['model']} v{output['model_version']}"],
        ["Dataset SHA-256", "<br/>".join(output["dataset_sha256"][index:index + 16] for index in range(0, len(output["dataset_sha256"]), 16)), "Forecast ID", "<br/>".join(output["forecast_id"][index:index + 12] for index in range(0, len(output["forecast_id"]), 12))],
        ["Observation window", output["observation_period"], "Target", output["forecast_target_period"]],
        ["Series", f"{output['series_id']}: {output['series_definition']}", "Point forecast", f"{output['point_forecast']:.3f}"],
        ["Training cutoff / rows", f"{output['training_target_end']} / {output['training_rows']}", "Origin", output["origin_period"]],
    ]
    identity = [
        [Paragraph(str(value), styles["IdentityLabel"] if column in (0, 2) else styles["IdentityCell"]) for column, value in enumerate(row)]
        for row in identity_values
    ]
    ident = Table(identity, colWidths=[29*mm, 67*mm, 27*mm, 49*mm])
    ident.setStyle(TableStyle([("BACKGROUND", (0,0), (0,-1), colors.HexColor("#EAF0F6")), ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#EAF0F6")), ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"), ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 6.8), ("LEADING", (0,0), (-1,-1), 8.5), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#CFD8E3")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4), ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
    story.extend([ident, Paragraph("Final-horizon comparison", styles["Subhead"]), Paragraph("Twelve common final targets (four series x three held-out months). Lower MAE, RMSE and sMAPE are better. Synthetic-only diagnostics.", styles["BodySmall"])])

    def metric_table(payload: dict) -> Table:
        rows = [["Method", "N", "MAE", "RMSE", "sMAPE (%)"]]
        for method, value in sorted(payload.items(), key=lambda item: item[1]["mae"]):
            rows.append([method.replace("_", " "), str(value["records"]), f"{value['mae']:.3f}", f"{value['rmse']:.3f}", f"{value['smape_pct']:.2f}"])
        table = Table(rows, colWidths=[66*mm, 18*mm, 27*mm, 27*mm, 34*mm], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 7.5), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#CFD8E3")), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F4F7FA")]), ("ALIGN", (1,1), (-1,-1), "RIGHT"), ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
        return table

    story.extend([metric_table(metric_payload["final_test"]), Paragraph("Development results", styles["Subhead"]), Paragraph("Six rolling-origin development targets per series (24 common records). The final three periods per series were held out from development.", styles["BodySmall"]), metric_table(metric_payload["development"]), PageBreak(), Paragraph("Method and evidence boundaries", styles["ReportTitle"])])
    observed = "The forecasting source gate examined live labour-vacancy data before fixture construction. The Adzuna store contained 3,417 unique records with posted dates across 22 irregular posting months (2024-07 to 2026-09); acquisition ran 2026-09-08 to 2026-09-20 and records were concentrated in 2026-08/09. The five-record DPSA source covered one month. Neither was a regular longitudinal panel, so neither entered this forecast evaluation. Adzuna permission allows academic API use and retention with attribution; it does not make this observed record set a stable time series."
    story.extend([Paragraph("Observed-source eligibility", styles["Subhead"]), Paragraph(observed, styles["BodySmall"]), Paragraph("Validation design", styles["Subhead"])])
    bullets = ["Deterministic fixture: four monthly series, 48 periods each (January 2022-December 2025), 192 observations. Generator and seed are included in the package.", "The final three months per series are test-only. Six earlier one-step rolling origins per series form development; training rows end strictly before each target.", "Scaling and model fits are origin-specific and use training data only. All five methods share the same 36 evaluation targets (24 development + 12 final test).", "Methods: implemented prototype LSTM architecture in an independent dated-panel harness, ridge autoregression, last value, seasonal naive (12-month lag), and drift. The LSTM was not registered or activated in the live model registry.", f"Exploratory final-test LSTM MAE cluster-bootstrap range: {output['uncertainty_interval'][0]:.3f} to {output['uncertainty_interval'][1]:.3f}. It resamples four synthetic series and is not a prediction interval."]
    story.extend([Paragraph("- " + item, styles["BodySmall"]) for item in bullets])
    story.extend([Paragraph("Reproducibility and review", styles["Subhead"]), Paragraph("Generator version, dataset SHA-256, split membership, origin-level actuals/predictions/residuals, software versions, test console, checksums and run identifiers accompany this output. Human review status is pending demonstration review. This is not an approved recommendation and does not authorise institutional action.", styles["BodySmall"]), Paragraph("Limitations and defensible interpretation", styles["Subhead"]), Paragraph("This run verifies that dated-series eligibility checks, chronological splitting, fold-local preprocessing, LSTM and baseline execution, uncertainty calculation, evidence linkage and a decision-support rendering pathway execute on deterministic synthetic data. It does not show real-vacancy forecast accuracy, generalisation, or that a model should be promoted or used for decisions. This is not a live-portal registry training event.", styles["BodySmall"]), Paragraph('Adzuna attribution reference: <link href="https://www.adzuna.co.za" color="#0563C1">Adzuna South Africa</link>. Adzuna observations are excluded from this forecast dataset.', styles["BodySmall"])])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#CFD8E3"))
        canvas.line(16*mm, 13*mm, A4[0]-16*mm, 13*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawString(16*mm, 8*mm, f"{RUN_ID} | synthetic functional verification only")
        canvas.drawRightString(A4[0]-16*mm, 8*mm, f"Page {document.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
def write_checksums(package: Path) -> str:
    register = package / "SHA256SUMS.txt"
    files = sorted(path for path in package.rglob("*") if path.is_file() and path != register)
    register.write_text(
        "".join(f"{digest(path)}  {path.relative_to(package).as_posix()}\n" for path in files),
        encoding="utf-8",
    )
    return digest(register)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--permission-record", type=Path, required=True)
    parser.add_argument("--permission-pdf", type=Path, required=True)
    parser.add_argument(
        "--require-gpu",
        action="store_true",
        help="Fail before training unless TensorFlow exposes a CUDA GPU.",
    )
    args = parser.parse_args()
    accelerator = configure_accelerator(args.require_gpu)
    package = args.package.resolve()
    if package.exists():
        raise FileExistsError(f"refusing to overwrite evidence package: {package}")
    for directory in (
        "dataset", "eligibility", "splits", "evaluation", "model/native_artifact", "outputs",
        "operational_verification", "metadata",
    ):
        (package / directory).mkdir(parents=True, exist_ok=True)

    dataset_path = package / "dataset/forecast_observations.csv"
    build_fixture().to_csv(dataset_path, index=False, lineterminator="\n")
    generator_source = Path(__file__).with_name("generate_forecast_fixture.py")
    shutil.copy2(generator_source, package / "dataset/generator.py")
    data_dictionary = pd.DataFrame([
        {"field": name, "definition": definition}
        for name, definition in {
            "series_id": "stable synthetic series identifier", "series_definition": "generating pattern",
            "period": "monthly observation date", "frequency": "monthly", "value": "non-negative integer demand count",
            "source_id": "stable fixture source identifier", "provenance": "generator version and seed",
            "rights_status": "synthetic_reproducible_fixture", "is_synthetic": "always true",
            "eligible": "declared candidate for validation",
        }.items()
    ])
    data_dictionary.to_csv(package / "dataset/data_dictionary.csv", index=False)
    write_negative_fixtures(build_fixture(), package / "dataset/negative_fixtures")
    dataset_sha = digest(dataset_path)  # frozen before evaluation

    raw = pd.read_csv(dataset_path)
    ledger, panel = validate_panel(raw, allow_synthetic=True)
    if len(panel) != 192 or panel.series_id.nunique() != 4:
        raise RuntimeError("unexpected eligible panel identity")
    ledger.drop(columns=["period_parsed", "value_parsed"]).to_csv(
        package / "eligibility/eligibility_ledger.csv", index=False
    )
    source_reconciliation = pd.DataFrame([
        {
            "source_id": "adzuna_jobs_api_trial", "provider": "Adzuna South Africa API",
            "permission_date": "2026-09-10", "permission_scope": "academic study trial access and retention",
            "attribution": "https://www.adzuna.co.za", "acquisition_method": "paginated API queries",
            "collection_dates": "2026-09-08 to 2026-09-20", "query_geography": "Western Cape, South Africa",
            "raw_record_count": 3417, "duplicate_count": 0, "invalid_missing_date_count": 0,
            "exclusions": 3417, "eligible_final_count": 0,
            "query_scope": "python developer; software developer; developer; system administrator; data engineer; systems engineer; business analyst; cyber security; IT support; network engineer; geographies varied among South Africa, Cape Town and Western Cape; page ranges varied",
            "permission_pdf_sha256": digest(args.permission_pdf),
            "redistribution_restrictions": "controlled study retention; no raw records committed to GitHub",
            "eligibility_decision": "rejected_as_empirical_panel",
            "reason": "22 irregular posting months across 2024-07 to 2026-09; collection occurred in 13 days and coverage is concentrated in 2026-08/09; no stable regular acquisition panel",
        },
        {
            "source_id": "job_advert_file_upload", "provider": "DPSA public vacancy circular",
            "permission_date": "public source", "permission_scope": "public vacancy proxy",
            "attribution": "official source retained", "acquisition_method": "file upload",
            "collection_dates": "2026-09-07", "query_geography": "Western Cape public service",
            "raw_record_count": 5, "duplicate_count": 0, "invalid_missing_date_count": 0,
            "exclusions": 5, "eligible_final_count": 0,
            "query_scope": "one five-record public service circular",
            "permission_pdf_sha256": "",
            "redistribution_restrictions": "reacquire from authoritative publisher where required",
            "eligibility_decision": "rejected_as_empirical_panel", "reason": "one posting month only",
        },
        {
            "source_id": "synthetic_forecast_fixture_20261005", "provider": "deterministic generator",
            "permission_date": "not applicable", "permission_scope": "reproducible technical verification",
            "attribution": "generator included", "acquisition_method": GENERATOR_VERSION,
            "collection_dates": "generated 2026-10-05", "query_geography": "not applicable",
            "raw_record_count": 192, "duplicate_count": 0, "invalid_missing_date_count": 0,
            "exclusions": 0, "eligible_final_count": 192,
            "query_scope": "four deterministic generated patterns",
            "permission_pdf_sha256": "",
            "redistribution_restrictions": "none; no provider or personal data",
            "eligibility_decision": "eligible_synthetic_functional_verification", "reason": "four complete regular 48-month series",
        },
    ])
    source_reconciliation.to_csv(package / "eligibility/source_reconciliation.csv", index=False)
    observed_months = [
        ("2024-07", 5), ("2024-11", 1), ("2025-02", 1), ("2025-03", 7),
        ("2025-04", 2), ("2025-05", 5), ("2025-06", 2), ("2025-07", 20),
        ("2025-08", 7), ("2025-09", 3), ("2025-10", 11), ("2025-11", 18),
        ("2025-12", 1), ("2026-01", 4), ("2026-02", 3), ("2026-03", 20),
        ("2026-04", 10), ("2026-05", 48), ("2026-06", 119), ("2026-07", 124),
        ("2026-08", 968), ("2026-09", 2038),
    ]
    pd.DataFrame([
        {
            "series_id": "adzuna_mixed_ict_search_snapshot", "period": period + "-01",
            "frequency": "monthly", "value": count, "source_id": "adzuna_jobs_api_trial",
            "provenance": "live portal PostgreSQL aggregate queried read-only on 2026-10-05; grouped by posted_date",
            "rights_status": "written_academic_permission", "is_synthetic": False,
            "eligible": False,
            "exclusion_reason": "irregular periods and unstable query/geography/acquisition coverage",
        }
        for period, count in observed_months
    ]).to_csv(package / "eligibility/observed_source_month_counts.csv", index=False)

    predictions, membership, metric_payload, uncertainty = evaluate(
        panel, package / "model/native_artifact"
    )
    membership.to_csv(package / "splits/split_membership.csv", index=False)
    predictions.to_csv(package / "evaluation/predictions.csv", index=False)
    json_write(package / "evaluation/metrics.json", metric_payload)
    json_write(package / "evaluation/uncertainty.json", uncertainty)
    comparison = pd.DataFrame([
        {"model": model, **values} for model, values in metric_payload["final_test"].items()
    ])[['model', 'records', 'mae', 'rmse', 'smape_pct']].sort_values("mae")
    comparison.to_csv(package / "evaluation/baseline_comparison.csv", index=False)
    lstm_rank = int(comparison.reset_index(drop=True).index[comparison.model.eq("prototype_lstm")][0]) + 1
    (package / "evaluation/error_analysis.md").write_text(
        "# Forecast error analysis\n\n"
        f"The final test contains {4 * HORIZON} common series-target records per method. "
        f"The prototype LSTM ranked {lstm_rank} of {len(METHODS)} by MAE. "
        "This synthetic result is a functional check, not evidence of labour-market accuracy. "
        "All methods use identical target records; residuals remain in `predictions.csv`. "
        "The three final periods per series were excluded from development metrics and model tuning. "
        "The LSTM uses the architecture declared by the FUTURE prototype service, adapted to "
        "one-step forecasts on this dated panel; it is not a candidate trained or activated in the live registry.\n",
        encoding="utf-8",
    )
    parameters = {
        "run_id": RUN_ID, "seed": SEED, "horizon": HORIZON, "lags": LAGS,
        "development_origins_per_series": DEV_ORIGINS, "lstm": {
            "architecture": ["Input(11,1)", "LSTM(64,relu,return_sequences=True)", "Dropout(0.2)", "LSTM(32,relu)", "Dense(1)"], "epochs": 12,
            "batch_size": 8, "shuffle": False, "optimizer": "Adam(0.001)",
            "scaling": "per-origin min-max fitted to training inputs and targets only",
        }, "ridge": {"alpha": 1.0, "scaling": "per-origin StandardScaler in Pipeline"},
    }
    json_write(package / "model/parameters.json", parameters)
    json_write(package / "model/model_card.json", {
        "name": "prototype_lstm_forecast_functional_verification",
        "version": "1.0.0", "status": STATUS, "intended_use": "technical pathway verification",
        "out_of_scope": ["empirical labour-market accuracy", "institutional action", "production promotion"],
        "dataset_id": "synthetic-forecast-panel-20261005-v1", "dataset_sha256": dataset_sha,
        "evaluation": metric_payload, "limitations": ["synthetic data", "four series", "three final targets per series"],
    })

    final_lstm = predictions[(predictions.split.eq("final_test")) & (predictions.model.eq("prototype_lstm"))].iloc[-1]
    series_row = panel[panel.series_id.eq(final_lstm.series_id)].iloc[0]
    lstm_uncertainty = uncertainty["methods"]["prototype_lstm"]
    output = {
        "output_id": "forecast-decision-support-20261005-v1", "run_id": RUN_ID,
        "dataset_id": "synthetic-forecast-panel-20261005-v1", "dataset_sha256": dataset_sha,
        "forecast_id": final_lstm.forecast_id, "series_id": final_lstm.series_id,
        "series_definition": series_row.series_definition, "observation_period": f"{panel.period.min()} to {panel.period.max()}",
        "forecast_target_period": final_lstm.target_period, "model": "prototype_lstm", "model_version": "1.0.0",
        "point_forecast": float(final_lstm.prediction), "uncertainty_interval": [lstm_uncertainty["lower_95"], lstm_uncertainty["upper_95"]],
        "uncertainty_scope": "exploratory 95% cluster-bootstrap interval for final-test MAE, not a prediction interval",
        "baseline_comparison": comparison.to_dict(orient="records"), "evidence_class": "synthetic functional verification",
        "limitations": ["constructed data", "not empirical accuracy", "no institutional action authorised"],
        "human_review_status": "pending_demonstration_review",
        "decision_statement": "Demonstration decision-support output—no institutional action authorised.",
    }
    output["origin_period"] = final_lstm.origin_period
    output["training_target_end"] = final_lstm.training_target_end
    output["training_rows"] = int(final_lstm.training_rows)
    json_write(package / "outputs/machine_readable_output.json", output)
    create_pdf(package / "outputs/decision_support_output.pdf", output, comparison, metric_payload)

    rights_register = pd.DataFrame([
        {"source_id": "adzuna_jobs_api_trial", "rights_status": "written_academic_permission", "permission_date": "2026-09-10", "attribution_required": True, "attribution_url": "https://www.adzuna.co.za", "permission_record_sha256": digest(args.permission_record), "permission_pdf_sha256": digest(args.permission_pdf), "included_in_forecast_dataset": False},
        {"source_id": "synthetic_forecast_fixture_20261005", "rights_status": "synthetic_reproducible_fixture", "permission_date": "not_applicable", "attribution_required": False, "attribution_url": "", "permission_record_sha256": "", "permission_pdf_sha256": "", "included_in_forecast_dataset": True},
    ])
    rights_register.to_csv(package / "metadata/source_rights_register.csv", index=False)
    json_write(package / "metadata/software_versions.json", {
        "python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__,
        "pandas": pd.__version__, "scikit_learn": sklearn.__version__, "tensorflow": tf.__version__,
        "reportlab": reportlab.Version, "accelerator": accelerator,
    })
    test_command = [
        sys.executable, "-m", "pytest",
        "research_evaluation/tests/test_locked_evaluation.py",
        "research_evaluation/tests/test_forecast_functional_verification.py", "-q",
    ]
    test_run = subprocess.run(
        test_command, cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    console_text = test_run.stdout + ("\nSTDERR:\n" + test_run.stderr if test_run.stderr else "")
    console_path = package / "operational_verification/test_console.txt"
    console_path.write_text(console_text, encoding="utf-8")
    summary_match = __import__("re").search(r"(\d+) passed(?:, (\d+) skipped)?(?:, (\d+) failed)?", console_text)
    test_summary = {
        "command": "python -m pytest research_evaluation/tests/test_locked_evaluation.py research_evaluation/tests/test_forecast_functional_verification.py -q",
        "exit_code": test_run.returncode,
        "passed": int(summary_match.group(1)) if summary_match else 0,
        "skipped": int(summary_match.group(2) or 0) if summary_match else 0,
        "failed": int(summary_match.group(3) or 0) if summary_match else None,
        "console_sha256": digest(console_path),
    }
    json_write(package / "operational_verification/test_report.json", test_summary)
    (package / "operational_verification/test_report.md").write_text(
        "# Operational verification test report\n\n"
        f"- Command: `{test_summary['command']}`\n"
        f"- Exit code: {test_summary['exit_code']}\n"
        f"- Passed: {test_summary['passed']}\n"
        f"- Skipped: {test_summary['skipped']}\n"
        f"- Failed: {test_summary['failed']}\n"
        f"- Console SHA-256: `{test_summary['console_sha256']}`\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0", "package_status": STATUS, "run_id": RUN_ID,
        "dataset_id": "synthetic-forecast-panel-20261005-v1", "dataset_sha256": dataset_sha,
        "dataset_frozen_before_final_evaluation": True, "final_horizon": HORIZON,
        "series_count": 4, "observation_count": 192, "period_start": panel.period.min(), "period_end": panel.period.max(),
        "generator_version": GENERATOR_VERSION, "generator_sha256": digest(package / "dataset/generator.py"),
        "evidence_boundary": "functional execution and traceability only; not empirical labour-market forecast accuracy",
    }
    json_write(package / "metadata/dataset_manifest.json", manifest)
    json_write(package / "PACKAGE_STATUS.json", {
        "status": STATUS, "run_id": RUN_ID, "dataset_id": manifest["dataset_id"],
        "dataset_sha256": dataset_sha, "alignment_package_modified": False,
        "claim": "functional execution and traceability only",
    })
    (package / "README.md").write_text(
        "# Forecast functional-verification evidence\n\n"
        f"Status: `{STATUS}`. This package is independently identifiable from the frozen alignment evidence. "
        "It demonstrates validation of a dated panel, leakage-controlled rolling origins, an executable LSTM, "
        "a transparent ridge candidate, three common baselines, period-level evidence, exploratory uncertainty, "
        "and an evidence-linked human-review output. It does not establish empirical labour-market forecast accuracy.\n",
        encoding="utf-8",
    )
    register_sha = write_checksums(package)
    print(json.dumps({"package": str(package), "run_id": RUN_ID, "dataset_sha256": dataset_sha, "sha256_register": register_sha, "test_report": test_summary, "metrics": metric_payload}, indent=2))
    if test_run.returncode:
        raise SystemExit(test_run.returncode)


if __name__ == "__main__":
    main()
