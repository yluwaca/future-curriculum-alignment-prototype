# FUTURE Platform — User Guide

> Audience: portal users of all roles. For architecture see [ARCHITECTURE.md](ARCHITECTURE.md); for setup see [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).

## 1. Access and roles

Request access via **Request access** on the landing page (`index.html`). An administrator approves the account and assigns a role. Roles determine which workspaces appear in the left sidebar.

| Role | Intended for | Sees |
| --- | --- | --- |
| **Viewer** | Academics, committee members, observers | Decision Portal dashboards (Overview, Curriculum Evidence, Skills Alignment, Demand Outlook, Decision History, Reports & Exports), Help |
| **Analyst** | Data/ingestion staff | Everything above + **Data Operations** (sources, imports, quality checks, processing) |
| **Data Scientist** | ML practitioners | Analyst surface + **Model Lab** (training, evaluation, registry) |
| **Curriculum Approver** | Senior academic governance | Viewer surfaces + exclusive authority to give final academic approval on recommendations (`recommendation.academic_approve`) — even administrators cannot bypass this control |
| **Admin** | Platform administrators | Everything + **System Operations** (health, backups, deployment, UAT) + **User Admin** |

> Note: administrators have broad bypass powers *except* academic approval, which is deliberately restricted to Curriculum Approvers.

## 2. Signing in

1. Open `http://localhost:8080` (landing page) → sign in.
2. Sessions are JWT-based; use **Change Password** in the top bar at any time.
3. The sidebar highlights your current workspace; breadcrumbs show where you are.

## 3. Decision Portal (all roles)

One page, several views — switch using the sidebar:

### 3.1 Overview
- KPI cards: curriculum records, skills mapped, average alignment, pending reviews.
- **Recommendation Priorities** bar list and **Latest Recommendations** table with filter.
- Select a recommendation to open its **Dossier**: evidence, forecast, explanations (TreeSHAP), decision history.

### 3.2 Curriculum Evidence
- Programme/module evidence coverage, document quality scores, ingestion activity, provenance (which source/job produced each item).

### 3.3 Skills Alignment
- Reviewed skill mappings, labour-market demand evidence, alignment indicators with missing/weak/strong coverage framing.

### 3.4 Demand Outlook
- Interpretable demand signals and forecasts with confidence and explicit limitations/maturity status. Treat forecasts as indicative only; check the stated model maturity before quoting numbers.

### 3.5 Decision History
- Every recorded approve/reject/modify decision with rationale, feedback, and status history.

### 3.6 Reports & Exports
- Generate/export snapshots for committee meetings (PDF export supported).

## 4. Recommendation review workflow

1. Open **Recommendations** (sidebar).
2. Filter/search the queue; open a recommendation's dossier to inspect evidence: curriculum chunk, job-trend signals, current-job demand, gap explanation, confidence.
3. Choose an action:
   - **Approve** — accept as-is,
   - **Modify** — edit content, then submit,
   - **Reject** — record a reason.
4. Decisions require a written rationale; all actions are audited.
5. Final **academic approval** appears only for Curriculum Approver accounts.

## 5. Data Operations (Analyst, Data Scientist, Admin)

1. **Sources** tab: register/enable/disable sources, run health checks, view schedules/freshness/retry policy.
2. **Imports**: upload curriculum PDFs or job-ad datasets (CSV/XLSX), trigger CPUT prospectus import or simulated job-board payloads.
3. **Jobs**: monitor ingestion jobs (progress, counts, failures, retries). Raw records keep checksums/provenance for every row.
4. **Quality**: review source-contract drift, failed/noisy records, low-confidence rows in the review queue; correct or skip items.
5. **Processing**: run the one-click processing chain (full run, or alignment-only / forecast-only / recommendations-only rerun) from cleaned evidence to canonical outputs.

### 5.1 Controlled curriculum upload

For an official curriculum file, complete institution, faculty, department, exact
programme name, module/document title, stable document key, evidence type, evidence year
and currency before selecting **Upload Curriculum File**. A green "file accepted as job"
message proves queue acceptance only. While the request is being submitted, the button is
disabled and displays **Uploading...**; do not refresh or submit the same file again. Keep
the job identifier, then wait for completion and
inspect the resulting document version, page/chunk counts, extracted module profile and
provenance against the original source. Correct or reject inaccurate extraction before
validating the curriculum evidence or generating skill mappings. Pilot one representative
file before bulk-uploading a programme corpus.

