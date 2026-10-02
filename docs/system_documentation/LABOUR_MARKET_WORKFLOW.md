# Labour-Market Workflow

This document is the operator-facing detail behind workflows 6–13 of the
[END_TO_END_SYSTEM_GUIDE](END_TO_END_SYSTEM_GUIDE.md). It records exactly what the labour-market
stack implements: configuration → import → skill pipeline → mapping review → demand signals →
Demand Outlook. Every endpoint, constant, and script named here is real; where a behaviour is
technical UAT or synthetic, this file says so.

---

## 1. Sources and their governance scope

| Source | Reach | Governance scope |
|---|---|---|
| Stats SA QLFS | Quarterly aggregate labour-force context (public) | `public_evidence`; never vacancy-level |
| DPSA public vacancy file | Current 5-record public-service vacancy proxy | `public_evidence` with proxy limitation |
| Adzuna trial | Operator-held trial postings | `ADZUNA_TRIAL_NOT_EMPIRICAL`, `live_trial_uat`, `empirical_use_permitted=false` |
| `synthetic` provider | Offline fixtures via `FUTURE_SYNTHETIC_JOBS_BASE_URL` | `simulated_uat`, never empirical |

The constants that enforce scope live in `backend/app/routers/labour_market.py`:

```python
ADZUNA_TRIAL_SOURCE_LABEL = "ADZUNA_TRIAL_NOT_EMPIRICAL"
ADZUNA_PIPELINE_RUN_KEY   = "adzuna_labour_market_skill_pipeline_v1"
ADZUNA_SIGNAL_RUN_KEY     = "adzuna_labour_market_signal_generation_v1"
```

When a run is scoped to the Adzuna trial source, responses carry a `trial_scope` block with
`acquisition_mode="live_trial_uat"`, `empirical_use_permitted=False`,
`unit="trial_job_postings"`, `evidence_class="trial_uat"`, and a representativeness note.

## 2. Configure a source

- **Stats SA QLFS**
  - Start extraction: `POST /api/v1/labour-market/extract/statssa`
  - Poll: `GET /api/v1/labour-market/job/{job_id}`
  - Full run: `POST /api/v1/pipeline/statssa/full-run`; list runs with `GET /api/v1/pipeline/runs`.
  - Portal: Data Operations → StatsSA QLFS (2020–2025, 24 files). Each retained observation must
    stay traceable to its official publication, table, and weighting.
- **DPSA vacancy proxy file**
  - Upload: `POST /api/v1/labour-market/jobs/upload` (201; CSV/XLSX/JSON/TXT/PDF, with
    `source_label`, `default_region`, `default_country`). Retain the ingestion job id.
- **Adzuna trial credentials** (operator, backend host)
  - `backend/scripts/configure_adzuna_credentials.py` reads `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`,
    encrypts them into the registered source's `auth_config`, and never prints them.
  - Inspect afterwards: `backend/scripts/inspect_adzuna_trial_uat.py`,
    `backend/scripts/inspect_empirical_readiness_uat.py`.
- **Synthetic provider**
  - Set `FUTURE_SYNTHETIC_JOBS_BASE_URL` to the offline loopback fixture. No credentials.
  - Import: `POST /api/v1/ingestion/adzuna/import-pages?provider=synthetic`
  - List: `GET /api/v1/ingestion/adzuna/posts?provider=synthetic`
  - Records: source `SYNTHETIC_JOB_BOARD`, record type `synthetic_job_payload`,
    `simulated_uat`. They never overwrite or purge stored Adzuna records.

## 3. Import vacancies (pagination, date filters, retries, dedup)

Endpoints in `backend/app/routers/ingestion.py`:

- `POST /ingestion/adzuna/import` — single import
- `POST /ingestion/adzuna/pages/estimate` — request-count preview (never contacts the API)
- `POST /ingestion/adzuna/import-pages` — bounded page-range import
- `GET /ingestion/adzuna/posts` — saved-post listing (browser shows 50 at a time with previous/next)
- `GET /ingestion/adzuna/operations-summary` — import/ops totals

