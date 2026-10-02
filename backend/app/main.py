"""
FUTURE Platform Backend - Main Application Entry Point
Production-ready FastAPI application with async support
"""

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# Load environment variables first
load_dotenv()

from app.core.bootstrap import (
    ensure_admin_user,
    initialize_rbac,
    initialize_predictive_platform,
    run_migrations,
    startup_summary,
    validate_environment,
)
from app.core.config import settings
from app.core.security import setup_security_headers
from app.core.rate_limit import limiter
from app.core.metrics import metrics
from app.db.session import SessionLocal, engine
from app.routers import auth
from app.routers import admin
from app.routers import analytics
from app.routers import curriculum
from app.routers import future_hooks
from app.routers import ingestion
from app.routers import labour_market
from app.routers import operations
from app.routers import pipeline
from app.routers import processing
from app.routers import predictive
from app.routers import semantic
from app.routers import skills
from app.routers import tenants
from app.routers import ofo
from app.routers import dhet_ofo
from app.routers import sensitivity
from app.routers import fairness
from app.routers import enrichment
from app.routers import alignment_labels
from app.services.operational_job_service import operational_job_service

# Configure logging
log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic"""
    # STARTUP
    logger.info(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    
    # Validate environment
    try:
        validate_environment()
        logger.info("✅ Environment validated")
    except RuntimeError as e:
        logger.error(f"❌ Environment validation failed: {str(e)}")
        sys.exit(1)

    # Check database connection
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Database connection successful")
    except SQLAlchemyError as e:
        logger.error(f"❌ Database connection failed: {str(e)}")
        sys.exit(1)

    # Run pending migrations
    if settings.RUN_MIGRATIONS_ON_STARTUP:
        try:
            run_migrations()
        except Exception as e:
            logger.error(f"❌ Migration execution failed: {str(e)}")
            if settings.FAIL_ON_MIGRATION_ERROR:
                sys.exit(1)
    else:
        logger.info("[BOOTSTRAP] Migrations skipped (RUN_MIGRATIONS_ON_STARTUP=False)")

    # Bootstrap admin user
    if settings.ENABLE_BOOTSTRAP_ADMIN and not settings.is_production:
        try:
            with SessionLocal() as db:
                ensure_admin_user(db)
        except Exception as e:
            logger.error(f"❌ Admin bootstrap failed: {str(e)}")

    # Initialize platform hooks
    initialize_rbac()
    initialize_predictive_platform()
    try:
        with SessionLocal() as db:
            app.state.model_restart_restoration = (
                predictive.model_lifecycle_coordinator.restore_active_models(db)
            )
        if app.state.model_restart_restoration.get("status") != "passed":
            logger.error(
                "[MODEL] Registry restoration completed with failures: %s",
                app.state.model_restart_restoration,
            )
        else:
            logger.info(
                "[MODEL] Registry-designated serving state restored: %s",
                app.state.model_restart_restoration,
            )
    except Exception as exc:
        app.state.model_restart_restoration = {
            "status": "failed",
            "reason": str(exc),
        }
        logger.exception("[MODEL] Registry restoration failed closed")
    # Startup recovery requeues stale durable jobs before worker polling begins.
    operational_job_service.start_worker()

    logger.info("✨ Application ready")
    startup_summary()
    yield  # Application runs here
    
    # SHUTDOWN
    logger.info("🛑 Shutting down application")
    operational_job_service.stop_worker()
    engine.dispose()
    logger.info("✅ Shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    root_path=settings.API_ROOT_PATH,
    lifespan=lifespan,
    docs_url=settings.API_DOCS_URL if settings.ENABLE_DOCS else None,
    redoc_url=settings.API_REDOC_URL if settings.ENABLE_DOCS else None,
    openapi_url=settings.API_OPENAPI_URL if settings.ENABLE_DOCS else None,
    debug=settings.DEBUG,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Setup security headers
setup_security_headers(app, settings)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
    max_age=settings.CORS_MAX_AGE,
)

# Add compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with timing and request ID"""
    import uuid
    import time

    request_id = str(uuid.uuid4())[:8]
    start = time.time()

    try:
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        metrics.record_request(
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        response.headers["X-Request-ID"] = request_id
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code} "
            f"({duration_ms:.0f}ms) [{request_id}]"
        )
        return response
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        logger.error(
            f"{request.method} {request.url.path} - Error ({duration_ms:.0f}ms) [{request_id}]: {str(e)}"
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "request_id": request_id}
        )


# Exception handlers
@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    """Handle database errors"""
    logger.error(f"Database error: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database service unavailable"}
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )


# Include routers
app.include_router(
    auth.router,
    prefix=settings.API_V1_PREFIX,
    tags=["authentication"]
)