### 5.2 End-to-end curriculum evidence checklist

Complete curriculum preparation in this order:

1. Upload each authorised curriculum document once and retain the accepted job identifier.
2. Wait for ingestion to complete; confirm the expected document, version, page/chunk count and provenance.
3. Validate or correct the subject profile: hierarchy, exact programme name/code, canonical subject code/name, evidence year, NQF level, credits, purpose and prerequisites.
4. Independently review the extracted document version. Validate it only when the correct source is readable and contains sufficient module, outcome and assessment evidence.
5. Reconcile duplicate or alias subject codes before downstream processing. The active programme module count must match the set of canonical validated subject codes.
6. Generate curriculum-skill mappings only after subject profiles and document versions are validated.
7. Review every uncertain mapping. Approve direct outcomes, assessed competencies and clearly taught topics; reject titles, URLs, references, incidental matches and broken fragments. Record a concise reason.
8. Refresh and confirm: zero outstanding profiles, zero unreviewed document versions, zero mapping candidates, no duplicate active modules, and 100% required module metadata.

A green upload notice proves only that the file was accepted into the queue. A green
subject-profile status does not replace document-evidence validation, and an auto-approved
mapping does not remove the need to review the remaining candidates.

Curriculum-side preparation is complete once the checklist above passes. It does not mean
the full alignment study is complete. Programme governance evidence (including applicable
CHE, DHET, SAQA and institutional records), validated labour-market evidence, and two-person
independent alignment labelling remain separate downstream gates.

For a prototype evaluation, do not mark missing programme-governance evidence as verified
merely to satisfy the user-interface indicator. The chain is an audited interpretation
control, not a prerequisite for ingesting authorised labour-market evidence. Where an
official programme-specific CHE accreditation reference, DHET PQM record, SAQA registration,
or institutional approval record is unavailable, retain the unverified state and disclose
the limitation. The five programme layers used by the readiness indicator are CHE
accreditation, DHET PQM, SAQA registration, institutional programme, and module curriculum;
HEQSF and the CHE standard are contextual layers.

For the CPUT Applications Development pilot, use programme code **ADICTA**. Do not use
**ADICTC**, which identifies Communication Networks. The public SAQA qualification is
**104714**, *Advanced Diploma in Information and Communication Technology in Applications
Development*, CPUT, NQF Level 7, 120 credits. The CPUT prospectus page for ADICTA is the
institutional programme source. SAQA's identification of CHE as quality-assurance
functionary supports provenance but does not replace the programme-specific CHE
accreditation reference or DHET PQM approval reference. Keep those two layers unverified
until the official references are obtained from CPUT.

The SAQA qualification rules are the authoritative public cross-check for the pilot's
credit total: ADT470S 20, ADP470S 20, PRJ470S 40, REM475S 20 and PFD470S 20 (120 total).
Do not replace an unknown institutional approval date with an assumed date. SAQA's public
registration start date is 3 October 2024 and is a different event from CPUT Senate approval,
CHE accreditation or DHET PQM approval. Record each date only against its own source.

Likewise, synthetic or researcher-entered alignment labels may be used in a segregated UAT
dataset to demonstrate task generation, independent submissions, disagreement routing,
adjudication and locking. They must be labelled as test data, excluded from empirical
findings, and must not be described as independent expert validation. If experts were not
recruited, empirical expert validation remains deferred future work.

### 5.3 RBAC technical acceptance test

Create separate UAT accounts for `viewer`, `analyst`, `data_scientist`,
`curriculum_approver`, and `admin`. Create a second Analyst account to test paired review.
Use unique passwords and email addresses, and include `uat` in each username so that the
audit trail cannot be mistaken for empirical expert review. Confirm permitted actions work,
forbidden actions return access denied, and each audit event records the correct identity.
Test both agreement and disagreement using the two Analyst accounts. The Administrator may
manage access but must not be able to exercise the Curriculum Approver's exclusive academic
decision permission. Record screenshots or exported audit results in the technical test
evidence and disclose that all UAT identities were operated by the researcher.

