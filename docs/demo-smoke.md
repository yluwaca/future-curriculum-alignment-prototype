# Synthetic demonstration smoke verification

This smoke path exercises the deployed API, database and worker with two visibly
synthetic fixtures. It does not run the locked research evaluator and none of its
records or outputs are empirical evidence.

## Prerequisites

Start the configured application stack, including the API, PostgreSQL/pgvector,
and the durable worker. Use a dedicated demonstration account with the roles
needed for curriculum ingestion, or the locally bootstrapped administrator.
Never put its password in a command, script, fixture, Git commit, or report.

On Windows, the wrapper prompts for the local demo username and a hidden password, uses
the locked backend virtual environment, and removes temporary credential variables when
the run ends:

```powershell
cd C:\Future
.\deploy\smoke\run-smoke.ps1 -BaseUrl http://127.0.0.1:8000
```

```bash
read -r -p 'Demo username: ' PCLMAS_SMOKE_USERNAME
read -r -s -p 'Demo password: ' PCLMAS_SMOKE_PASSWORD; echo
export PCLMAS_SMOKE_USERNAME PCLMAS_SMOKE_PASSWORD
./deploy/smoke/run-smoke.sh
```

The default endpoint is `http://localhost:8080`. Override it with
`PCLMAS_BASE_URL`. A successful run writes `demo/output/smoke-report.json`; the
report retains hashes, stage statuses and output counts, but no access token,
password, personal information, or restricted raw text.

For Windows native deployment, set `PCLMAS_BASE_URL=http://127.0.0.1:8000`;
the independently served frontend is at `http://127.0.0.1:5173`.

## Idempotency and expected behaviour

The curriculum fixture has the stable document key
`synthetic-demo-curriculum-v1` (the ingestion service's canonical slug form). The
vacancy rows have stable `DEMO-JOB-*`
identifiers. The runner reuses the curriculum document if present and relies on
the supported vacancy connector's record deduplication. Rerun the smoke command
to verify the same installation without deleting the database.

The run fails on missing authentication, unhealthy services, rejected uploads,
worker timeout, or unavailable inspectable endpoints. Empty alignment, forecast
or recommendation lists are reported truthfully and do not cause synthetic data
to be treated as eligible evidence. Forecasting must remain unavailable when the
demo history is insufficient.

The current application processes curriculum uploads asynchronously. If the
document is not visible before the default 120-second timeout, inspect the worker
and operational-job logs; do not bypass the worker by inserting database rows.