app.include_router(
    admin.router,
    prefix=settings.API_V1_PREFIX,
    tags=["admin"]
)

app.include_router(
    labour_market.router,
    prefix=settings.API_V1_PREFIX,
    tags=["labour-market"]
)

app.include_router(
    ingestion.router,
    prefix=settings.API_V1_PREFIX,
    tags=["ingestion"]
)

app.include_router(
    curriculum.router,
    prefix=settings.API_V1_PREFIX,
    tags=["curriculum"]
)

app.include_router(
    predictive.router,
    prefix=settings.API_V1_PREFIX,
    tags=["predictive-analytics"]
)

app.include_router(
    semantic.router,
    prefix=settings.API_V1_PREFIX,
    tags=["semantic-search"]
)

app.include_router(
    skills.router,
    prefix=settings.API_V1_PREFIX,
    tags=["skills"]
)

app.include_router(
    tenants.router,
    prefix=settings.API_V1_PREFIX,
    tags=["tenants"]
)

app.include_router(
    analytics.router,
    prefix=settings.API_V1_PREFIX,
    tags=["analytics"]
)

app.include_router(
    pipeline.router,
    prefix=settings.API_V1_PREFIX,
    tags=["pipeline"]
)

app.include_router(
    processing.router,
    prefix=settings.API_V1_PREFIX,
    tags=["processing"]
)

app.include_router(
    operations.router,
    prefix=settings.API_V1_PREFIX,
    tags=["operations"]
)

app.include_router(
    future_hooks.router,
    prefix=settings.API_V1_PREFIX,
    tags=["future-hooks"]
)

app.include_router(
    ofo.router,
    prefix=settings.API_V1_PREFIX,
    tags=["ofo"]
)

app.include_router(
    dhet_ofo.router,
    prefix=settings.API_V1_PREFIX,
    tags=["dhet-ofo"]
)

app.include_router(
    sensitivity.router,
    prefix=settings.API_V1_PREFIX,
    tags=["sensitivity"]
)

app.include_router(
    fairness.router,
    prefix=settings.API_V1_PREFIX,
    tags=["fairness"]
)

app.include_router(
    enrichment.router,
    prefix=settings.API_V1_PREFIX,
    tags=["vector-enrichment"]
)

app.include_router(
    alignment_labels.router,
    prefix=settings.API_V1_PREFIX,
    tags=["alignment-labels"],
)


# System endpoints
@app.get("/", tags=["system"])
async def root():
    """Root endpoint - API information"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": settings.API_DOCS_URL if settings.ENABLE_DOCS else None
    }


@app.get("/health", tags=["system"], include_in_schema=False)
async def health():
    """Health check endpoint (liveness probe)"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.APP_VERSION,
        "uptime_seconds": round(metrics.get_summary()["uptime_seconds"], 0),
    }


@app.get("/ready", tags=["system"], include_in_schema=False)
async def ready():
    """Readiness check with database connectivity"""
    checks = {}
    all_healthy = True

    # Database check
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        logger.error(f"Readiness check failed: {str(e)}")
        checks["database"] = "disconnected"
        all_healthy = False

    # Disk space check
    import shutil
    try:
        disk = shutil.disk_usage("/")
        free_gb = round(disk.free / (1024**3), 1)
        pct_free = round(disk.free / disk.total * 100, 1)
        checks["disk"] = {"free_gb": free_gb, "free_percent": pct_free}
        if pct_free < 10:
            checks["disk"]["status"] = "warning"
    except Exception:
        checks["disk"] = "unknown"

    # Metrics check
    summary = metrics.get_summary()
    checks["requests_total"] = summary["total_requests"]
    checks["error_rate_percent"] = summary["error_rate"]

    status_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
            "version": settings.APP_VERSION,
        },
    )


@app.get("/metrics", tags=["system"], include_in_schema=False)
async def metrics_endpoint():
    """Prometheus-style metrics endpoint"""
    summary = metrics.get_summary()

    # Database pool stats
    try:
        pool = engine.pool
        db_stats = {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "checked_in": pool.checkedin(),
        }
    except Exception:
        db_stats = {}

    # Process memory
    import os
    try:
        pid = os.getpid()
        import psutil
        proc = psutil.Process(pid)
        mem_mb = round(proc.memory_info().rss / (1024**2), 1)
    except Exception:
        mem_mb = None

    return {
        "requests": {
            "total": summary["total_requests"],
            "errors": summary["total_errors"],
            "error_rate_percent": summary["error_rate"],
            "status_codes": summary["status_codes"],
        },
        "uptime_seconds": summary["uptime_seconds"],
        "response_times": summary["response_times"],
        "database": db_stats,
        "memory_mb": mem_mb,
        "timestamp": summary["timestamp"],
    }
