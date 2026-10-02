# FUTURE Platform — Developer Guide

> Companion documents: [ARCHITECTURE.md](ARCHITECTURE.md), [USER_GUIDE.md](USER_GUIDE.md), [ML_PIPELINE.md](ML_PIPELINE.md).

## 1. Prerequisites

| Requirement | Version / notes |
| --- | --- |
| Windows 10/11 with PowerShell | dev scripts are PowerShell-native |
| Python | 3.11+ (a project venv already exists at `backend\venv`) |
| PostgreSQL 16 + pgvector | easiest via `docker-compose.yml` (`pgvector/pgvector:pg16`) or a local install with the `vector` extension available |
| NGINX | bundled in `nginx\` for local static serving |
| Docker (optional) | only for the containerised stack |

## 2. Repository orientation

```
backend/app        FastAPI application (routers, services, models, core, schemas, db)
backend/migrations Alembic revisions
backend/tests      pytest suite
frontend/          static HTML/CSS/JS portal (no build step)
scripts/           ops + evaluation scripts (seed data, UAT evaluation)
docs/              research documentation; docs/system_documentation = this handbook
nginx/             local NGINX binary + configs
docker-compose.yml production-style stack (postgres + backend + nginx)
```

## 3. First-time setup

### 3.1 Environment file
Copy and edit `backend\.env` (a template exists at `.env.production.example`). Minimum keys:

```
ENVIRONMENT=development
DATABASE_URL=postgresql+psycopg2://future:<password>@localhost:5432/future
SECRET_KEY=<long random string>
JWT_ISSUER=future-platform
JWT_AUDIENCE=future-users
CORS_ORIGINS=http://localhost:8080
RUN_MIGRATIONS_ON_STARTUP=true   # optional convenience
```

> `Settings()` reads `.env` relative to `backend/`. Scripts under `scripts\` load it automatically.

### 3.2 Python environment
Use the existing venv or recreate:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

Key packages installed: fastapi, sqlalchemy 2, alembic, psycopg2, pgvector, python-jose, passlib, slowapi, pandas, pdfplumber, scikit-learn, xgboost, tensorflow, shap, sentence-transformers/torch, pytest.

### 3.3 Database schema
```powershell
cd backend
.\venv\Scripts\python.exe -m alembic upgrade head
```
69 ordered revisions take the schema from empty to current (release9 includes job-posting provenance columns).

### 3.4 Bootstrap admin (dev only)
On first run outside production the lifespan bootstraps an admin user and RBAC baseline automatically (`ENABLE_BOOTSTRAP_ADMIN=false` disables this in prod).

## 4. Running locally

### Option A — one command (recommended)
```powershell
.\start-future.ps1            # starts backend + nginx, waits for health, opens browser
.\stop-future.ps1             # stop
```
Surfaces:
| Service | URL |
| --- | --- |
| Frontend | http://localhost:8080 |
| Backend API docs | http://localhost:8000/docs |
| Health | http://127.0.0.1:8000/health |

### Option B — manual backend only
```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.0.0 --port 8000
# (use --host 127.0.0.1)
```
Serve the frontend any static way, e.g. `cd frontend; python -m http.server 8080`, or use the bundled nginx (`cd nginx; .\nginx.exe`).

### Option C — containerised stack
```powershell
docker compose up --build
```
Secrets (`POSTGRES_PASSWORD`, `SECRET_KEY`, …) must be provided by your environment/secret manager; compose refuses to start with placeholders.

## 5. Frontend development

- Pure static files — edit, refresh browser (cache-bust query strings like `?v=YYYYMMDD` are used on CSS links).
- `styles.css` is the centralized design system (tokens + components); page CSS files refine layout. Load order: fonts → page css → `styles.css`.
- `shared-nav.js` renders the role-aware sidebar/breadcrumbs; `config.js` holds the API base URL.
- Auth flows live in `auth.js`; each page imports shared modules as ES modules.

## 6. Tests

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests -x -q
```
43 test modules cover RBAC (including strict academic approval), ingestion, curriculum evidence, skills, semantic search, model lifecycle/governance, backups, deployment rehearsals. Keep this green before committing.

## 7. Useful scripts

| Script | Purpose |
| --- | --- |
| `scripts\run_uat_evaluation.py` | End-to-end empirical evaluation over the **locked** reviewed dataset → Markdown+JSON reports in `docs\uat_evaluation\`. Refuses synthetic snapshots. |
| `scripts\seed_locked_reviewed_dataset.py` | Seeds a *synthetic DEV-only* locked snapshot to exercise plumbing. Never cite its metrics. |
| `backend\scripts\*` | Diagnostics (LSTM debug, mock data, sensitivity figures, resilience UAT). |

Run evaluation (full training, allow several minutes):
```powershell
.\backend\venv\Scripts\python.exe scripts\run_uat_evaluation.py
.\backend\venv\Scripts\python.exe scripts\run_uat_evaluation.py --snapshot-version <version> --gap-top-k 10
```

## 8. Making changes safely

1. **Models**: edit `app/models/*` → generate revision `alembic revision --autogenerate -m "..."` → review → `alembic upgrade head`. Add tests.
2. **API**: routers are thin; put logic in `services/`. Every sensitive action should write an audit event.
3. **Permissions**: new protected endpoints use `require_permission("area.action")` or `require_role(...)`. Academic-approval-adjacent endpoints MUST keep the strict-role behaviour (see `core/dependencies.py`).
4. **Frontend**: reuse existing class hooks (`.panel`, `.btn`, tables) from `styles.css`; avoid re-theming components per page.
5. **Migrations discipline**: never edit an applied revision; add a new one.

## 9. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: sqlalchemy` when running scripts | Use the venv interpreter: `.\backend\venv\Scripts\python.exe ...` |
| `ValidationError: SECRET_KEY Field required` | Run from root is fine for `scripts\` (auto-loads env); for manual runs ensure `backend\.env` exists and you launched from `backend\`, or set vars explicitly |
| Backend health check fails | Check DB reachable, `DATABASE_URL`, port 8000 free; see `backend\server.log` / `stderr.txt` |
| Port 8080 occupied | Stop old nginx: `cd nginx; .\nginx.exe -s stop` |
| pgvector missing | Ensure image `pgvector/pgvector:pg16` or `CREATE EXTENSION vector;` (system falls back to JSONB but semantic search degrades) |
