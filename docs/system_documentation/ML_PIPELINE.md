# FUTURE Platform — ML Pipeline

> Companion documents: [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).
> Code references use `backend/app/...` paths with line numbers current at time of writing.

## 1. Pipeline at a glance

```
Evidence ingestion ──► Cleaning/harmonisation ──► Independent expert labelling
        │                      │                          │
        ▼                      ▼                          ▼
 Raw archive +         Canonical records          AlignmentReviewTask →
 provenance FKs        (curriculum, trends,       AlignmentExpertLabel
                       postings, skills)                   │
                                                            ▼
                                              LabelDatasetSnapshot  ── LOCKED
                                                            │
                     ┌──────────────────────────────────────┤
                     ▼                                      ▼
        XGBoost alignment classifier            LSTM demand forecaster
        (chronological TimeSeriesSplit CV)      (walk-forward backtesting)
                     │                                      │
                     └────────────┬─────────────────────────┘
                                  ▼
             PredictiveOutput + SHAP explanations + gap scores
                                  ▼
                 HITL governance → recommendations/reports
```

## 2. Data ingestion and feature sources

Three evidence categories feed the pipeline:

| Category | Sources | Becomes |
| --- | --- | --- |
| Curriculum | PDF upload, API import, CPUT prospectus | Curriculum documents → versions → chunks; programme/module records; evidence types |
| Labour-market trends | StatsSA QLFS, CHE VitalStats | Trend facts (`LabourMarketTrendFact`) → canonical signals |
| Current jobs | Uploaded CSV/XLSX, simulated job-board payloads | `JobPosting` rows carrying relational provenance: `source_id` → `data_source`, `ingestion_job_id` → `ingestion_job` (`models/job_posting.py:189-197`; migration `release9_job_posting_provenance`) |

Ingestion guarantees: raw payload archive with checksums, versioned source contracts with drift checks, normaliser registry producing cleaned records, retry/failure diagnostics, and quality-check review queues.

## 3. Dataset construction and locking (leakage safety)

The supervised dataset is built **only from independent human review**, never from model outputs:

1. `AlignmentLabellingService.generate_tasks` pairs curriculum chunks with labour-market windows.
2. Two reviewers label independently (`AlignmentExpertLabel`, stages `first`/`second`); disagreement triggers third-person adjudication. Labels use a 5-point rubric (1 = no alignment … 5 = very strong).
3. `LabelDatasetSnapshotService.create_locked_snapshot` (`services/label_dataset_snapshot_service.py:35-168`) collects completed tasks, enforces inclusion rules (independent reviewer pair, final label present), computes a SHA-256 content fingerprint over schema+rubric+rules+rows, and stores the snapshot as **`approved_locked`** with per-row fingerprints.
4. Training data is loaded exclusively through `ReviewedAlignmentTrainingDatasetService.load` (`services/reviewed_alignment_training_dataset_service.py:23-93`), which re-verifies: lifecycle state (`approved_locked`, :24-25), row count (:33-34), every row fingerprint (:38-41), label-target consistency (:42-43), and the whole-dataset fingerprint (:57-64). Rows are ordered by evidence chronology, then locked row index (:66).

Feature derivation from each locked row (`build_features`, :95-121) uses only source-evidence text statistics (token counts, lexical diversity, Jaccard overlap, vocabulary coverage, length ratios). Explicitly excluded inputs: expert labels, reviewer identities, justifications, present/missing skill annotations, generated model scores.

**Binary target definition**: continuous target = `(final_alignment_label − 1) / 4`. The operational binary aligned/not-aligned label threshold is *learned*, not fixed — see §4.

## 4. XGBoost alignment classifier

Entry point: `ModelService.train_xgboost_alignment_model(db, label_snapshot_id, ...)` (`services/model_service.py:761-1329`). Triggered from Model Lab or durable jobs via `CandidateTrainingService.train` (which also snapshots state and registers the candidate in the model registry).

