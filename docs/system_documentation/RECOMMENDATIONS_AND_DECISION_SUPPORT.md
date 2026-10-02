# Recommendations and Decision Support

This document is the detail behind workflows 17–19 of the
[END_TO_END_SYSTEM_GUIDE](END_TO_END_SYSTEM_GUIDE.md): generating labour demand–curriculum
recommendations, reviewing their dossiers, recording decisions, and exporting reports. All
implemented names here are real; the role and evidence boundaries are enforced server-side.

## 1. Recommendation generation (labour demand / curriculum)

The labour-demand recommendation generator is the implemented path for labour evidence.

- Service: `backend/app/services/labour_recommendation_builder.py`
- CLI: `backend/scripts/build_labour_recommendations.py` (default `--demand-threshold 0.15`,
  `--out-dir docs\evidence`).

Behaviour:

- `RECOMMENDATION_TYPE = "labour_demand_curriculum"`.
- Kinds: `curriculum_gap` (priority `high`, priority_score `0.90`) when the labour signal is not
  covered by the curriculum; `curriculum_coverage` (priority `medium`, priority_score `0.60`)
  when it is covered.
- Inputs are **approved only**: `_require_approved(...)`, `_approved_only(...)`, and the demand
  signal rows. Demand threshold filters weak signals.
- Each recommendation carries `dedup_key` (stable hash of type, kind, skill id, period), source
  ids (demand signals, demand evidence, labour and curriculum mappings), source list, period,
  explanation, and status `pending_review`. `_exists(...)` skips an existing `dedup_key`, so
  reruns add nothing and never overwrite.
- Deterministic: same inputs → same recommendations.

Verified deployed run (2026-09-09): 59 approved curriculum mappings, 872 approved labour mappings,
3166 signals, 45396 demand evidence rows → 7 new recommendations, 0 duplicate skips. (Local
verification used 168 / 13915 / 2622 / 38075 → 9.)

The older analytics generator also exists for the original pipeline
(`backend/app/services/analytics_recommendation_service.py`,
`generate_recommendations`, `POST /api/v1/analytics/generate`); the labour demand–curriculum
generator is the one fed by approved labour evidence.

## 2. Reading recommendations and dossiers

Endpoints in `backend/app/routers/analytics.py`:

- `GET /analytics/recommendations` — list.
- `GET /analytics/recommendations/grouped` — grouped summary.
- `GET /analytics/recommendations/{id}/dossier` — full dossier (recommendation, skill,
  alignment, forecast, evidence summary, explanations, demand evidence, reviews, feedback, status
  history).
- `GET /analytics/recommendations/{id}/lineage` — evidence lineage summary.
- `GET /analytics/recommendations/{id}/explanations` — ordered explanation rows.
- `GET /analytics/recommendations/{id}/reviews` — review history.
- `GET /analytics/recommendations/{id}/feedback` — feedback rows.
- `GET /analytics/recommendations/{id}/status-history` — status changes.

Portal: Decision Portal → Recommendations → dossier; Decision History view.

## 3. Decisions and the academic-approval gate

- `POST /analytics/recommendations/{id}/approve` — `require_role("CURRICULUM_APPROVER")` plus the
  `recommendation.academic_approve` permission.
- `POST /analytics/recommendations/{id}/reject` — same gate.
- `POST /analytics/recommendations/{id}/modify` — same gate; resubmits edited content.
- `POST /analytics/recommendations/{id}/feedback` — any signed-in user records feedback.
- `POST /analytics/recommendations/{id}/committee-decision` — committee decision path, gated on
  `recommendation.academic_approve`.

Administrators deliberately cannot perform the final academic approval: the server enforces the
`curriculum_approver` role and permission, backed by
`backend/tests/test_strict_academic_rbac.py`. Every decision requires a rationale, which is
persisted with the reviewer identity and timestamp in `RecommendationReview`,
`RecommendationFeedback`, and `RecommendationStatusHistory`.

## 4. Governance readiness and committee support

- `GET /analytics/recommendation-governance/readiness` — gate summary.
- `POST /analytics/recommendation-governance/committee-pack` — creates a committee pack report.

## 5. Reports and exports

- `GET /analytics/reports` and `GET /analytics/reports/{id}` — saved evidence snapshots
  (creator, notes, summary, full payload, payload hash).
- `GET /analytics/recommendations/{id}/dossier/report` — generates the recommendation evidence
  dossier report (persisted as a `GeneratedReport`, audited as
  `event_type=recommendation_report`).
- Portal: Reports & Exports → Saved Evidence Snapshots → View. Exports download to the browser's
  download folder (CSV/PDF/JSON depending on the report row buttons); snapshots are immutable
  point-in-time records.

## 6. Evidence and verification

- Evidence artifacts: `docs/evidence/` recommendation-build report from 2026-09-09 and the
  `deploy-labour-flow-2026-09-09/` directory.
- Recommended verification: run `backend/scripts/build_labour_recommendations.py` (report
  confirms new vs skipped), then open a recommendation's dossier and lineage and confirm the
  evidence IDs resolve to approved mappings, signals, and demand-evidence rows.