# Windows native examiner deployment

This path runs the backend natively on Windows. It is idempotent: rerunning configuration replaces only non-secret configuration, database extension creation uses `IF NOT EXISTS`, Alembic upgrades to the current head, and start/stop tolerate an already-running or already-stopped service.

## Required software

- 64-bit Python 3.12 (bootstrap installs it through `winget` when absent)
- PostgreSQL 16 and command-line tools
- pgvector 0.8.6 compiled for the installed PostgreSQL 16 server
- PowerShell 7 or Windows PowerShell 5.1
- At least 20 GB free disk before bootstrap; do not proceed to smoke verification while
  `/ready` reports a disk warning

`bootstrap.ps1 -InstallPostgreSQL` verifies Python 3.12 and installs it when absent,
then requests PostgreSQL 16 through `winget`. Use `-SkipPythonInstall` only where
software installation is prohibited and Python has been provisioned separately. It
does not download an unverified third-party pgvector binary: when necessary it installs
Microsoft C++ Build Tools, retrieves the pinned pgvector 0.8.6 official source archive,
verifies its SHA-256, and compiles it for PostgreSQL 16. Git is not required.
Run bootstrap from an Administrator PowerShell session. `database.ps1` is the
authoritative check: it must successfully run `CREATE EXTENSION IF NOT EXISTS vector`.

## Portable package contract

The package root is `Deploy`. It must contain `backend/app/main.py`, `backend/alembic.ini`, migrations, and a hash-locked `backend/requirements.lock`. The scripts reject the current unpinned dependency list as an examiner install.

## Repeatable sequence

From `Deploy/deploy/windows`:

```powershell
.\bootstrap.ps1 -InstallPostgreSQL
.\configure.ps1 -Port 8000 -CorsOrigins http://localhost:8080
.\provision-database.ps1
.\database.ps1
.\migrate.ps1
.\start.ps1
.\create-admin.ps1
.\health.ps1
```

On the first start, loading the pinned numerical and ML libraries can take several
minutes. `health.ps1` waits up to 180 seconds by default and reports the retained backend
log if readiness fails. Messages stating that no active XGBoost or LSTM registry model is
available are expected for the synthetic demo package; they must not be represented as
empirical predictions.

The native frontend is served at `http://127.0.0.1:5173` and calls the loopback API on port 8000.

Run `./verify-scripts.ps1` for the non-destructive script contract check. This parses every PowerShell file, checks the lifecycle surface, rejects known embedded credential patterns, and confirms idempotent pgvector and migration commands are present.

Stop safely with `./stop.ps1`. Rerun the same sequence after an interrupted install. Logs, PID state, and generated configuration are ignored by Git. Secrets are session environment variables and are never written by these scripts.

`provision-database.ps1` prompts without echo for the PostgreSQL administrator and
application-role passwords. It creates or repairs the application role, database and
pgvector extension idempotently. The administrator password is held only for that process
and is removed after `psql` completes. It then sets the application database URL and a
new random application signing key in the current PowerShell process; neither is printed
or persisted. Keep the same PowerShell window open. Never use the administrator account
in `FUTURE_DATABASE_URL`.

The two secrets are different:

- The **PostgreSQL administrator password** was selected by the PostgreSQL installer and
  is used only to create/repair the database and extension.
- The **application-role password** is selected at the hidden provisioning prompt and is
  used by FUTURE to connect as the least-privilege `future` role.
- `FUTURE_SECRET_KEY` is not a password you must invent. Provisioning generates it for
  token signing and retains it only in the current PowerShell process.

## Current acceptance boundary

These scripts are structurally verifiable on this workstation. They are not a clean-room proof until the portable backend, exact dependency lock, PostgreSQL/pgvector installation, empty-database migrations, service readiness, safe demo ingestion, processing, and output checks all pass on a fresh Windows host.