### 4.1 Validation design
- **Chronological TimeSeriesSplit cross-validation, no shuffling** (`model_service.py:897-899`; split count `min(5, max(2, n // 12))`).
- **Target-threshold sensitivity**: candidate binary thresholds sweep 0.35–0.85; selection maximises mean F1, worst-fold F1 and class balance across chronological folds (`:1222-1226`; fixed cosine-0.75 and full-dataset-median rules are explicitly rejected).
- **Operating threshold** then tuned on validation folds only (maximise F1 → balanced accuracy → recall).
- **Fold-safe preprocessing**: VIF filtering, scalers and class weighting are fitted independently inside each fold's training window; holdout rows are transform-only (`preprocessing_evidence.holdout_rows_used_during_fit = 0`, `:1196-1202`).
- Final holdout: last chronological slice (default `test_size=0.2` after train/validation).

### 4.2 Reported metrics (holdout)
F1, ROC-AUC, PR-AUC, precision, recall, balanced accuracy, Brier score, confusion matrix with denominator check (`evaluate_binary`, `:862-887`), plus per-fold CV mean/std/worst F1 and mean AUCs. Baseline comparisons include DummyClassifier majority and standard baselines.

### 4.3 Fairness guard
An automated fairness audit runs over predictions by faculty (`FairnessAuditService`); a flagged audit blocks the candidate (`fairness_blocked`, `:1256-1271`).

## 5. LSTM demand forecaster

Entry point: `ModelService.train_lstm_forecast_model(db, sequence_length=12, epochs=15, batch_size=16)` (`services/model_service.py:1335-1687`).

- Sequences are derived from active, non-synthetic curriculum modules through `FeatureEngineer.create_lstm_sequence_features` (`feature_engineering.py:637+`), capped at 600 series.
- Architecture: stacked LSTM(64, relu, return_sequences) → Dropout(0.2) → LSTM(32) → Dense(1); MSE loss, Adam lr=0.001.
- **Walk-forward backtesting**: expanding-window `TimeSeriesSplit` folds; Min-Max scaling fitted on each training window only ("minmax_train_fold_only"); metrics per fold (RMSE, MAE, sMAPE, MAPE, direction accuracy) aggregated to mean/std/worst (`:1461-1551`).
- **Holdout**: final temporal slice; reported RMSE/MAE/sMAPE/MAPE/direction accuracy.
- **Baseline honesty**: transparent forecasting baselines — naive last value, seasonal naive lag, moving average w=3, expanding mean, exponential smoothing, linear trend — are evaluated on identical folds and holdout; the model must beat them (`baseline_predictions`, `:1430-1454`; improvement % recorded).
- Maturity status and readiness warnings flow into the registry entry; promotion remains blocked without longer history/stable folds.

## 6. Explainability — TreeSHAP only

- Explainer creation: `shap.TreeExplainer(model)` at serving load, candidate preparation, and evaluation (`model_service.py:189, 230, 1043`).
- Global attribution: mean |SHAP| over a background sample (≤100 rows) → top features with importances recorded in metadata (`:1046-1062`).
- Local attribution: per-prediction `shap_values` → top-10 signed contributions persisted in `PredictiveOutput.shap_summary` (`:1801-1836`).
- **LIME has been fully removed** — no `LimeTabularExplainer` exists anywhere; the legacy DB column `lime_summary` is retained empty purely for schema compatibility (`:1845-1846`: "Legacy database column retained empty; TreeSHAP is exclusive.").
- Limitations text ships with every explainability block: SHAP explains the candidate only, and human curriculum review stays central.

## 7. Descriptive TF-IDF Gap Score

Complementary, model-free interpretability metric:

- `FeatureEngineer.fit_tfidf` fits a shared TF-IDF vectoriser (max 256 features, English stopwords) on curriculum + demand texts (`feature_engineering.py:125-163`).
- For each pair, curriculum and demand vectors are compared with cosine similarity; **gap = 1 − cos(c, d)** via `calculate_gap_score` (`:195-228`).
- Used descriptively (e.g., in `scripts/run_uat_evaluation.py`, which reports baseline vs simulated post-recommendation gaps where absent high-demand terms are appended to the curriculum side and the gap recomputed).
- A semantic variant (sentence-transformer embedding similarity) exists behind a guarded try/except and degrades to the TF-IDF value when unavailable (`feature_engineering.py:473-503`).

## 8. Model lifecycle & governance

