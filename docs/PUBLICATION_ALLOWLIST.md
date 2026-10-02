# FUTURE/PCLMAS Public Publication Allowlist

This repository must be published using an explicit allowlist. A path not permitted below is excluded until a human rights, privacy, security, and licensing review approves it.

This document authorises preparation of a release candidate only. It does not authorise publishing or pushing externally.

## 1. Preconditions

Before copying any file into a public repository:

1. Create a clean Git repository or verified export; the audited directory had no `.git` metadata.
2. Rotate every credential found in local environment files, even if those files will be excluded.
3. Run secret, personal-information, restricted-text, licence, archive-content, and large-file scans.
4. Review every dependency and bundled asset for redistribution obligations.
5. Complete a clean-room installation and test run from the release candidate.
6. Obtain explicit approval before an external push or release.

## 2. Allowed by path, subject to content review

The following paths may be considered for the public release because they primarily contain source code, schemas, tests, or public-facing documentation. Permission is conditional on a final content scan and does not override third-party rights.

| Path | Conditions |
| --- | --- |
| `backend/app/**` | Source code only. Exclude embedded credentials, real identifiers, copied restricted source text, generated files, and local configuration. |
| `backend/alembic/**`, `backend/migrations/**` | Migration source and documentation only; exclude dumps and generated database contents. |
| `backend/tests/**` | Tests and wholly synthetic fixtures only. Remove real credentials, personal identifiers, source excerpts, environment-specific paths, and examiner observations. |
| `backend/scripts/**` | Review every script for embedded credentials, server identities, private addresses, restricted paths, and destructive operational assumptions. |
| `backend/Dockerfile`, `backend/pytest.ini` | Allowed after clean-room verification. |
| `backend/requirements.txt` | Allowed, but a resolved lockfile and software-version record should be added for reproducibility. |
| `frontend/**` | Authored application source and assets only. Review bundled media, third-party libraries, API endpoints, example identities, and source-map/generated files. |
| `scripts/**` | Only generic setup, migration, evaluation, and test scripts. Exclude deployment credentials, host-specific configuration, certificates, keys, private addresses, and examiner-data paths. |
| `tools/**` | Only generic, documented, rights-safe processing/evaluation tools. Exclude corpora, downloaded source material, generated artifacts, caches, inspection output, and scripts containing personal/server credentials. |
| `.github/workflows/**` | Allowed after checking secrets are referenced only through the hosting platform and no private infrastructure identifiers are embedded. |
| `docker-compose.yml` | Allowed if it continues to require injected secrets and contains no deploy-time credentials or private hostnames. |
| `.env.production.example` | Placeholder values only. Never substitute working credentials. |
| `.gitignore` | Allowed; verify it covers every generated, secret, data, examiner, backup, and local-runtime path. |
| `README.md` | Replace or update before release with accurate clean-room setup, lawful fixture-data acquisition, evaluation, limitations, and public/examiner boundaries. |
| `docs/*.md` | Allow individually, not as a blanket directory copy. Include only authored technical/research documentation that contains no personal information, examiner-only results, restricted excerpts, private infrastructure details, or unlicensed content. |
| `docs/diagrams/**`, `docs/figures/**` | Only diagrams created for this project and confirmed free of restricted content, personal information, or third-party images. Prefer editable source plus rendered output when both are owned. |
| `spec/**` | Review activity logs for personal, credential, private-host, and examiner-only details before inclusion. |
| `nginx/conf/**`, `postgres/**` | Configuration templates and certificate instructions only. Never include private keys, issued certificates, logs, binaries, database files, or vendor documentation copied into the tree. |

No data file is public merely because code can read it. Public data or fixtures require the separate rules below.

## 3. Public data and fixture rule

Only these data categories may enter the public repository:

- small, purpose-built synthetic fixtures that cannot be linked to real people or reconstruct restricted source records;
- derived aggregate tables whose source licence permits redistribution and whose cells do not expose restricted or identifiable information;
- public-source download manifests containing official source URLs, citations, versions, dates, checksums, and extraction instructions, when redistribution of the original file is unnecessary or uncertain.

Every public data file must have a dataset-card entry specifying provenance, licence, intended use, exclusions, schema, synthetic/empirical status, and checksum.

Do not present synthetic fixtures as empirical thesis evidence. Public reproducibility may demonstrate pipeline behavior while the complete scientific evaluation remains in the examiner package.

## 4. Always excluded from the public repository

The following paths or categories are denied by default:

| Path or category | Reason |
| --- | --- |
| `backend/.env`, `backend/.env.bak`, `backend/.env.production`, `.env`, `.env.*` other than reviewed examples | Working secrets, credentials, identities, and deployment details. |
| Any private key, certificate, token, password, database URL with credentials, API key, OIDC secret, JWT secret, or bootstrap credential | Security-sensitive. Rotate if ever exposed. |
| `backend/data/**`, `data/**` | Contains raw, uploaded, staged, processed, backup, curriculum, public-statistics, job-advert, and test material with mixed rights and privacy status. Publish only separately reviewed allowlisted fixtures or download manifests. |
| `models/**`, `backend/models/**`, `backend/output/**` | Models and outputs may encode restricted data or provisional evidence; they are generated and must be handled through reviewed release artifacts. |
| `backend/data/backups/**`, database dumps, encrypted snapshots, rollback evidence, retained raw payloads | Operational or examiner-only evidence; not public data. Encryption does not make a backup publishable. |
| LinkedIn-style or other job-advert exports and scraped/provider data | Personal, contractual, platform, and redistribution risk. |
| CPUT subject guides, prospectuses, module descriptors, curriculum planning material, staged uploads, and institutional documents | Institutional and copyright restrictions unless written permission explicitly permits redistribution. |
| `docs/Thesis/**`, full thesis binaries/extracts, named comparator theses, student numbers, and benchmark thesis text | Personal information and copyright risk; final thesis publication belongs in an approved institutional channel. |
| `docs/CPUT/**` | Internal/institutional and copyright risk pending explicit review. |
| `docs/benchmark_thesis/**` | Third-party thesis text and personal identifiers. |
| `conference/**`, `docs/conference_feedback/**` | Manuscripts, templates, reviews, annotations, correspondence, and third-party material; release only through the authorised publication route. |
| `*.doc`, `*.docx`, `*.pdf` by default | Binary documents can contain hidden metadata, comments, revisions, identifiers, and copyrighted content. Allow only after individual review and metadata sanitisation. |
| `future.zip`, `Future.txt`, `backend_code.txt`, `backend_code - Copy.txt`, `frontend_code.txt`, `thesis_extract.txt`, scratch diagrams/briefs identified in `.gitignore` | Archives, duplicated dumps, scratch or derived content; high risk of secrets, data, and stale claims. |
| `venv/**`, `backend/venv*/**`, `node_modules/**`, caches, `__pycache__`, `.pytest*`, temporary directories | Generated environment or runtime material; large, non-reproducible, and potentially path/identity-bearing. |
| `logs/**`, `*.log`, `stdout.txt`, `stderr.txt` | May disclose credentials, identities, requests, private paths, or infrastructure. |
| `nginx/**/*.exe`, bundled nginx vendor documentation/source, runtime directories | Third-party/generated distribution not needed for source publication. |
| `nginx/certs/**`, `postgres/certs/**` except reviewed README templates | Key and certificate risk. |
| Examiner package data, split membership with sensitive identifiers, retained record-level predictions, reviewer identities, adjudication notes, and restricted error examples | Confidential research evidence. |

## 5. Examiner-only evidence

The examiner package is a separate, access-controlled deliverable and must not be placed in public Git history. Where authorised, it may contain:

- the locked deidentified dataset or a controlled-access reconstruction procedure;
- complete source-rights and eligibility records;
- exclusions and exact split membership;
- full run manifests and dependency locks;
- record-level labels, probabilities, predictions, actuals, forecasts, residuals, and uncertainty;
- complete fold results, confusion matrices, error analysis, and test evidence.

It must still exclude working secrets and unnecessary personal information. Its manifest must specify access, retention, destruction, and redistribution conditions.

## 6. Required release checks

A release candidate passes only if all checks succeed:

```text
[ ] Every included path is allowed above and individually reviewed.
[ ] No denied path or archive is present.
[ ] Secret scan reports zero unresolved findings.
[ ] PII and restricted-text review reports zero unresolved findings.
[ ] Data and asset licences are documented; a code licence is selected by the owner.
[ ] Third-party notices and citation metadata are complete.
[ ] Environment files contain placeholders only.
[ ] Dependency versions are locked and vulnerability review is recorded.
[ ] Public fixtures are synthetic or redistribution-authorised and have checksums/cards.
[ ] README clean-room setup, migration, tests, and fixture evaluation succeed.
[ ] CI verifies the public boundary and reproducibility path.
[ ] Public and examiner package SHA-256 manifests are retained.
[ ] The thesis claims match the verified locked evaluation.
[ ] Explicit approval to publish or push has been received.
```

## 7. Default decision rule

When a file's ownership, licence, privacy status, or scientific role is unclear, exclude it from the public repository. Record the decision in a public-exclusion manifest and route the item for review; do not infer permission from local possession or public accessibility.
