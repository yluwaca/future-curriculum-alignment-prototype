# backend/app/services/etl_pipeline.py

"""
Enterprise ETL Pipeline Service for FUTURE Platform.

Responsibilities:
- curriculum ingestion
- labour market ingestion
- text normalization
- skill extraction
- ETL orchestration
- demand aggregation
- preprocessing support
- forecasting preparation

Aligned with:
- PostgreSQL schema
- SQLAlchemy 2.0
- Predictive schemas
- ML pipelines
"""

from __future__ import annotations

import logging
import re

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np
import pandas as pd

from sklearn.impute import KNNImputer

from sqlalchemy.orm import Session

from app.models.curriculum_module import (
    CurriculumModule,
)
from app.models.job_posting import (
    JobPosting,
)

from app.schemas.predictive import (
    CurriculumModuleCreate,
    JobPostingCreate,
)

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)

# =========================================================
# ETL Pipeline
# =========================================================


class ETLPipeline:
    """
    Enterprise ETL pipeline.

    Handles:
    - ingestion
    - cleaning
    - harmonization
    - aggregation
    - preprocessing
    """

    # -----------------------------------------------------
    # ESCO / O*NET Simplified Skill Taxonomy
    # -----------------------------------------------------

    ESCO_SKILLS_MAPPING = {
        "python": ["python", "py"],
        "java": ["java", "jvm"],
        "javascript": ["javascript", "js", "node"],
        "typescript": ["typescript", "ts"],
        "go": ["golang", "go language", "go programming"],
        "rust": ["rust", "rust-lang"],
        "c++": ["c++", "cpp", "c plus plus"],
        "c#": ["c#", "c sharp", "dotnet", ".net"],
        "ruby": ["ruby", "ruby on rails"],
        "php": ["php", "php programming"],
        "swift": ["swift", "ios"],
        "kotlin": ["kotlin", "kotlin android"],
        "scala": ["scala", "scala programming"],
        "r": ["r programming", "r statistics", "r language"],
        "sql": ["sql", "postgres", "postgresql", "mysql", "database", "rdbms"],
        "react": ["react", "reactjs", "react.js", "jsx"],
        "angular": ["angular", "angularjs"],
        "vue": ["vue.js", "vuejs", "vue"],
        "django": ["django", "django framework"],
        "flask": ["flask", "flask framework"],
        "spring boot": ["spring boot", "spring framework", "spring"],
        "node.js": ["node.js", "nodejs", "node"],
        "machine learning": ["machine learning", "ml", "deep learning", "neural network", "tensorflow", "pytorch"],
        "data analysis": ["analytics", "data analysis", "business intelligence", "power bi", "tableau"],
        "natural language processing": ["nlp", "natural language processing", "text analytics"],
        "computer vision": ["computer vision", "image recognition", "object detection"],
        "deep learning": ["deep learning", "dnn", "deep neural network"],
        "generative ai": ["generative ai", "gen ai", "generative artificial intelligence"],
        "large language models": ["llm", "large language model", "large language models"],
        "reinforcement learning": ["reinforcement learning", "rl"],
        "web development": ["frontend", "backend", "full stack", "web development"],
        "cloud computing": ["aws", "azure", "gcp", "cloud", "amazon web services", "google cloud platform", "microsoft azure"],
        "devops": ["docker", "kubernetes", "devops", "ci/cd", "jenkins", "github actions"],
        "api development": ["api", "rest", "graphql", "restful"],
        "data engineering": ["data engineering", "data pipeline", "etl", "elt"],
        "apache spark": ["spark", "pyspark", "apache spark"],
        "apache kafka": ["kafka", "apache kafka", "event streaming"],
        "data warehousing": ["data warehouse", "data warehousing", "data lake", "delta lake"],
        "terraform": ["terraform", "iac", "infrastructure as code"],
        "docker": ["docker", "containerisation", "docker compose"],
        "kubernetes": ["kubernetes", "k8s", "kube"],
        "project management": ["project management", "scrum", "agile", "kanban", "sprint"],
        "communication": ["communication", "presentation", "report writing", "stakeholder"],
        "cybersecurity": ["cybersecurity", "information security", "network security", "infosec"],
        "data governance": ["data governance", "data stewardship", "data quality"],
        "data privacy": ["data privacy", "gdpr", "data protection"],
        "risk management": ["risk management", "risk assessment", "compliance"],
        "leadership": ["leadership", "team leadership", "people management"],
        "strategic planning": ["strategic planning", "strategy", "organisational strategy"],
        "critical thinking": ["critical thinking", "analytical thinking", "problem solving"],
        "creativity": ["creativity", "innovation", "creative thinking"],
        "negotiation": ["negotiation", "conflict resolution", "mediation"],
        "ux design": ["ux", "user experience", "ux design", "ui design", "user interface"],
        "product management": ["product management", "product owner", "product strategy"],
        "data storytelling": ["data storytelling", "data visualisation", "data visualization", "dashboard"],
        "time series analysis": ["time series", "forecasting", "arima", "prophet"],
        "knowledge graphs": ["knowledge graph", "neo4j", "graph database", "semantic graph"],
        "recommendation systems": ["recommendation system", "recommender system", "collaborative filtering"],
        "anomaly detection": ["anomaly detection", "outlier detection", "fraud detection"],
        "econometrics": ["econometrics", "econometric modelling"],
        "financial analysis": ["financial analysis", "financial modelling", "financial forecasting"],
    }

    # =====================================================
    # Initialization
    # =====================================================

    def __init__(self) -> None:

        logger.info(
            "[ETL] Pipeline initialized"
        )

    # =====================================================
    # Curriculum Ingestion
    # =====================================================

    def ingest_curriculum(
        self,
        db: Session,
        curriculum_data: List[
            CurriculumModuleCreate
        ],
        force_reprocess: bool = False,
    ) -> Tuple[int, List[str]]:
        """
        Ingest curriculum modules.
        """

        count_ingested = 0

        errors: List[str] = []

        logger.info(
            "[ETL] Starting curriculum ingestion "
            "(records=%s)",
            len(curriculum_data),
        )

        for record in curriculum_data:

            try:

                existing = (
                    db.query(
                        CurriculumModule
                    )
                    .filter(
                        CurriculumModule.module_code
                        == record.module_code
                    )
                    .first()
                )

                # -----------------------------------------
                # Skip Existing
                # -----------------------------------------

                if (
                    existing
                    and not force_reprocess
                ):

                    logger.debug(
                        "[ETL] Skipping existing "
                        "curriculum module: %s",
                        record.module_code,
                    )

                    continue

                # -----------------------------------------
                # Update Existing
                # -----------------------------------------

                if existing:

                    existing.module_name = (
                        record.module_name
                    )

                    existing.description = (
                        record.description
                    )

                    existing.nqf_level = (
                        record.nqf_level
                    )

                    existing.faculty = (
                        record.faculty
                    )

                    existing.programme = (
                        record.programme
                    )

                    existing.credits = (
                        record.credits
                    )

                    existing.data_source = (
                        record.data_source
                    )

                    existing.is_active = (
                        record.is_active
                    )

                    existing.last_processed_at = (
                        datetime.now(timezone.utc)
                    )

                    db.add(existing)

                # -----------------------------------------
                # Create New
                # -----------------------------------------

                else:

                    new_module = (
                        CurriculumModule(
                            module_code=record.module_code,
                            module_name=record.module_name,
                            description=record.description,
                            nqf_level=record.nqf_level,
                            faculty=record.faculty,
                            programme=record.programme,
                            credits=record.credits,
                            data_source=record.data_source,
                            is_active=record.is_active,
                            last_processed_at=datetime.now(timezone.utc),
                        )
                    )

                    db.add(new_module)

                count_ingested += 1

            except Exception as exc:

                logger.exception(
                    "[ETL] Curriculum ingestion failed "
                    "for module=%s",
                    record.module_code,
                )

                errors.append(
                    f"{record.module_code}: {str(exc)}"
                )

        # -------------------------------------------------
        # Commit
        # -------------------------------------------------

        try:

            db.commit()

            logger.info(
                "[ETL] Curriculum ingestion complete "
                "(ingested=%s)",
                count_ingested,
            )

        except Exception as exc:

            db.rollback()

            logger.exception(
                "[ETL] Curriculum transaction failed"
            )

            errors.append(str(exc))

        return count_ingested, errors

    # =====================================================
    # Job Posting Ingestion
    # =====================================================

    def ingest_job_postings(
        self,
        db: Session,
        job_data: List[
            JobPostingCreate
        ],
        force_reprocess: bool = False,
    ) -> Tuple[int, List[str]]:
        """
        Ingest labour market job postings.
        """

        count_ingested = 0

        errors: List[str] = []

        logger.info(
            "[ETL] Starting job ingestion "
            "(records=%s)",
            len(job_data),
        )

        for record in job_data:

            try:

                existing = (
                    db.query(JobPosting)
                    .filter(
                        JobPosting.job_id
                        == record.job_id
                    )
                    .first()
                )

                # -----------------------------------------
                # Skip Existing
                # -----------------------------------------

                if (
                    existing
                    and not force_reprocess
                ):

                    logger.debug(
                        "[ETL] Skipping existing "
                        "job posting: %s",
                        record.job_id,
                    )

                    continue

                # -----------------------------------------
                # Derived Temporal Features
                # -----------------------------------------

                posted_date = (
                    record.posted_date
                )

                posting_year = (
                    posted_date.year
                )

                posting_month = (
                    posted_date.month
                )

                posting_quarter = (
                    (posting_month - 1) // 3
                ) + 1

                # -----------------------------------------
                # Extract Skills Automatically
                # -----------------------------------------

                extracted_skills = (
                    self.extract_skills(
                        (
                            record.job_description
                            or ""
                        )
                    )
                )

                merged_skills = list(
                    set(
                        (
                            record.required_skills
                            or []
                        )
                        + extracted_skills
                    )
                )

                # -----------------------------------------
                # Update Existing
                # -----------------------------------------

                if existing:

                    existing.job_title = (
                        record.job_title
                    )

                    existing.job_description = (
                        record.job_description
                    )

                    existing.required_skills = (
                        merged_skills
                    )

                    existing.education_level = (
                        record.education_level
                    )

                    existing.experience_years = (
                        record.experience_years
                    )

                    existing.region = (
                        record.region
                    )

                    existing.country = (
                        record.country
                    )

                    existing.employment_type = (
                        record.employment_type
                    )

                    existing.salary_min = (
                        record.salary_min
                    )

                    existing.salary_max = (
                        record.salary_max
                    )

                    existing.posted_date = (
                        record.posted_date
                    )

                    existing.closed_date = (
                        record.closed_date
                    )

                    existing.posting_year = (
                        posting_year
                    )

                    existing.posting_month = (
                        posting_month
                    )

                    existing.posting_quarter = (
                        posting_quarter
                    )

                    existing.source = (
                        record.source
                    )

                    existing.source_url = (
                        record.source_url
                    )

                    existing.last_processed_at = (
                        datetime.now(timezone.utc)
                    )

                    db.add(existing)

                # -----------------------------------------
                # Create New
                # -----------------------------------------

                else:

                    new_job = JobPosting(
                        job_id=record.job_id,
                        job_title=record.job_title,
                        job_description=record.job_description,
                        required_skills=merged_skills,
                        education_level=record.education_level,
                        experience_years=record.experience_years,
                        region=record.region,
                        country=record.country,
                        employment_type=record.employment_type,
                        salary_min=record.salary_min,
                        salary_max=record.salary_max,
                        posted_date=record.posted_date,
                        closed_date=record.closed_date,
                        posting_year=posting_year,
                        posting_month=posting_month,
                        posting_quarter=posting_quarter,
                        source=record.source,
                        source_url=record.source_url,
                        is_processed=False,
                        embedding_generated=False,
                        last_processed_at=datetime.now(timezone.utc),
                    )

                    db.add(new_job)

                count_ingested += 1

            except Exception as exc:

                logger.exception(
                    "[ETL] Job ingestion failed "
                    "for job_id=%s",
                    record.job_id,
                )

                errors.append(
                    f"{record.job_id}: {str(exc)}"
                )

        # -------------------------------------------------
        # Commit
        # -------------------------------------------------

        try:

            db.commit()

            logger.info(
                "[ETL] Job ingestion complete "
                "(ingested=%s)",
                count_ingested,
            )

        except Exception as exc:

            db.rollback()

            logger.exception(
                "[ETL] Job ingestion transaction failed"
            )

            errors.append(str(exc))

        return count_ingested, errors

    # =====================================================
    # Text Cleaning
    # =====================================================

    @staticmethod
    def clean_text(
        text: Optional[str],
    ) -> str:
        """
        Normalize text.
        """

        if not text:
            return ""

        text = text.lower()

        text = re.sub(
            r"[^a-z0-9\s]",
            " ",
            text,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        return text

    # =====================================================
    # Skill Extraction
    # =====================================================

    @classmethod
    def extract_skills(
        cls,
        text: Optional[str],
    ) -> List[str]:
        """
        Extract skill entities from text.
        """

        if not text:
            return []

        cleaned_text = (
            cls.clean_text(text)
        )

        identified_skills = []

        for (
            canonical_skill,
            keywords,
        ) in (
            cls.ESCO_SKILLS_MAPPING.items()
        ):

            for keyword in keywords:

                if keyword in cleaned_text:

                    identified_skills.append(
                        canonical_skill
                    )

                    break

        return sorted(
            list(set(identified_skills))
        )

    # =====================================================
    # Missing Value Handling
    # =====================================================

    @staticmethod
    def handle_missing_values(
        df: pd.DataFrame,
        strategy: str = "mean",
        threshold: float = 0.05,
    ) -> pd.DataFrame:
        """
        Handle missing values.
        """

        if df.empty:
            return df

        missing_pct = (
            df.isnull().sum() / len(df)
        )

        cols_to_drop = (
            missing_pct[
                missing_pct > threshold
            ]
            .index
            .tolist()
        )

        if cols_to_drop:

            logger.info(
                "[ETL] Dropping sparse columns: %s",
                cols_to_drop,
            )

            df = df.drop(
                columns=cols_to_drop
            )

        numeric_cols = (
            df.select_dtypes(
                include=[np.number]
            ).columns
        )

        if strategy == "knn":

            imputer = KNNImputer(
                n_neighbors=5,
                weights="distance",
            )
            df[numeric_cols] = imputer.fit_transform(
                df[numeric_cols]
            )

        elif strategy == "mean":

            df[numeric_cols] = (
                df[numeric_cols]
                .fillna(
                    df[numeric_cols].mean()
                )
            )

        elif strategy == "drop":

            df = df.dropna()

        logger.info(
            "[ETL] Missing values handled "
            "(strategy=%s)",
            strategy,
        )

        return df

    @classmethod
    def winsorise_features(
        cls,
        df: pd.DataFrame,
        percentile: float = 95.0,
    ) -> pd.DataFrame:
        """
        Winsorise numeric features at the given percentile
        (paper: 95th-percentile winsorisation).
        """
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        upper = np.percentile(df[numeric_cols].dropna(), percentile)
        lower = np.percentile(df[numeric_cols].dropna(), 100.0 - percentile)
        df_out = df.copy()
        for col in numeric_cols:
            df_out[col] = df_out[col].clip(lower=lower, upper=upper)
        logger.info(
            "[ETL] Winsorised %d columns at %.1f%% "
            "(lower=%.4f, upper=%.4f)",
            len(numeric_cols), percentile, lower, upper,
        )
        return df_out

    # =====================================================
    # Demand Aggregation
    # =====================================================

    @classmethod
    def aggregate_demand_time_series(
        cls,
        db: Session,
        region: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Aggregate demand signals for forecasting.
        """

        query = (
            db.query(JobPosting)
            .filter(
                JobPosting.is_processed.is_(
                    False
                )
            )
        )

        if region:

            query = query.filter(
                JobPosting.region == region
            )

        postings = query.all()

        if not postings:

            logger.warning(
                "[ETL] No job postings found "
                "for aggregation"
            )

            return pd.DataFrame()

        rows = []

        for posting in postings:

            extracted_skills = (
                posting.required_skills
                or cls.extract_skills(
                    posting.job_description
                )
            )

            rows.append(
                {
                    "date": posting.posted_date,
                    "region": posting.region,
                    "job_id": posting.job_id,
                    "skills": extracted_skills,
                }
            )

        df = pd.DataFrame(rows)

        if df.empty:
            return pd.DataFrame()

        df["year_month"] = (
            df["date"]
            .dt
            .to_period("M")
        )

        aggregated = (
            df.groupby(
                ["year_month", "region"]
            )
            .agg(
                demand_count=(
                    "job_id",
                    "count",
                ),
                all_skills=(
                    "skills",
                    lambda x: [
                        skill
                        for skill_list in x
                        for skill in skill_list
                    ],
                ),
            )
            .reset_index()
        )

        aggregated[
            "skill_frequency"
        ] = aggregated[
            "all_skills"
        ].apply(
            lambda x: dict(
                Counter(x)
            )
        )

        logger.info(
            "[ETL] Demand aggregation complete "
            "(groups=%s)",
            len(aggregated),
        )

        return aggregated

    # =====================================================
    # Full ETL Orchestration
    # =====================================================

    def process_etl_pipeline(
        self,
        db: Session,
        curriculum_data: Optional[
            List[
                CurriculumModuleCreate
            ]
        ] = None,
        job_data: Optional[
            List[
                JobPostingCreate
            ]
        ] = None,
        force_reprocess: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute complete ETL pipeline.
        """

        logger.info(
            "[ETL] Starting pipeline execution"
        )

        summary: Dict[str, Any] = {
            "curriculum_ingested": 0,
            "job_postings_ingested": 0,
            "demand_aggregation_success": False,
            "errors": [],
            "timestamp": datetime.now(timezone.utc),
        }

        # -------------------------------------------------
        # Curriculum
        # -------------------------------------------------

        if curriculum_data:

            count, errors = (
                self.ingest_curriculum(
                    db=db,
                    curriculum_data=curriculum_data,
                    force_reprocess=force_reprocess,
                )
            )

            summary[
                "curriculum_ingested"
            ] = count

            summary["errors"].extend(
                errors
            )

        # -------------------------------------------------
        # Job Postings
        # -------------------------------------------------

        if job_data:

            count, errors = (
                self.ingest_job_postings(
                    db=db,
                    job_data=job_data,
                    force_reprocess=force_reprocess,
                )
            )

            summary[
                "job_postings_ingested"
            ] = count

            summary["errors"].extend(
                errors
            )

        # -------------------------------------------------
        # Aggregation
        # -------------------------------------------------

        try:

            aggregated = (
                self.aggregate_demand_time_series(
                    db=db
                )
            )

            summary[
                "demand_aggregation_success"
            ] = not aggregated.empty

        except Exception as exc:

            logger.exception(
                "[ETL] Demand aggregation failed"
            )

            summary["errors"].append(
                str(exc)
            )

        logger.info(
            "[ETL] Pipeline execution completed"
        )

        return summary