# Forecast Functional Verification

## Evidence status

`synthetic_functional_verification_not_empirical_accuracy`

The live Adzuna store was audited before constructing a fixture. It contained 3,417 unique dated
records across 22 non-contiguous advertisement months. Collection occurred from 8–20 September 2026
and coverage was heavily concentrated in August–September 2026. This does not establish a stable
30-month observed acquisition panel. The five-record DPSA source covered one posting month. Neither
source passed the empirical forecasting-series gate.

The Adzuna permission record was checked against the archived email PDF. It permits South African
API use and retention for the study, requires attribution and a working link to
<https://www.adzuna.co.za>, and does not change the observed panel's irregular coverage.

## Reproducible route

Generate the deterministic fixture and negative cases:

```powershell
python research_evaluation/generate_forecast_fixture.py `
  --output forecast_observations.csv `
  --negative-dir negative_fixtures
```

Build the evidence package:

```powershell
python research_evaluation/run_forecast_functional_verification.py `
  --require-gpu `
  --package CONTROLLED_PATH/forecast_verification `
  --permission-record CONTROLLED_PATH/adzuna-permission-2026-09-10.md `
  --permission-pdf CONTROLLED_PATH/28-adzuna-written-research-permission.pdf
```

`--require-gpu` is fail-closed: the runner exits before training if TensorFlow cannot expose a
logical GPU. The controlled GPU execution used TensorFlow 2.21.0 under Ubuntu 24.04/WSL2 on an
NVIDIA GeForce GTX 1660 Ti. Accelerator selection is retained in
`metadata/software_versions.json`; the completed four-series run took approximately six minutes.
This execution detail demonstrates the configured pathway and is not an accuracy claim.

The runner freezes and hashes the dataset before evaluation. It reserves the final three months of
each series, uses six preceding one-step rolling origins for development, and fits scaling and model
parameters separately at every origin. It executes the implemented FUTURE LSTM architecture on the
dated synthetic panel, plus ridge autoregression, last-value, seasonal-naive and drift methods, all
on identical target records. The independent dated-panel harness uses the LSTM architecture from the
prototype model service; its candidate is not registered or activated in the live portal. It retains
origin and target periods, training cutoff and row count, split, actual, prediction and residual.

Verify the complete package:

```powershell
python research_evaluation/verify_forecast_package.py CONTROLLED_PATH/forecast_verification
```

## Interpretation

The output is labelled “demonstration decision-support output—no institutional action authorised”.
Bootstrap intervals resample the independent synthetic series and are exploratory because only four
series exist. Executing the model, or outperforming a baseline on constructed data, is not evidence
of real labour-market forecast accuracy.