An alignment disagreement test requires at least one validated curriculum version and one
traceable labour-market signal. If no labour evidence has been loaded, the correct result is
zero eligible review tasks; defer the paired-label disagreement test until the first labelled
labour UAT source exists. Never create an apparently real labour signal solely to make the
workflow turn green.

### 5.4 Synthetic governance UAT

Where a CHE accreditation letter, DHET PQM approval or institutional approval record is not
publicly available within the approved ethics scope, use a segregated synthetic UAT record
only to exercise the software path. Its title must begin `SYNTHETIC UAT — NOT EMPIRICAL`, its
metadata must contain `evidence_class=synthetic_uat` and `empirical_use_permitted=false`, and
it must state the official fields needed for replacement. Synthetic records may satisfy the
separate `technical_demo_ready` indicator but are excluded from `programme_evidence_ready`.
This lets the quantitative prototype be technically tested without claiming access to, or
findings from, non-public institutional information.

### 5.5 Stats SA QLFS labour-evidence intake

Use **Data Operations → StatsSA QLFS** for official quarterly labour-market context. For
the current pilot, enter start year **2020**, end year **2025**, and maximum files **24**;
leave **Discovery only** clear and **Extract tables** selected. Submit once and retain the
job identifier. A multi-year extraction can take several minutes. Wait until the durable
job reads **Completed**, with 24 publications seen and zero unexplained failures, before
selecting **Run StatsSA Pipeline** for that job.

QLFS is official empirical evidence about labour-force conditions, but it is not a vacancy
dataset and contains no direct proof that employers demand a particular curriculum skill.
Keep its observation type as `qlfs_aggregate`; retain year, quarter, geography, measure,
unit, table/variable reference, source URL, checksum and acquisition timestamp. Before an
extracted measure is eligible for analysis, validate its table title, population, geography,
unit, weighting, footnotes, occupation/industry classification and any comparability break.
In particular, do not relabel quarterly QLFS estimates as monthly vacancies or real-time
skill demand. Vacancy-level skill alignment remains a separate evidence stream.

The import is technically complete when the source job completes, the pipeline run has no
failed stages, raw files and hashes are retained, quality checks have no blocking errors,
and trend facts/canonical signals can be traced back to a publication and table. Technical
completion does not by itself make every extracted row empirically eligible.

### 5.6 DPSA public-vacancy proxy pilot

Use **Data Operations → Job Advert Dataset** for an authorised vacancy file. Record an exact
source label, region and country, then retain the ingestion job identifier. The current
technical pilot uses five Western Cape ICT-titled posts extracted from DPSA Public Service
Vacancy Circular 11 of 2026. Its evidence role is `public_service_vacancy_proxy`: it tests
vacancy ingestion, cleaning, skill matching, human review and approved-evidence promotion,
but it is not a sample of the whole Western Cape or private-sector ICT labour market.

After upload, run the job-skill pipeline to create candidate mappings. Review the source
text for every candidate, choose approve/reject/further review, and record a rationale. A
researcher-operated prototype decision must explicitly say that it is technical UAT and is
not an independent expert review. Only mappings with `mapping_status=approved` may create
job-skill signals or skill-demand evidence. Candidate and rejected mappings are excluded.

When all contributing adverts are from DPSA, downstream signals retain
`evidence_scope=public_service_vacancy_proxy`, use the unit
`public_service_job_postings`, and carry a representativeness warning. Do not use this pilot
for longitudinal forecasting or generalise its counts beyond the five retained posts.
Empirical market claims require a lawful, consecutive, broader vacancy corpus with stable
identifiers, dates, locations and advert text; 27 or more monthly periods are the minimum
forecasting gate, 36 are preferred, and 60 are required before considering LSTM evaluation.

### 5.7 Adzuna technical-trial UAT and academic research permission

Adzuna was configured as a provisional licensed vacancy connector for a bounded provider
trial. During the trial it was used to validate coverage, quality and usability through
the normal end-to-end workflow. Every posting acquired in that period carries the exact
source marker `ADZUNA_TRIAL_NOT_EMPIRICAL`, and those historical rows and their derived
signals/evidence keep their original trial acquisition metadata (`acquisition_mode=live_trial_uat`,
`empirical_use_permitted=false`) as an auditable record.

