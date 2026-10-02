# Examiner clean-room test record

Complete one copy for Windows and one for Ubuntu. Do not record passwords, tokens,
database URLs containing credentials, personal information or raw examiner data.

## Host

- Test identifier:
- Tester:
- Date/time and timezone:
- Operating system/edition/build:
- CPU architecture, RAM and free disk:
- Deployment choice: Windows native / Linux Docker / Linux native Bash
- Package manifest SHA-256 or package revision:
- Docker storage filesystem and free space before build (Linux Docker; minimum 30 GiB):

## Prerequisites

Record version and source for Python, PowerShell/Bash, PostgreSQL, pgvector, Docker Engine,
Compose and browser as applicable.

## Commands and outcomes

| Step | Exact command | Exit code | Outcome/evidence reference |
| --- | --- | ---: | --- |
| Package verification | | | |
| Bootstrap | | | |
| Configure | | | |
| Database/role provisioning | | | |
| Database/pgvector check | | | |
| First migration | | | |
| Second migration | | | |
| Start | | | |
| Create/repair admin | | | |
| Health/readiness | | | |
| First synthetic smoke | | | |
| Second synthetic smoke | | | |
| Stop/start persistence | | | |
| Non-destructive stop | | | |

## Idempotency evidence

- Schema head before/after second migration:
- Stable curriculum document identifier:
- Vacancy identifiers and counts after run 1/run 2:
- Recommendation/review counts after run 1/run 2:
- State retained after restart:

## Failures and undocumented assistance

List every error, workaround, external instruction, manual file edit or privileged action.
An undocumented workaround fails acceptance until incorporated into the package or README.
Redact accidental usernames, email addresses and password-like values before retaining a
transcript as evidence; a disclosed password-like value must be retired even if the failed
command did not persist it.

## Boundary checks

- Demo visibly marked synthetic/non-empirical:
- No empirical examiner dataset loaded:
- No secret printed or retained in report/log:
- No personal/restricted material present:
- Ordinary stop preserved data:

## Verdict

- Passed / failed:
- Blocking defects:
- Tester signature/date:
