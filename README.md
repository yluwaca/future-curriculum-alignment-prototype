# FUTURE Curriculum Alignment Prototype

FUTURE is a research prototype for integrating university curriculum evidence, labour-market evidence and reference skill taxonomies into traceable, human-reviewable curriculum-alignment outputs.

The repository supports evidence ingestion, governed skill harmonisation, reviewed alignment labels, immutable dataset snapshots, candidate-model evaluation, promotion gates, evidence-linked recommendations, review history and committee reporting.

## Research boundary

This software was developed and preliminarily tested as a decision-support prototype. It does not establish that use of the prototype improves curriculum outcomes, graduate work readiness, placement rates, employment rates or graduate unemployment.

The final bounded evaluation used a locked 993-row alignment dataset. The evaluated XGBoost candidate produced a holdout F1 score of 0.6957 and ROC-AUC of 0.9124, but chronological grouped validation was unstable. The candidate was therefore retained for research evidence and was not promoted as the active recommendation model. See `docs/FINAL_RESEARCH_EVALUATION.md`.

## Repository structure

- `backend/` -- API, processing, governance and model services, migrations and tests.
- `frontend/` -- browser-based prototype interface.
- `deploy/` -- Windows and Linux deployment and verification scripts.
- `scripts/` -- dataset seeding, evaluation and evidence-pack scripts.
- `research_evaluation/` -- locked-evaluation algorithm, schemas and tests.
- `demo/` -- explicitly synthetic demonstration inputs.
- `data/templates/` -- empty acquisition, rights, manifest and split schemas.
- `data/locked/` -- placeholder for the separately governed research dataset; no empirical data is committed by default.
- `docs/` -- deployment, architecture, workflow, evaluation and data-availability documentation.

## Installation and verification

- Windows native installation: `docs/windows-native-deployment.md`
- Linux installation: `docs/linux-deployment.md`
- Synthetic smoke test: `docs/demo-smoke.md`

Copy `.env.example` to an untracked `.env` file and replace every `CHANGE_ME` value. Never commit credentials or operational secrets.

## Data availability

The public source repository does not automatically include the examiner/eSango dataset, raw provider records, institutional curriculum documents, database contents, trained model binaries or committee evidence. The frozen deidentified dataset will be distributed or deposited according to source rights, ethics approval and CPUT repository requirements. See `docs/DATA_AVAILABILITY.md` and `data/locked/README.md`.

## Reproducibility

The controlled examiner/eSango package identifies the locked dataset and evaluated candidate with complete SHA-256 fingerprints. A controlled reproducibility rerun over the same immutable 993-row snapshot retained row-level holdout and fold probabilities, exact split membership, the native rerun model artefact, software versions and checksums. F1 and confusion-matrix counts reproduced exactly; small differences in probability-sensitive metrics are reported transparently. Release `v1.0.2-operational-verification` is the current frozen alignment and operational reference and is not moved by the forecasting work.

Forecasting is documented and evaluated in a separately identifiable package. The dated Adzuna store did not meet the regular longitudinal-panel gate, so release `v1.1.0-forecast-functional-verification` uses a deterministic synthetic panel to verify validation, leakage-controlled rolling origins, an executable prototype LSTM architecture and ridge candidate, common baselines, period-level evidence, and an evidence-linked output. This demonstrates functional execution and traceability, not empirical labour-market forecast accuracy. See `docs/FORECAST_FUNCTIONAL_VERIFICATION.md`.

## Citation

Citation metadata and the final thesis record will be added after institutional submission.