**Written academic research permission (2026-09-10):** Adzuna Support (Jesse Mutenyo) granted
written permission for the CPUT academic study to use the Adzuna South Africa API with trial
access and retention for thesis/analysis, on condition of full attribution to
`https://www.adzuna.co.za` in any thesis, publication, research, or examiner package. The
permission record is registered on the `adzuna_jobs_api_trial` source
(`permission_status=written_academic_permission`, `empirical_use_permitted=true`); evidence:
[docs/evidence/adzuna-permission-2026-09-10.md](../../docs/evidence/adzuna-permission-2026-09-10.md).
New ingestion runs, pipeline runs, signals and demand evidence carry the permission metadata
plus the attribution requirement, and report/exam-package exports include the attribution note.
Historical pre-permission rows are never rewritten.

Use a maximum of five results for a diagnostic UAT run, preserve the ingestion job ID,
review every generated candidate, and state in each review note that the decision was a
researcher-operated technical UAT decision (pre-permission) or a researcher-reviewed
approval under the academic permission where required. Rejected mappings
are evidence that false-positive and disagreement handling works; never approve a mapping
merely to clear the queue. Trial candidates do not block empirical readiness.

If permission is refused or expires, first preview and then explicitly
apply `backend/scripts/purge_adzuna_trial_uat.py`; this deletes the labelled trial records
and derivatives while retaining the connector and automated tests. Any future licence change
is recorded in the source-rights register before changing the empirical-use gate.

## 6. Model Lab (Data Scientist, Admin)

1. Inspect current model status (active version, metrics, dataset fingerprint).
2. Launch candidate training:
   - **XGBoost alignment** — requires a locked reviewed-label snapshot; runs chronological TimeSeriesSplit CV plus holdout evaluation (F1, ROC-AUC, precision, recall).
   - **LSTM forecast** — runs expanding-window walk-forward backtesting plus holdout (RMSE, MAE, sMAPE).
3. Compare candidates against baselines and prior registry entries; read SHAP global summaries and limitations.
4. Promotion is gated: candidates stay "candidate" until an authorised promotion decision is made. Nothing auto-promotes.

## 7. System Operations (Admin)

Service health, backup/restore drills, retention policy, deployment readiness, migration/rollback rehearsal, external monitoring/alerts, strict tenant isolation checks, and UAT summaries.

The **Operational Release Criteria (Reference)** table is explanatory guidance, not a live
status report and not a production certification. Production or release-readiness claims
must be supported by the live reports on the same page, including installed TLS, bootstrap
account disablement, monitoring ownership, a recoverable encrypted backup, rollback
evidence and a recorded UAT run.

## 7.1 Synthetic demo versus validation data

The Phase 1 demo smoke workflow creates records explicitly labelled `SYNTHETIC DEMO`.
Docker preserves these records in its PostgreSQL named volume after stop/start and image
rebuilds. They prove only that the ingestion and portal plumbing works. They must not be
treated as curriculum evidence, labour-market evidence, model-training data or findings.

Before a Phase 2 validation dataset is loaded, an administrator must verify zero relevant
records in a separately identified validation database. If synthetic records are visible,
stop and use a separate clean validation volume or obtain authorisation for a documented
reset. Never run the demo smoke workflow against the validation database.

### Interpreting curriculum quality colours

Validating a subject profile removes that profile from the outstanding review list, but it
does not automatically turn every curriculum-quality indicator green. Credits and NQF
percentages are calculated across underlying module records, and the mapping warning remains
until reviewed curriculum-skill mappings exist. Retained document versions may also increase
the evidence-chunk count. Treat red indicators as specific data-quality diagnostics: inspect
the affected module identities and current-version evidence rather than repeatedly saving an
already validated profile.

## 8. User Admin (Admin)

- Approve pending access requests, assign/change roles, deactivate accounts.
- Remember: role changes cannot grant anyone academic approval rights except via `curriculum_approver`.

## 9. Help resources in-product

- **Help Manual** (`help-manual.html`): step-by-step task instructions per workspace.
- **Public User Guide** (`user-guide.html`): responsible-interpretation guidance.

## 10. Good practice

1. Check **provenance and dates** before interpreting any number.
2. Prefer the dossier's evidence over headline scores.
3. Record meaningful rationales — they become the audit trail.
4. Never treat predictions as automatic decisions; the platform supports human judgement, it does not replace it.
