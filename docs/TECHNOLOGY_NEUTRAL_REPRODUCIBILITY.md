# Technology-neutral reproducibility protocol

## Purpose

The examiner/eSango deposit must allow another researcher to reconstruct the final evaluation using a different programming language or modelling library. Reproduction therefore depends on open tabular data, explicit decision rules, retained split membership and predictions—not solely on a Python pickle or application database.

## Two evaluation layers

Keep the following layers distinct:

1. **Application candidate evaluation.** This is the 30 September 2026 XGBoost candidate evaluated from locked snapshot `alignment_labels_20260930_133157_149576`. Its exact parameters, feature definition, threshold, split membership, predictions and environment must be exported from the application evidence record.
2. **Portable reference harness.** `research_evaluation/run_locked_evaluation.py` is a publication-safe independent harness. It demonstrates the prespecified eligibility, chronological group splitting, fold-safe feature fitting, threshold selection, metrics, uncertainty and evidence retention. Its classification estimator is TF–IDF plus balanced logistic regression. Its outputs must not be relabelled as the XGBoost candidate results.

## Canonical exchange formats

Use formats with published specifications and broad implementation support:

- UTF-8 CSV with a header row for observations, membership and predictions;
- UTF-8 JSON for manifests, metrics, parameters and software versions;
- UTF-8 Markdown or PDF/A for narrative documentation;
- PNG for screenshots; and
- `SHA256SUMS.txt` for integrity verification.

Native model files may be included as supplementary artefacts, but they are not the only reproducibility mechanism.

## Required frozen files

The controlled deposit should contain:

```text
examiner-esango-package/
  README.md
  dataset/
    alignment_observations.csv
  metadata/
    dataset_manifest.json
    data_dictionary.csv
    source_rights_register.csv
    software_versions.json
  splits/
    split_membership.csv
    fold_membership.csv
  evaluation/
    predictions.csv
    fold_predictions.csv
    metrics.json
    candidate_evaluation.json
  model/
    model_card.json
    model_parameters.json
    feature_specification.json
    operating_threshold.json
    native/                 # optional and access-controlled
  evidence/
    screenshots/
    committee_report.pdf
  algorithms/
    ALGORITHM_SPECIFICATION.md
  SHA256SUMS.txt
```

Every file must refer to the same snapshot and candidate run. The dataset manifest records the snapshot identifier, record count, class balance, dates, eligibility policy, label basis, source rights, split policy and file hashes.

## Minimum observation fields

The canonical alignment dataset is defined by `research_evaluation/schemas/alignment_observations.csv`. Identifiers must be stable but non-identifying. Dates use ISO 8601. Boolean values use `true` or `false`. The target rule is fixed before fitting:

```text
target = 1 when final_alignment_label >= 4; otherwise target = 0
```

The original 1–5 label must be retained so that another researcher can test alternative, declared target definitions without changing the deposited evidence.

## Split and leakage rules

1. Keep all rows sharing a `group_id` in one partition.
2. Order groups by their earliest observation date.
3. Lock the final chronological 20% of groups as the untouched test set.
4. Fit text vocabularies, feature transforms, scalers, imbalance handling and models using development records only.
5. Select the operating threshold only from development or out-of-fold predictions.
6. Apply the frozen pipeline and threshold once to the test set.
7. Retain membership and predictions for every scored test observation.

For the application XGBoost run, the exported membership and prediction files are authoritative. Do not regenerate or replace them after inspecting test performance.

## Metrics

Report at minimum: eligible observations, exclusions, group counts, class balance by partition, operating threshold, confusion matrix, precision, recall, positive-class F1, macro-F1, balanced accuracy, ROC-AUC, PR-AUC, Brier score, fold results and uncertainty intervals. State explicitly when a metric is undefined.

## Independent validation sequence

Another researcher may use R, Julia, Java, MATLAB or another technology by:

1. verifying all SHA-256 digests;
2. reading the manifest and data dictionary;
3. reconstructing the target using the declared rule;
4. using the retained membership rather than creating a new split;
5. fitting preprocessing and the declared model only on the development partition;
6. applying the retained operating threshold to the untouched test probabilities;
7. recomputing metrics from `predictions.csv`; and
8. comparing reproduced values with `metrics.json`, documenting library-related numerical tolerances.

## Access boundary

Public GitHub may contain schemas, algorithms, validators, synthetic examples and metadata. The empirical dataset and native model artefact are published only when every source permits redistribution and the ethics/institutional conditions allow it. Otherwise, eSango should hold a restricted-access package and GitHub should provide its catalogue record and access procedure.

