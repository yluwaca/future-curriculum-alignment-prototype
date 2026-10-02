# RBAC and Review Workflow

This document is the detail behind workflow 1 (user registration, approval, roles, login) and the
review-workflow gates used throughout the platform (curriculum document review, subject-profile
validation, skill-mapping review, and decision history). Companion:
[END_TO_END_SYSTEM_GUIDE](END_TO_END_SYSTEM_GUIDE.md).

## 1. Roles

The role catalogue (seeded in DB migrations `6bd96643a6c5` and `release9a_curriculum_approver_rbac`)
contains exactly five roles:

| `role_id` | Portal name | Core purpose |
|---|---|---|
| `viewer` | Viewer | Read-only decision user; may not ingest, map, train, approve, or operate |
| `analyst` | Analyst | View + Data Operations: ingest, normalise, review/approve mappings, run approved regeneration |
| `data_scientist` | Data Scientist | Analyst + Model Lab: datasets, candidate training, technical evaluation, lifecycle review |
| `curriculum_approver` | Curriculum Approver | Final academic approval of curriculum recommendations; exclusive, server-enforced |
| `admin` | Administrator | Operational and access custodian: approve users, promote models, backups, UAT, rollbacks |

Permissions are granted per role (e.g. `dataset.read`, `model.run`, `model.train`,
`recommendation.academic_approve`, `system.admin`). Portal surfaces gate on these permissions;
the sidebar renders only what the role includes.

## 2. Registration and approval

- **Register:** `POST /api/v1/auth/register` (201; 3/minute). Body: username (3+ chars,
  `^[a-zA-Z0-9._-]+$`), email, password (8+ chars, must include uppercase, lowercase, and digit).
  Account is created `approval_status="pending"` under the institution tenant. Duplicate
  username/email → 409; missing institution configuration → 503.
- **Admin sees pending:** `GET /api/v1/admin/users?status=pending`.
- **Approve with role:** `PUT /api/v1/admin/users/{user_id}/approve`
  (`default_role`, `notes`). Grants the role, sets `approved_by`/`approved_at`,
  activates the `UserRole`, and invalidates the permission cache. Requires `system.admin`.
- **Reject:** `PUT /api/v1/admin/users/{user_id}/reject` (`reason`).
- **Change role / status / reset password:** `PUT /api/v1/admin/users/{user_id}/roles`,
  `/status`, `/reset-password`.
- **Role catalogue:** `GET /api/v1/admin/roles`. **Audit:** `GET /api/v1/admin/audit-logs`.
  **Stats:** `GET /api/v1/admin/stats`.

Administrators assign the least-privileged role that covers a requester's responsibilities.

## 3. Login and sessions

- `POST /api/v1/auth/login` (10/minute per IP) returns a token pair; refresh and revoke are handled
  by `backend/app/services/auth_service.py`.
- `POST /api/v1/auth/logout` revokes the session.
- Failures: incorrect password returns 401; 5 consecutive failures set `is_active=False`
  (`account_locked`, `event_type=security`); pending approval returns 403 "Account pending admin
  approval"; a locked/inactive account returns 403 "User inactive".

## 4. How gates are enforced

- `require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")` — operation-only roles
  (e.g. labour pipeline, curriculum upload, mapping review).
- `require_role("CURRICULUM_APPROVER")` + `require_permission("recommendation.academic_approve")`
  — the exclusive final-academic-approval gate.
- `require_permission("system.admin")` — user administration and operational actions.
- Tenant scoping: `scope_query(...)` in `backend/app/core/tenant_scope.py` limits what a signed-in
  user can read; an unauthenticated call to a protected endpoint returns 401, and a viewer calling
  an operation endpoint returns 403.

UAT coverage: `backend/tests/test_strict_academic_rbac.py`,
`backend/tests/test_unit_admin.py`.

## 5. Review workflow patterns

Every review surface in the platform follows the same pattern: a queue → an evidence panel → a
decision that is recorded with identity, timestamp, and note → history that can be audited.

| Surface | Queue endpoint | Decision endpoint | History endpoint |
|---|---|---|---|
| Curriculum subject profiles | `GET /curriculum/subject-profiles` (+ consolidated) | `PATCH /curriculum/subject-profiles/{id}` | profile `validation_notes`/`validation_status` |
| Curriculum evidence review | `GET /curriculum/evidence-reviews/queue` | `POST /curriculum/versions/{id}/evidence-reviews` | `GET /curriculum/versions/{id}/evidence-reviews` |
| Skill mapping review | `GET /skills/governance/workbench` | `POST /skills/mappings/{id}/review`, `POST /skills/mappings/bulk-review` | `SkillMappingReviewEvent` + `GET /skills/governance/summary` |
| Duplicate/alias/quality | `GET /skills/duplicates/candidates`, `GET /skills/quality/...` | `POST /skills/duplicates/merge`, `POST /skills/quality/.../review` | audit events |
| Recommendation decision | `GET /analytics/recommendations` | `POST /analytics/recommendations/{id}/approve\|reject\|modify` | `GET /analytics/recommendations/{id}/reviews`, `/status-history` |

Notes for reviewers that the portal surfaces depend on:

- A zero extraction count means "no evidence of that type found", not "the document contains
  none"; click through to the extracted chunks before deciding.
- Decisions at or above the auto-approval rubric (`confidence >= 0.90`) are auto-approved with
  audit metadata; everything else needs a human decision with a note.
- Final academic approval is exclusive to `curriculum_approver`; administrators never see that
  control, by design.
- Researcher-operated prototype reviews (labour mapping decisions) are technical UAT and must be
  disclosed as such, not presented as independent expert validation.

## 6. Evidence

- Audit events are written by `backend/app/services/audit_service.py` for registration, admin
  actions, login failures, pipeline runs, signal generation, mapping review, recommendation
  decisions, and report generation; they can be read through `GET /api/v1/admin/audit-logs`.
- Articles of record: `CPUT_ADICTA_UAT_AND_PROVENANCE_2026-09-06.md` (curriculum review chain),
  `DPSA_PHASE3_PUBLIC_VACANCY_PILOT_UAT_2026-09-07.md` and `ADZUNA_*` UAT docs (labour mapping
  review decisions).