# Language-neutral algorithm specification

## A. Dataset eligibility

```text
INPUT: candidate alignment observations
FOR each observation:
    require stable observation_id and group_id
    require observation_date and evidence_cutoff_date
    exclude if evidence_cutoff_date is after observation_date
    exclude synthetic observations from empirical evaluation
    require coding protocol, hashed coder and hashed source identifiers
    require the declared label-review basis
    require non-empty curriculum and labour-market evidence
    require authorised rights status
    require final_alignment_label in {1,2,3,4,5}
    exclude duplicated observation_id values
OUTPUT: eligibility ledger containing included flag and exclusion reason
```

For independently reviewed evidence, require at least two independent reviewers and completed adjudication. Researcher-proxy labels must be identified as exploratory and must not be pooled silently with independently reviewed labels.

## B. Target construction for the final application candidate

```text
normalised_alignment_score = (final_alignment_label - 1) / 4
IF normalised_alignment_score >= 0.35:
    target = 1
ELSE:
    target = 0
```

For the deposited discrete labels, this means labels 3, 4 and 5 are positive; labels 1 and 2 are negative. Retain the original ordinal label and target-rule version. Do not confuse the `0.35` target-construction threshold with the final candidate probability operating threshold of `0.75`.

The separate portable reference harness in `research_evaluation/run_locked_evaluation.py` uses `final_alignment_label >= 4`. It is a methodological reference and does not reproduce the reported XGBoost target unless its declared target rule is changed prospectively and recorded as a different run.

## C. Chronological grouped partition

```text
group_date[group] = minimum observation_date within group
ordered_groups = groups sorted by group_date ascending
cut = floor(0.80 * number_of_groups)
development_groups = ordered_groups before cut
test_groups = ordered_groups from cut onward
assert no group occurs in both partitions
assert both target classes occur in both partitions
freeze split_membership.csv
```

## D. Development-fold procedure

Use expanding chronological group folds. For every fold:

```text
fit all preprocessing using fold-training records only
transform fold-validation records with the fitted preprocessing
fit the candidate using fold-training records only
retain validation probabilities and observation identifiers
compute fold metrics
```

Select any classification threshold using pooled development out-of-fold probabilities only. Freeze the threshold before test evaluation.

## E. Final candidate evaluation

```text
fit preprocessing and candidate on all development records
score each untouched test record once
predicted = 1 when probability >= frozen_threshold; otherwise 0
retain observation_id, group_id, actual, probability, predicted and correctness
compute confusion matrix and prespecified metrics
compute uncertainty using the declared resampling method and seed
compare against baselines on exactly the same test observations
```

The final application candidate is XGBoost. Its exported `model_parameters.json` and `feature_specification.json` must supply the exact booster, objective, class weighting, tree parameters, feature construction and random seed used on 30 September 2026. Do not infer missing parameters from defaults.

## F. Promotion decision

```text
IF any leakage, eligibility, minimum-sample, calibration or stability gate fails:
    candidate_status = evaluated_not_promoted
ELSE IF every prespecified gate passes:
    candidate_status = eligible_for_governed_promotion
```

A holdout result alone does not override poor chronological-fold stability. The final candidate remained unpromoted.

## G. Recommendation boundary

Until a candidate is promoted, generate operational recommendations from the approved active baseline only. Record the method name, evidence identifiers, confidence, reviewer decision, status history and audit event. A recommendation is decision support—not evidence of curriculum, employment or institutional impact.