Enforced bounds and retry behaviour (`backend/app/services/ingestion/adzuna_paginated_importer.py`):

| Constant | Value | Meaning |
|---|---|---|
| `PAGE_SIZE_MAX` | 50 | No larger page size accepted |
| `PAGE_NUMBER_MAX` | 250 | No higher page number accepted |
| `MAX_PAGES_PER_RUN` | 250 | At most 250 API pages per run |
| `DEFAULT_PAGE_RANGE` | 10 | Default start/end window |
| `MAX_RETRIES_PER_PAGE` | 2 | Retries per page before giving up on it |
| `RATE_LIMIT_RETRY_SECONDS` | (5, 10, 20) | Backoff ladder for provider rate limits |
| `BACKOFF_SECONDS` | (2, 5, 10) | Backoff ladder for transient failures |
| `CONSECUTIVE_FAILURE_ABORT` | 3 | Consecutive page failures abort the run |
| `DEFAULT_REQUESTS_PER_MINUTE` | 30 | Default rate budget |
| `REQUEST_TIMEOUT_SECONDS` | 30 | Per-request timeout |

`_fetch_with_retry` implements the retry/recovery path. A run stops cleanly with
`stop_reason="aborted_after_consecutive_failures"` or `"empty_page"`. Deduplication is per
advertisement: an existing record is reported as a **duplicate** (not overwritten), and rerunning
the same range inserts nothing new. If the upstream API has no server-side date filter, the portal
applies the date range client-side and counts filtered-out records separately. Runs longer than 10
pages require an explicit confirmation (each page is one API request).

The automated matrix `backend/tests/test_adzuna_paginated_import.py` proves the boundaries:
unknown provider → 422, missing base URL → 503, unauthenticated → 401, viewer role → 403, empty
page → stops, transient 500 → recovered, 50-row pages fully ingested, reruns report duplicates.

## 4. Skill extraction and mapping

- Save postings → `POST /api/v1/labour-market/jobs/upload` (or an import run).
- Run extraction/matching: `POST /api/v1/labour-market/jobs/skill-pipeline`
  (`require_role("ADMIN","ANALYST","DATA_SCIENTIST")`). Response includes `postings_seen`,
  `cleaned_created`, `aliases_created`, `mappings_created`, `mappings_skipped`, plus `run_id`
  and, for trial runs, `ingestion_job_ids` and `trial_scope`.
- Read postings: `GET /api/v1/labour-market/jobs`; a single posting:
  `GET /api/v1/labour-market/job/{job_id}`.
- Read runs: `GET /api/v1/labour-market/jobs/skill-pipeline/runs`.

The pipeline run is persisted as a `PipelineRun` under `labour_market_skill_pipeline_v1` (or
`adzuna_labour_market_skill_pipeline_v1` for trial scope) with the actor and parameters.

## 5. Mapping review (labour side)

Review happens on the shared Skills Alignment workbench:

- `GET /api/v1/skills/governance/workbench` — queue of `candidate`/`needs_review` labour and
  curriculum mappings with evidence text, confidence, and the 0.90 auto-approval threshold; also
  reports the latest `skills.extract.evidence` durable job.
- `POST /api/v1/skills/mappings/{mapping_id}/review` — approve / reject / needs_review with a note
  (required role gate). Decisions create `SkillMappingReviewEvent` rows.
- `POST /api/v1/skills/mappings/bulk-review` — confidence-band decisions; `dry_run` defaults to
  true; noisy rows (long evidence text or newlines) are excluded.
- `GET /api/v1/skills/governance/summary` — status counts and duplicate candidates (≥ 0.86).
- Quality queues (dry-run first): `/skills/quality/low-confidence-mappings/review`,
  `/skills/quality/noisy-job-skills/review`, `/skills/quality/aliases/review`,
  `/skills/quality/duplicates/review`, `/skills/duplicates/merge`.

Only **approved** labour mappings feed signals and evidence. High-confidence mappings
(`confidence >= 0.90`) that match the auto-approval rubric are auto-approved with audit metadata
(`auto_review`).

