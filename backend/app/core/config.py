# backend/app/core/config.py

from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    """
    FUTURE Platform configuration.
    Production-ready Pydantic v2 settings.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =====================================================
    # Application
    # =====================================================

    APP_NAME: str = "FUTURE Platform"

    APP_VERSION: str = "1.0.0"

    APP_DESCRIPTION: str = (
        "Predictive model for curriculum-labour market alignment"
    )

    ENVIRONMENT: str = "development"

    DEBUG: bool = False

    LOG_LEVEL: str = "INFO"

    # =====================================================
    # Server
    # =====================================================

    HOST: str = "127.0.0.1"

    PORT: int = 8000

    WORKERS: int = 1

    RELOAD: bool = True

    ACCESS_LOG: bool = True

    # =====================================================
    # API
    # =====================================================

    API_ROOT_PATH: str = ""

    API_V1_PREFIX: str = "/api/v1"

    ENABLE_DOCS: bool = True

    API_DOCS_URL: Optional[str] = "/docs"

    API_REDOC_URL: Optional[str] = "/redoc"

    API_OPENAPI_URL: Optional[str] = "/openapi.json"

    # =====================================================
    # Database
    # =====================================================

    DATABASE_URL: str = Field(
        default=(
            "postgresql://future_app:"
            "password@localhost:5432/future_db"
        )
    )

    DATABASE_SCHEMA: str = "public"

    DATABASE_SSL_MODE: str = "prefer"

    DATABASE_POOL_SIZE: int = 5

    DATABASE_MAX_OVERFLOW: int = 10

    DATABASE_ECHO: bool = False

    # =====================================================
    # JWT / Security
    # =====================================================

    SECRET_KEY: str

    SECRET_PROVIDER: str = "development_env"

    SECRET_ROTATION_OWNER: Optional[str] = None

    SECRET_ROTATION_DAYS: int = 90

    ALGORITHM: str = "HS256"

    JWT_ISSUER: str = "future-platform"

    JWT_AUDIENCE: str = "future-api"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # =====================================================
    # CORS
    # =====================================================

    CORS_ALLOW_CREDENTIALS: bool = True

    CORS_ALLOW_METHODS: List[str] = [
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ]

    CORS_ALLOW_HEADERS: List[str] = [
        "Authorization",
        "Content-Type",
        "X-Request-ID",
    ]

    CORS_EXPOSE_HEADERS: List[str] = [
        "X-Request-ID",
    ]

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

    CORS_MAX_AGE: int = 3600

    # =====================================================
    # Middleware
    # =====================================================

    ENABLE_GZIP: bool = True

    GZIP_MIN_SIZE: int = 1000

    # =====================================================
    # Logging
    # =====================================================

    LOG_FILE_PATH: str = "./logs/backend.log"

    # =====================================================
    # Storage Paths
    # =====================================================

    STATSSA_DOWNLOAD_PATH: str = "data/raw/statssa"

    CHE_DOWNLOAD_PATH: str = "data/raw/che"

    CURRICULUM_UPLOAD_PATH: str = "data/raw/curriculum"

    DHET_OFO_EVIDENCE_PATH: str = "data/evidence/dhet_ofo_2021"

    ESCO_BUNDLE_EVIDENCE_PATH: str = "data/evidence/esco_bundle"

    @property
    def statssa_path(self) -> Path:
        path = Path(self.STATSSA_DOWNLOAD_PATH).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def che_path(self) -> Path:
        path = Path(self.CHE_DOWNLOAD_PATH).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def curriculum_upload_path(self) -> Path:
        path = Path(self.CURRICULUM_UPLOAD_PATH).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def dhet_ofo_evidence_path(self) -> Path:
        path = Path(self.DHET_OFO_EVIDENCE_PATH).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def esco_bundle_evidence_path(self) -> Path:
        path = Path(self.ESCO_BUNDLE_EVIDENCE_PATH).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


    # =====================================================
    # ML / Predictive Module
    # =====================================================

    ENABLE_PREDICTIVE_MODULE: bool = True

    FEATURE_ENABLE_SHAP: bool = True

    MODEL_STORAGE_PATH: str = "./models"

    MODEL_VERSION: str = "latest"

    ENABLE_MODEL_HOT_RELOAD: bool = False

    TFIDF_MAX_FEATURES: int = 256

    DEFAULT_FORECAST_HORIZON: int = 12

    MAX_JOB_POSTINGS_ANALYSIS: int = 1000

    # =====================================================
    # XGBoost
    # =====================================================

    XGBOOST_MAX_DEPTH: int = 6

    XGBOOST_LEARNING_RATE: float = 0.1

    XGBOOST_N_ESTIMATORS: int = 100

    # =====================================================
    # LSTM
    # =====================================================

    LSTM_SEQUENCE_LENGTH: int = 12

    LSTM_UNITS_1: int = 128

    LSTM_UNITS_2: int = 64

    LSTM_DROPOUT: float = 0.2

    LSTM_EPOCHS: int = 50

    LSTM_BATCH_SIZE: int = 32

    # =====================================================
    # Feature Flags
    # =====================================================

    ENABLE_SHAP_EXPLAINABILITY: bool = True

    ENABLE_FAIRNESS_AUDIT: bool = True

    ENABLE_AUDIT_LOGGING: bool = True

    ENABLE_OFO_TAXONOMY: bool = True

    # =====================================================
    # OIDC / SSO
    # =====================================================

    OIDC_ENABLED: bool = False

    OIDC_CLIENT_ID: Optional[str] = None

    OIDC_CLIENT_SECRET: Optional[str] = None

    OIDC_AUTHORITY: str = (
        "https://login.microsoftonline.com"
    )

    LOCAL_AUTH_FALLBACK: bool = True

    # =====================================================
    # Deployment
    # =====================================================

    RUN_MIGRATIONS_ON_STARTUP: bool = False

    FAIL_ON_MIGRATION_ERROR: bool = False

    REQUIRE_HTTPS: bool = False

    TRUST_PROXY_HEADERS: bool = False

    # =====================================================
    # Bootstrap Admin
    # =====================================================

    ENABLE_BOOTSTRAP_ADMIN: bool = True

    BOOTSTRAP_ADMIN_USERNAME: str = "admin"

    BOOTSTRAP_ADMIN_EMAIL: str = (
        "admin@future.local"
    )

    BOOTSTRAP_ADMIN_PASSWORD: Optional[str] = None

    # =====================================================
    # Validators
    # =====================================================

    @field_validator(
        "CORS_ALLOW_METHODS",
        "CORS_ALLOW_HEADERS",
        "CORS_EXPOSE_HEADERS",
        "CORS_ORIGINS",
        mode="before",
    )
    @classmethod
    def parse_comma_separated_strings(
        cls,
        value,
    ):
        """
        Support both:
        - JSON arrays
        - comma-separated strings
        """

        if isinstance(value, str):

            value = value.strip()

            # JSON-style list
            if value.startswith("["):
                import json
                return json.loads(value)

            # CSV-style list
            return [
                v.strip()
                for v in value.split(",")
                if v.strip()
            ]

        return value

    # =====================================================
    # Helper Properties
    # =====================================================

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in [
            "production",
            "prod",
        ]

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() in [
            "development",
            "dev",
        ]

    
# =========================================================
# Singleton Settings Instance
# =========================================================

settings = Settings()


def get_settings() -> Settings:
    return settings


# =========================================================
# Model Path Helper
# =========================================================


def get_model_path(
    model_name: str,
    version: Optional[str] = None,
) -> Path:

    version = (
        version or settings.MODEL_VERSION
    )

    return (
        Path(settings.MODEL_STORAGE_PATH)
        / model_name
        / version
    )
