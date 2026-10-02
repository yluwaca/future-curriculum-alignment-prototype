# Data availability and controlled access

## Public repository

The public code repository contains source code, schemas, deployment scripts, tests and a small synthetic demonstration fixture. It does not contain raw provider vacancy records, database dumps, institutional curriculum documents, personal identifiers, credentials, model caches or the controlled examiner dataset. Release `v1.0.0-thesis-prototype` is the frozen code reference for the final preliminary evaluation.

## Examiner and institutional repository package

The separate controlled archive is named `FUTURE_examiner_esango_FINAL_2026-10-02.zip`. It is linked to locked snapshot `alignment_labels_20260930_133157_149576`, candidate `xgboost-20260930T134244`, dataset fingerprint `f3c0a456e63b40f177d87879dae83adcc99558246dc3217c51dd5ac354174f95`, and training-matrix fingerprint `476969dc8d79b7d60a5ba7a45838025911066182c842b502eae950265670e630`.

Subject to institutional and source-licence conditions, the controlled package contains the original restricted snapshot, a deidentified 993-row technology-neutral dataset, manifest, data dictionary, deterministic split membership, class balance, target definition, candidate and fold metrics, baselines, calibration and threshold evidence, model parameters and model card, official API evidence, committee report and a SHA-256 register.

Row-level and fold-level probability outputs were not retained by the completed run. The native candidate binary remains on the governed FUTURE server and was not exposed through its official read-only API. The package records those limitations explicitly; it does not fabricate missing run artefacts.

The archive is for controlled examination and research verification. It must not be published on GitHub or redistributed until CPUT and all source-rights decisions permit broader release. Public-source documents should be reacquired from authoritative publishers where redistribution rights are uncertain.