## 6. Demand-signal generation

- `POST /api/v1/labour-market/jobs/skill-pipeline/signals`
  (`require_role("ADMIN","ANALYST","DATA_SCIENTIST")`). Response reports
  `mappings_considered`, `mappings_approved_used`, `signals_seen/created/updated`,
  `evidence_seen/created/skipped`, `promotion_gate="approved_labour_mappings_only"`, plus
  `run_id` and `trial_scope` when trial-scoped. Runs record under
  `labour_market_signal_generation_v1` or `adzuna_labour_market_signal_generation_v1`.
- Technical-UAT view of trial signals: `GET /api/v1/labour-market/jobs/skill-pipeline/signals` —
  signals with `method="job_skill_demand_v1"` and
  `evidence_scope="adzuna_trial_uat_not_empirical"`, with the trial-scope metadata block.
- The "Generate demand" portal button stays disabled until approved mappings exist.

## 7. Demand Outlook and related read views

- `GET /api/v1/labour-market/signals` — all demand signals ordered by score.
- `GET /api/v1/labour-market/trends`, `/trends/summary` — trend facts.
- `GET /api/v1/analytics/forecasts`, `/analytics/skill-gaps`, `/analytics/summary` — the forecast /
  Demand Outlook panels. Forecasts carry a maturity status and explicit limitations.
- `GET /api/v1/labour-market/jobs/provider-readiness-report` — read-only per-provider register:
  acquisition mode, empirical-use flag, signal coverage by year/quarter, decided-mapping counts,
  plus the latest pipeline/signal runs. Role-gated to ADMIN/ANALYST/DATA_SCIENTIST • 401 without a
  token.

## 8. Readiness gates and trial lifecycle

- `backend/scripts/inspect_empirical_readiness_uat.py` — checks whether trial records satisfy
  empirical readiness (they do not until permission is recorded).
- `backend/scripts/purge_adzuna_trial_uat.py` — an administrator previews and applies the targeted
  trial purge if permission is refused or expires; connector and tests remain.
- `backend/scripts/run_adzuna_trial_uat.py` — bounded operator trial run for coverage/quality/
  usability.

Smoke-test scripts (deployed and offline):
`backend/scripts/smoke_test_labour_market_live.py` and
`backend/scripts/smoke_test_labour_market_mock.py`, producing the
`labour-market-smoke-<mode>-<stamp>.json/.md` artifacts in `docs/evidence/`. The deployed instance
passed both (live and mock) after the 2026-09-09 deployment.

## 9. Evidence

- Decisions and mappings: `backend/app/services/labour_market_skill_pipeline_service.py`,
  `backend/app/services/labour_market_trend_service.py`,
  `backend/app/services/skill_harmonisation_service.py`.
- Snapshot of the whole labour state: `backend/scripts/freeze_labour_evidence_snapshot.py`
  (read-only; feeds `docs/evidence/labour-evidence-snapshot-*.json` + manifest).
- UAT documents: `ADZUNA_PAGINATED_IMPORT_UAT_2026-09-09.md`,
  `ADZUNA_PORTAL_END_TO_END_UAT_2026-09-09.md`, `ADZUNA_TO_DEMAND_OUTLOOK_UAT_2026-09-08.md`,
  `ADZUNA_TRIAL_END_TO_END_UAT_2026-09-08.md`, `JOB_BOARD_PROVIDER_ABSTRACTION_UAT_2026-09-09.md`,
  `STATS_SA_QLFS_PHASE1_PHASE2_UAT_2026-09-07.md`,
  `DPSA_PHASE3_PUBLIC_VACANCY_PILOT_UAT_2026-09-07.md`.

## 10. Counts for verification

`backend/scripts/count_labour_evidence.py` prints read-only counts of the five labour evidence
tables plus recommendations. Baseline after the labour-workflow deployment (2026-09-09):
`job_postings 446`, `skill_mappings 1352`, `approved_mappings 931`, `labour_signals 3166`,
`demand_evidence 45396`, `recommendations 57`.