1. Training always produces a **candidate** artifact (`xgboost_<timestamp>.pkl` / LSTM equivalents) plus a JSON metadata sidecar (fingerprints, thresholds, folds, baselines, limitations).
2. `ModelRegistryService.register_candidate` records the entry with dataset fingerprint, CV folds, baseline comparison, fairness assessment, explainability summary.
3. Serving-state restoration on backend restart reactivates only what was authorised previously.
4. **Promotion gates** are explicit in every metrics dict (`promotion_gate.status = "blocked_pending_full_validation"` / `"candidate_review_required"`); promotion requires authorised registry action — nothing auto-promotes.
5. Every downstream recommendation carries its evidence group (curriculum / trends / current jobs), confidence, and TreeSHAP explanation into the HITL queue; approve/reject/modify decisions and rationales are audited end-to-end.

## 9. Reproducing results

Use the evaluation script (loads latest locked snapshot; refuses synthetic ones):

```powershell
.\backend\venv\Scripts\python.exe scripts\run_uat_evaluation.py
# optional: --snapshot-version <v>   --gap-top-k 10   --output-dir <dir>
```

Outputs Markdown + JSON under `docs/uat_evaluation/`: XGBoost holdout F1/ROC-AUC/precision/recall (+CV stats), LSTM holdout RMSE/MAE/sMAPE (+walk-forward folds/baselines), TF-IDF gap scores (baseline vs simulated post-recommendation), and the exact locked row count with snapshot fingerprint.

> Reporting rule observed across the repo: only snapshots created from genuinely independent expert reviews may be cited; synthetic DEV seeds exist solely to exercise plumbing.

## 10. Labour-workflow dataset readiness + recommendation pipeline (2026-09-09)

Parallel, deterministic infrastructure for the **labour-market evidence** path
(job postings → skill mappings → demand signals) that is separate from the
curriculum alignment pipeline above:

- `backend/app/services/labour_training_dataset_service.py` — versioned dataset
  builder (`labour-ds-v1-<sha256>`), 17 features (posting/title/skill/match/evidence
  statistics, salary norm, source/region/employment indicators, year/quarter norm,
  declared-skill flag), target `mapping_approval`, posting-keyed leakage-safe splits
  (`hash` or `time`, 70/15/15), default test-label masking with masked
  verification, row dedupe, missing-field report, class distribution, seeded
  `synthetic_fixtures` and a DB `rows_from_db` loader. Deterministic stdlib only
  (no sklearn).
- `backend/app/services/labour_baseline_model_service.py` — `readable-baseline-v1`
  (score = `0.55·confidence + 0.45·token_overlap`, threshold 0.5) with manual
  classification metrics and an evaluation report that ships explicit limitations.
- `backend/app/services/labour_recommendation_builder.py` — deterministic
  decision-support: consumes **approved-only** curriculum and labour mappings plus
  demand signals/evidence, produces `curriculum_gap` (high 0.90) vs
  `curriculum_coverage` (medium 0.60) recommendations with a stable dedup key
  (type, kind, skill, period), persists `Recommendation` rows as
  `pending_review` with a full evidence-id trace and `RecommendationExplanation`
  JSONB. Rejected/unreviewed mappings are excluded by construction; non-approved
  inputs raise unless the validation escape is explicit.

Evidence (all `docs/evidence/`): model-training-readiness-2026-09-09.{json,md},
recommendation-readiness-2026-09-09.{json,md}, the read-only snapshot
labour-evidence-snapshot-20260909T094040Z.json + manifest, and the closure record
labour-workflow-closure-2026-09-09.md.

**Boundary:** these packages are technical UAT only. They exercise plumbing with
deterministic synthetic fixtures and trial evidence (`ADZUNA_TRIAL_NOT_EMPIRICAL`,
`empirical_use_permitted=false`); no model is promoted and no empirical validity
is claimed until expert-labelled labour evidence and institutional validation are
recorded.

**Deployment (2026-09-09 evening):** this package is deployed to the instance backendservices (3 services + related scripts/tests) and the frontend portal changes; docker cp + no-op migration at head elease9b_readiness_indexes, backend healthy. In-container runs reproduced identical deterministic metrics (dataset labour-ds-v1-ea6a995f927af102) and created 7 pending_review recommendations on the serving DB (approved-only inputs). Ledger: docs/evidence/deploy-labour-flow-2026-09-09/README.md.
