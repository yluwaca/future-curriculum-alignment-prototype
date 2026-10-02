# Locked research evaluation

This directory is the publication-safe evaluation harness for the thesis. It is independent of the live application database and refuses synthetic, undated, unreviewed, duplicate, or unauthorized observations.

Copy the header-only schemas from `schemas/` into controlled examiner storage and populate them with authorized records. Never commit populated examiner data.

The alignment target is fixed before fitting: `aligned = 1` when the final 1–5 rubric label is at least 4; otherwise 0. Groups remain intact, the final chronological 20% of groups is untouched test data, and threshold selection uses development out-of-fold predictions only. `--label-basis researcher_proxy` produces an explicitly exploratory run; it can never be silently pooled with or represented as an independently reviewed confirmatory run.

The prespecified minimum alignment gate is 120 eligible records, 30 independent leakage groups, and 40 records in each binary class. Failure returns `not evaluable`; the gate must not be relaxed after examining outcomes.

Forecast evaluation requires a regular dated panel. Each series declares `monthly` or `quarterly` frequency and must have no missing periods. It uses rolling one-step origins: the final `horizon` targets per series are locked test records and the preceding origins are development folds. At each origin, the autoregression, its scaler, and every baseline see only values and training targets strictly before the forecast target. The candidate and all baselines are scored on identical retained records. Synthetic, duplicate, irregular, short, constant, all-zero, or unauthorized series are rejected. `horizon` is the number of final rolling test origins, not a multi-step forecast made from one origin.

```powershell
python -m pip install -r research_evaluation/requirements-evaluation.lock
python research_evaluation/run_locked_evaluation.py alignment --input EXAMINER_PATH/alignment.csv --output EXAMINER_PATH/runs
python research_evaluation/run_locked_evaluation.py forecast --input EXAMINER_PATH/forecast.csv --output EXAMINER_PATH/runs --horizon 3
python -m pytest research_evaluation/tests -q
```

Runs retain eligibility, membership, predictions, folds, metrics, uncertainty, parameters, versions, seeds, fingerprints, and checksums. A run completes only after every eligibility gate passes.
