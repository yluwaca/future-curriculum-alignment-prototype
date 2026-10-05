# Data availability and controlled access

## Public repository

The public code repository contains source code, schemas, deployment scripts, tests and a small synthetic demonstration fixture. It does not contain raw provider vacancy records, database dumps, institutional curriculum documents, personal identifiers, credentials, model caches or the controlled examiner dataset. Release `v1.0.2-operational-verification` is the frozen alignment and operational-verification code reference. Release `v1.1.0-forecast-functional-verification` adds a separate forecasting verification workflow without moving that earlier release.

## Examiner and institutional repository package

The separate controlled archive is named `FUTURE_examiner_esango_FINAL_2026-10-02.zip`. It is linked to locked snapshot `alignment_labels_20260930_133157_149576`, candidate `xgboost-20260930T134244`, dataset fingerprint `f3c0a456e63b40f177d87879dae83adcc99558246dc3217c51dd5ac354174f95`, and training-matrix fingerprint `476969dc8d79b7d60a5ba7a45838025911066182c842b502eae950265670e630`.

Subject to institutional and source-licence conditions, the controlled package contains the original restricted snapshot, a deidentified 993-row technology-neutral dataset, manifest, data dictionary, deterministic split membership, class balance, target definition, candidate and fold metrics, baselines, calibration and threshold evidence, model parameters and model card, official API evidence, committee report and a SHA-256 register.

A controlled reproducibility rerun over the same immutable snapshot retains row-level holdout probabilities, fold probabilities, exact split membership, the native rerun model artefact, software versions and checksums. It reproduces the original F1 and confusion-matrix counts exactly. Small probability-sensitive metric differences are recorded in the comparison evidence and attributed cautiously to the later runtime environment. The original server binary remains governed separately and is not substituted for the rerun artefact.

The archive is for controlled examination and research verification. It must not be published on GitHub or redistributed until CPUT and all source-rights decisions permit broader release. Public-source documents should be reacquired from authoritative publishers where redistribution rights are uncertain.

## Forecast functional-verification package

The forecast package is independently identified from the 993-row alignment package. Adzuna permission was verified, but its dated records did not form a stable, regular historical acquisition panel, so they were excluded from empirical forecast evaluation. The controlled forecast evidence contains a generated 4-series, 48-month, 192-row synthetic fixture, generator and dataset fingerprints, eligibility ledger, leakage-controlled split membership, period-level candidate and baseline predictions, exploratory uncertainty, native candidate artefacts, test evidence, and a demonstration decision-support PDF.

The synthetic fixture and code contain no provider or personal data. A controlled composite archive may include the original unchanged alignment package and the written permission evidence under institutional access conditions. The forecasting claim is limited to functional execution and traceability.
