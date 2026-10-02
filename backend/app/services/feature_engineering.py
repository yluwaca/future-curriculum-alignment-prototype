# backend/app/services/feature_engineering.py

"""
Enterprise Feature Engineering Service for FUTURE Platform.

Responsibilities:
- TF-IDF vectorization
- feature generation
- curriculum-demand alignment
- gap scoring
- SHAP-safe feature ordering
- LSTM sequence generation
- feature hashing
- metadata lineage

Aligned with:
- PostgreSQL schema
- SQLAlchemy 2.0
- XGBoost pipelines
- LSTM forecasting
- SHAP explainability
"""

from __future__ import annotations

import hashlib
import json
import logging

from datetime import datetime, timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np
import pandas as pd

from sklearn.feature_extraction.text import (
    TfidfVectorizer,
)
from sklearn.metrics.pairwise import (
    cosine_similarity,
)
from sklearn.preprocessing import (
    StandardScaler,
)
from sklearn.linear_model import (
    LinearRegression,
)

from sqlalchemy.orm import Session

from app.models.curriculum_module import (
    CurriculumModule,
)
from app.models.job_posting import (
    JobPosting,
)

from app.services.etl_pipeline import (
    ETLPipeline,
)
from app.services.semantic_vector_service import (
    compute_embedding,
)

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)

# =========================================================
# Feature Engineering Service
# =========================================================


class FeatureEngineer:
    """
    Enterprise feature engineering service.

    Supports:
    - XGBoost feature generation
    - forecasting sequences
    - SHAP explainability
    - curriculum-demand analysis
    """

    # =====================================================
    # Initialization
    # =====================================================

    def __init__(
        self,
        tfidf_max_features: int = 256,
    ) -> None:
        """
        Initialize feature engineering service.
        """

        self.tfidf_max_features = (
            tfidf_max_features
        )

        self.tfidf_vectorizer: Optional[
            TfidfVectorizer
        ] = None

        self.scaler: Optional[
            StandardScaler
        ] = None

        self.feature_names: List[str] = []

        logger.info(
            "[FE] Feature engineering service initialized"
        )

    # =====================================================
    # TF-IDF Fitting
    # =====================================================

    def fit_tfidf(
        self,
        texts: List[str],
    ) -> TfidfVectorizer:
        """
        Fit TF-IDF vectorizer.
        """

        if not texts:

            raise ValueError(
                "Cannot fit TF-IDF on empty corpus."
            )

        self.tfidf_vectorizer = (
            TfidfVectorizer(
                max_features=self.tfidf_max_features,
                stop_words="english",
                lowercase=True,
                min_df=1,
                max_df=0.95,
            )
        )

        self.tfidf_vectorizer.fit(texts)

        self.feature_names = sorted(
            self.tfidf_vectorizer
            .get_feature_names_out()
            .tolist()
        )

        logger.info(
            "[FE] TF-IDF fitted "
            "(features=%s)",
            len(self.feature_names),
        )

        return self.tfidf_vectorizer

    # =====================================================
    # TF-IDF Transformation
    # =====================================================

    def transform_tfidf(
        self,
        texts: List[str],
    ) -> np.ndarray:
        """
        Transform text using fitted TF-IDF.
        """

        if self.tfidf_vectorizer is None:

            raise ValueError(
                "TF-IDF vectorizer is not fitted."
            )

        matrix = (
            self.tfidf_vectorizer
            .transform(texts)
            .toarray()
        )

        return matrix

    # =====================================================
    # Gap Score
    # =====================================================

    @staticmethod
    def calculate_gap_score(
        curriculum_embedding: np.ndarray,
        demand_embedding: np.ndarray,
    ) -> float:
        """
        Calculate curriculum-demand gap score.
        """

        if curriculum_embedding.ndim == 1:

            curriculum_embedding = (
                curriculum_embedding.reshape(1, -1)
            )

        if demand_embedding.ndim == 1:

            demand_embedding = (
                demand_embedding.reshape(1, -1)
            )

        similarity = cosine_similarity(
            curriculum_embedding,
            demand_embedding,
        )[0, 0]

        gap_score = (
            1.0 - similarity
        )

        return float(
            max(
                0.0,
                min(1.0, gap_score),
            )
        )

    # =====================================================
    # Feature Hashing
    # =====================================================

    @staticmethod
    def generate_feature_hash(
        features: Dict[str, Any],
    ) -> str:
        """
        Generate deterministic SHA-256 feature hash.
        """

        serialized = json.dumps(
            features,
            sort_keys=True,
            default=str,
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

    # =====================================================
    # Context Features
    # =====================================================

    @staticmethod
    def build_context_features(
        curriculum: CurriculumModule,
    ) -> Dict[str, float]:
        """
        Build contextual curriculum features.
        """

        features: Dict[str, float] = {}

        # -------------------------------------------------
        # NQF Level
        # -------------------------------------------------

        nqf_level = (
            curriculum.nqf_level or 0
        )

        features[
            "nqf_level_normalized"
        ] = nqf_level / 10.0

        # -------------------------------------------------
        # Credits
        # -------------------------------------------------

        credits = (
            curriculum.credits or 0
        )

        features[
            "credits_normalized"
        ] = credits / 100.0

        # -------------------------------------------------
        # Active Flag
        # -------------------------------------------------

        features[
            "is_active"
        ] = (
            1.0
            if curriculum.is_active
            else 0.0
        )

        return features

    # =====================================================
    # XGBoost Feature Generation
    # =====================================================

    def create_xgboost_features(
        self,
        db: Session,
        curriculum: CurriculumModule,
        region: Optional[str] = None,
        batch_mode: bool = False,
    ) -> Tuple[
        Dict[str, float],
        Dict[str, Any],
    ]:
        """
        Generate stable XGBoost feature vector.
        """

        logger.info(
            "[FE] Generating XGBoost features "
            "for module=%s",
            curriculum.module_code,
        )

        features: Dict[str, float] = {}

        metadata: Dict[str, Any] = {}

        # -------------------------------------------------
        # Curriculum Text
        # -------------------------------------------------

        curriculum_text = " ".join(
            filter(
                None,
                [
                    curriculum.module_name,
                    curriculum.description,
                    curriculum.faculty,
                    curriculum.programme,
                ],
            )
        )

        cleaned_curriculum_text = (
            ETLPipeline.clean_text(
                curriculum_text
            )
        )

        # -------------------------------------------------
        # Job Postings
        # -------------------------------------------------

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

        job_postings = (
            query
            .order_by(
                JobPosting.posted_date.desc()
            )
            .limit(1000)
            .all()
        )

        job_texts = [
            ETLPipeline.clean_text(
                jp.job_description
                or jp.job_title
            )
            for jp in job_postings
        ]

        if not job_texts:

            logger.warning(
                "[FE] No job postings found "
                "for module=%s",
                curriculum.module_code,
            )

            job_texts = [
                cleaned_curriculum_text
            ]

        # -------------------------------------------------
        # Fit TF-IDF Once
        # -------------------------------------------------

        if self.tfidf_vectorizer is None:

            self.fit_tfidf(
                job_texts
                + [cleaned_curriculum_text]
            )

        # -------------------------------------------------
        # Vectorization
        # -------------------------------------------------

        curriculum_vector = (
            self.transform_tfidf(
                [cleaned_curriculum_text]
            )[0]
        )

        demand_vectors = (
            self.transform_tfidf(
                job_texts[:100]
            )
        )

        demand_vector = np.mean(
            demand_vectors,
            axis=0,
        )

        # -------------------------------------------------
        # Stable Feature Ordering
        # -------------------------------------------------

        for idx, feature_name in enumerate(
            self.feature_names
        ):

            if idx >= len(curriculum_vector):
                break

            features[
                f"tfidf_{feature_name}"
            ] = float(
                curriculum_vector[idx]
            )

        # -------------------------------------------------
        # Gap Score
        # -------------------------------------------------

        gap_score = (
            self.calculate_gap_score(
                curriculum_vector,
                demand_vector,
            )
        )

        features[
            "gap_score"
        ] = gap_score

        metadata[
            "gap_score"
        ] = gap_score

        # -------------------------------------------------
        # Semantic Gap Score (sentence-transformer)
        # Skip in batch mode — too slow for 600+ curricula
        # -------------------------------------------------

        if not batch_mode:
            try:
                curriculum_embedding = compute_embedding(
                    cleaned_curriculum_text,
                )
                if curriculum_embedding and job_texts:
                    job_embeddings = [
                        emb
                        for t in job_texts[:50]
                        if (emb := compute_embedding(t)) is not None
                    ]
                    if job_embeddings:
                        mean_job_embedding = [
                            sum(vals) / len(job_embeddings)
                            for vals in zip(*job_embeddings)
                        ]
                        semantic_gap = gap_score
                        if len(curriculum_embedding) == len(mean_job_embedding):
                            dot = sum(a * b for a, b in zip(curriculum_embedding, mean_job_embedding))
                            semantic_similarity = max(-1.0, min(1.0, dot))
                            semantic_gap = 1.0 - semantic_similarity
                            semantic_gap = max(0.0, min(1.0, semantic_gap))
                        features["semantic_gap_score"] = semantic_gap
                        metadata["semantic_gap_score"] = semantic_gap
            except Exception:
                logger.warning(
                    "[FE] Semantic gap score failed",
                    exc_info=True,
                )

        # -------------------------------------------------
        # Skills
        # -------------------------------------------------

        identified_skills = (
            ETLPipeline.extract_skills(
                curriculum.description
            )
        )

        for skill in identified_skills:

            features[
                f"skill_{skill}"
            ] = 1.0

        # -------------------------------------------------
        # Context Features
        # -------------------------------------------------

        context_features = (
            self.build_context_features(
                curriculum
            )
        )

        features.update(
            context_features
        )

        # -------------------------------------------------
        # Skill Demand Frequencies
        # -------------------------------------------------

        skill_frequency: Dict[
            str,
            int,
        ] = {}

        for job in job_postings:

            job_skills = (
                job.required_skills
                or ETLPipeline.extract_skills(
                    job.job_description
                )
            )

            for skill in job_skills:

                skill_frequency[
                    skill
                ] = (
                    skill_frequency.get(
                        skill,
                        0,
                    )
                    + 1
                )

        total_jobs = max(
            len(job_postings),
            1,
        )

        for skill, count in (
            skill_frequency.items()
        ):

            features[
                f"demand_freq_{skill}"
            ] = (
                count / total_jobs
            )

        # -------------------------------------------------
        # Metadata
        # -------------------------------------------------

        metadata[
            "identified_skills"
        ] = identified_skills

        metadata[
            "num_job_postings_analyzed"
        ] = len(job_postings)

        metadata[
            "feature_count"
        ] = len(features)

        metadata[
            "feature_hash"
        ] = (
            self.generate_feature_hash(
                features
            )
        )

        metadata[
            "generated_at"
        ] = datetime.now(timezone.utc)

        metadata[
            "skill_demand_ranking"
        ] = [
            {
                "skill": skill,
                "demand_count": count,
                "demand_share": count / total_jobs,
            }
            for skill, count in sorted(
                skill_frequency.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]
        ]

        logger.info(
            "[FE] Generated XGBoost feature vector "
            "(features=%s)",
            len(features),
        )

        return features, metadata

    # =====================================================
    # LSTM Sequence Generation
    # =====================================================

    def create_lstm_sequence_features(
        self,
        db: Session,
        curriculum: CurriculumModule,
        sequence_length: int = 12,
        region: Optional[str] = None,
    ) -> Tuple[
        np.ndarray,
        Dict[str, Any],
    ]:
        """
        Generate LSTM forecasting sequences.
        """

        logger.info(
            "[FE] Building LSTM sequences "
            "for module=%s",
            curriculum.module_code,
        )

        identified_skills = (
            ETLPipeline.extract_skills(
                curriculum.description
            )
        )

        if not identified_skills:

            identified_skills = [
                "generic"
            ]

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

        job_postings = (
            query
            .order_by(
                JobPosting.posted_date.desc()
            )
            .limit(1000)
            .all()
        )

        monthly_demands: Dict[
            str,
            int,
        ] = {}

        # Normalize identified skills for matching (ETL uses spaces, some data uses underscores)
        identified_skills_normalized = {s.replace("_", " ").lower() for s in identified_skills}

        for posting in job_postings:

            posting_skills = (
                posting.required_skills
                or ETLPipeline.extract_skills(
                    posting.job_description
                )
            )

            posting_skills_normalized = {s.replace("_", " ").lower() for s in posting_skills}

            if posting_skills_normalized & identified_skills_normalized:

                month_key = (
                    posting.posted_date.strftime(
                        "%Y-%m"
                    )
                )

                monthly_demands[
                    month_key
                ] = (
                    monthly_demands.get(
                        month_key,
                        0,
                    )
                    + 1
                )

        # -------------------------------------------------
        # Build Stable Sequence
        # -------------------------------------------------

        sequence: List[float] = []

        current_date = datetime.now(timezone.utc)

        for offset in range(
            sequence_length - 1,
            -1,
            -1,
        ):

            target_date = (
                pd.Timestamp(
                    current_date
                )
                - pd.DateOffset(
                    months=offset
                )
            )

            month_key = (
                target_date.strftime(
                    "%Y-%m"
                )
            )

            demand_count = (
                monthly_demands.get(
                    month_key,
                    0,
                )
            )

            sequence.append(
                float(demand_count)
            )

        sequence_array = np.array(
            sequence,
            dtype=np.float32,
        ).reshape(-1, 1)

        # -------------------------------------------------
        # Normalize
        # -------------------------------------------------

        max_value = (
            sequence_array.max()
        )

        if max_value > 0:

            sequence_array = (
                sequence_array
                / max_value
            )

        metadata = {
            "sequence_length": sequence_length,
            "identified_skills": identified_skills,
            "region": region,
            "generated_at": datetime.now(timezone.utc),
            "feature_hash": hashlib.sha256(
                sequence_array.tobytes()
            ).hexdigest(),
        }

        logger.info(
            "[FE] LSTM sequence generated "
            "(length=%s)",
            sequence_length,
        )

        return sequence_array, metadata

    # =====================================================
    # Feature Scaling
    # =====================================================

    def scale_features(
        self,
        features_df: pd.DataFrame,
    ) -> Tuple[
        pd.DataFrame,
        StandardScaler,
    ]:
        """
        Scale numeric features.
        """

        if features_df.empty:

            raise ValueError(
                "Cannot scale empty DataFrame."
            )

        scaler = StandardScaler()

        numeric_columns = (
            features_df
            .select_dtypes(
                include=[np.number]
            )
            .columns
        )

        features_df[
            numeric_columns
        ] = scaler.fit_transform(
            features_df[
                numeric_columns
            ]
        )

        self.scaler = scaler

        logger.info(
            "[FE] Feature scaling completed "
            "(columns=%s)",
            len(numeric_columns),
        )

        return features_df, scaler

    @staticmethod
    def variance_inflation_factor(
        features_df: pd.DataFrame,
        threshold: float = 5.0,
    ) -> pd.DataFrame:
        """
        Remove features with VIF >= threshold (paper: VIF < 5).
        """
        df = features_df.select_dtypes(include=[np.number]).copy()
        df = df.fillna(0.0)
        kept_cols = []
        removed = []
        for col in df.columns:
            other_cols = [c for c in df.columns if c != col]
            if len(other_cols) < 1:
                kept_cols.append(col)
                continue
            try:
                X_other = df[other_cols].values
                y_col = df[col].values
                model = LinearRegression()
                model.fit(X_other, y_col)
                r2 = model.score(X_other, y_col)
                vif = 1.0 / (1.0 - r2) if r2 < 0.999 else float("inf")
            except Exception as exc:
                raise RuntimeError(f"VIF calculation failed for feature '{col}': {exc}") from exc
            if vif < threshold:
                kept_cols.append(col)
            else:
                removed.append((col, round(vif, 2)))
        if removed:
            logger.info(
                "[FE] Removed %d features with VIF >= %.1f: %s",
                len(removed), threshold,
                [r[0] for r in removed],
            )
        return features_df[kept_cols]
