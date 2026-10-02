# Data availability and controlled access

## Public repository

The public code repository contains source code, schemas, deployment scripts, tests and a small synthetic demonstration fixture. It does not contain raw provider vacancy records, database dumps, institutional curriculum documents, personal identifiers, credentials, model caches or the controlled examiner dataset. Release `v1.0.1-thesis-evidence` is the frozen code reference for the complete preliminary-evaluation evidence workflow.

## Examiner and institutional repository package

The separate controlled archive is named `FUTURE_examiner_esango_FINAL_2026-10-02.zip`. It is linked to locked snapshot `alignment_labels_20260930_133157_149576`, candidate `xgboost-20260930T134244`, dataset fingerprint `f3c0a456e63b40f177d87879dae83adcc99558246dc3217c51dd5ac354174f95`, and training-matrix fingerprint `476969dc8d79b7d60a5ba7a45838025911066182c842b502eae950265670e630`.

Subject to institutional and source-licence conditions, the controlled package contains the original restricted snapshot, a deidentified 993-row technology-neutral dataset, manifest, data dictionary, deterministic split membership, class balance, target definition, candidate and fold metrics, baselines, calibration and threshold evidence, model parameters and model card, official API evidence, committee report and a SHA-256 register.

A controlled reproducibility rerun over the same immutable snapshot retains row-level holdout probabilities, fold probabilities, exact split membership, the native rerun model artefact, software versions and checksums. It reproduces the original F1 and confusion-matrix counts exactly. Small probability-sensitive metric differences are recorded in the comparison evidence and attributed cautiously to the later runtime environment. The original server binary remains governed separately and is not substituted for the rerun artefact.

The archive is for controlled examination and research verification. It must not be published on GitHub or redistributed until CPUT and all source-rights decisions permit broader release. Public-source documents should be reacquired from authoritative publishers where redistribution rights are uncertain.
