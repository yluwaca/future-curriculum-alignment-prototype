# Final bounded prototype evaluation

## Frozen evidence

- Snapshot version: `alignment_labels_20260930_133157_149576`
- Observations: 993
- Dataset fingerprint prefix: `f3c0a456e63b40f1`
- Binary distribution: 953 negative and 40 positive observations
- Candidate: `xgboost-20260930T134244`
- Lifecycle state: evaluated, not approved, not active

The labels were produced through a disclosed rule-assisted workflow and explicitly confirmed by the researcher. They are not represented as independent expert labels.

## Untouched holdout

| Measure | Result |
|---|---:|
| Holdout observations | 199 |
| F1-score | 0.6957 |
| ROC--AUC | 0.9124 |
| PR--AUC | 0.7598 |
| Balanced accuracy | 0.8868 |
| Brier score | 0.0639 |
| True negatives | 184 |
| False positives | 5 |
| False negatives | 2 |
| True positives | 8 |

Eligible baselines on the identical holdout were logistic regression (F1 0.0000), a simple feature-mean rule (F1 0.1070) and majority class (F1 0.0000). A former target-derived comparator was removed from promotion comparison.

## Chronological validation

- Evidence range: December 2025 to September 2026
- Strategy: expanding-window chronological source groups
- Mean fold F1: 0.0192
- F1 standard deviation: 0.0333
- Worst-fold F1: 0.0000
- Mean fold ROC--AUC: 0.6539

## Decision

The candidate was not promoted. Holdout discrimination was promising, but fold stability, calibration, positive-class coverage and group-safe chronology were inadequate for a generalisable predictive claim. The result supports technical feasibility of the governed pipeline, not production readiness or institutional impact.

The operational recommendation workflow continued to use the documented transparent method `canonical_signal_weighted_baseline_v2`. A recommendation must not be represented as an XGBoost output unless its own stored dossier identifies that model.

