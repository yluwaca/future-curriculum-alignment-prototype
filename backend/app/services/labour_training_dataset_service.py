"""Reproducible labour-workflow training dataset builder (deterministic).

Builds leakage-safe, versioned training rows from labour-market evidence
(job postings and their skill mappings), optional curriculum evidence, and
deterministic synthetic fixtures. Supports train / validation / held-out test
splits that are keyed by *source posting*, so a single posting can never leak
across splits, and masks reviewer decisions that belong to the held-out test
split so they are never present during training.

Target definition (binary, technical): ``mapping_approval`` --
``1`` when a posting-to-skill mapping was reviewed and approved,
``0`` otherwise (candidate, needs_review, or explicitly rejected).

The module depends only on the standard library and SQLAlchemy (the database
loader is optional). Every operation is deterministic: the same rows, seed,
split scheme and feature schema produce exactly the same rows, splits, and
dataset version. Outputs from this module are **technical UAT evidence**; the
synthetic fixtures are used only to validate technical behaviour and are not
claims of empirical model validity.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

FEATURE_NAMES: List[str] = [
    "posting_len",
    "title_len",
    "skills_count",
    "matched_len",
    "desc_match",
    "token_overlap",
    "evidence_len",
    "confidence",
    "source_adzuna",
    "source_dpsa",
    "region_western_cape",
    "region_cape_town",
    "salary_mid_norm",
    "employment_full_time",
    "is_processed",
    "year_norm",
    "quarter_norm",
    "is_declared_job_skill",
]

MISSING_VALUE = -1.0

DEFAULT_SPLIT_RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}
SPLIT_ORDER = ("train", "validation", "test")

TARGET_DEFINITION: Dict[str, Any] = {
    "target": "mapping_approval",
    "label_encoding": {
        "approved": 1,
        "candidate_needs_review_rejected": 0,
    },
    "source_fields": ["mapping_status"],
    "note": (
        "Binary technical target for review-priority and demand-gap modelling. "
        "It measures technical mapping approval status, not an empirical "
        "labour-market or curriculum outcome."
    ),
}

FEATURE_SCHEMA_VERSION = "labour_row_features_v1"
DATASET_SCHEMA_VERSION = "labour_dataset_v1"


class TrainingDatasetError(Exception):
    """Raised when a training dataset cannot be built safely."""


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _tokens(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return re.findall(r"[a-z0-9+#.]+", text.lower())


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    aset = set(a)
    bset = set(b)
    if not aset or not bset:
        return 0.0
    return len(aset & bset) / len(aset | bset)


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def derive_features(row: Mapping[str, Any]) -> Dict[str, float]:
    """Derive the stable feature vector from a dataset row."""

    description = row.get("description") or ""
    title = row.get("title") or ""
    matched = row.get("matched_text") or ""
    evidence_len = _num(row.get("evidence_len"))

    posting_tokens = _tokens(f"{title} {description}")
    matched_tokens = _tokens(matched)

    salary_mid = _num(row.get("salary_mid"))
    year = _num(row.get("posting_year"))
    quarter = _num(row.get("posting_quarter"))
    confidence = _num(row.get("confidence"))

    source = str(row.get("source") or "").lower()
    region = str(row.get("region") or "").lower()
    employment = str(row.get("employment_type") or "").lower()

    values: Dict[str, float] = {
        "posting_len": _clip(min(len(description), 4000) / 4000.0),
        "title_len": _clip(min(len(title), 200) / 200.0),
        "skills_count": _clip(_num(row.get("skills_count")) or 0.0, 0.0, 1.0),
        "matched_len": _clip(min(len(matched), 120) / 120.0),
        "desc_match": 1.0 if (matched and matched.lower() in description.lower()) else 0.0,
        "token_overlap": _jaccard(matched_tokens, posting_tokens),
        "evidence_len": _clip((evidence_len or 0.0) / 600.0),
        "confidence": _clip(confidence if confidence is not None else 0.5),
        "source_adzuna": 1.0 if "adzuna" in source or "trial_not_empirical" in source else 0.0,
        "source_dpsa": 1.0 if source.startswith("dpsa") or "public service" in source else 0.0,
        "region_western_cape": 1.0 if ("western cape" in region or "cape town" in region) else 0.0,
        "region_cape_town": 1.0 if "cape town" in region else 0.0,
        "salary_mid_norm": _clip((salary_mid or 0.0) / 200000.0),
        "employment_full_time": 1.0 if employment.startswith("full") else 0.0,
        "is_processed": 1.0 if row.get("is_processed") else 0.0,
        "year_norm": _clip(((year or 2026.0) - 2000.0) / 40.0),
        "quarter_norm": _clip((quarter or 1.0) / 4.0),
        "is_declared_job_skill": 1.0 if row.get("extraction_method") == "declared_job_skill" else 0.0,
    }
    return {name: values[name] for name in FEATURE_NAMES}


def derive_label(row: Mapping[str, Any]) -> Optional[int]:
    status = row.get("mapping_status")
    if status is None:
        return None
    return 1 if str(status).lower() == "approved" else 0


def canonical_row_key(row: Mapping[str, Any]) -> str:
    return str(row["row_id"])


@dataclass
class TrainingDatasetRecord:
    version: str
    schema_version: str
    feature_names: List[str]
    target_definition: Dict[str, Any]
    scheme: str
    seed: int
    source_signature: str
    rows: List[Dict[str, Any]]
    splits: Dict[str, List[str]]
    class_distribution: Dict[str, Dict[str, int]]
    missing: Dict[str, int]
    deduplicated: int
    masked_test_labels: bool
    split_ratios: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SPLIT_RATIOS))

    def split_rows(self, split: str) -> List[Dict[str, Any]]:
        wanted = set(self.splits.get(split, []))
        return [row for row in self.rows if row["row_id"] in wanted]

    def labelled_split_rows(self, split: str) -> List[Dict[str, Any]]:
        return [row for row in self.split_rows(split) if derive_label(row) is not None]

    def to_manifest(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema_version": self.schema_version,
            "feature_names": list(self.feature_names),
            "target_definition": self.target_definition,
            "scheme": self.scheme,
            "seed": self.seed,
            "split_ratios": self.split_ratios,
            "source_signature": self.source_signature,
            "n_rows": len(self.rows),
            "row_ids": [row["row_id"] for row in self.rows],
            "splits": {name: len(ids) for name, ids in self.splits.items()},
            "class_distribution": self.class_distribution,
            "missing_fields": self.missing,
            "deduplicated_removed": self.deduplicated,
            "masked_test_labels": self.masked_test_labels,
        }


class LabourTrainingDatasetService:
    """Deterministic dataset builder for the labour-market workflow."""

    def __init__(
        self,
        seed: int = 42,
        scheme: str = "hash",
        mask_test_labels: bool = True,
        split_ratios: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.seed = int(seed)
        if scheme not in ("hash", "time"):
            raise TrainingDatasetError(f"unsupported split scheme: {scheme!r}")
        self.scheme = scheme
        self.mask_test_labels = bool(mask_test_labels)
        self.split_ratios = dict(split_ratios or DEFAULT_SPLIT_RATIOS)
        total = sum(self.split_ratios.values())
        if abs(total - 1.0) > 1e-6:
            raise TrainingDatasetError(
                f"split ratios must sum to 1.0, got {self.split_ratios} (sum={total})"
            )

    # ------------------------------------------------------------------
    # Row sources
    # ------------------------------------------------------------------

    def rows_from_db(self, db) -> List[Dict[str, Any]]:
        """Load dataset rows read-only from the labour evidence database."""
        from sqlalchemy.orm import Session

        from app.models.job_posting import JobPosting
        from app.models.skill import Skill
        from app.models.skill_mapping import SkillMapping

        if not isinstance(db, Session):
            raise TrainingDatasetError("rows_from_db requires a SQLAlchemy Session")

        postings = db.query(JobPosting).order_by(JobPosting.posting_id.asc()).all()
        posting_lookup = {str(posting.posting_id): posting for posting in postings}

        mapping_rows = (
            db.query(SkillMapping, Skill)
            .join(Skill, Skill.skill_id == SkillMapping.skill_id)
            .filter(SkillMapping.source_domain == "labour_market")
            .order_by(SkillMapping.created_at.asc(), SkillMapping.mapping_id.asc())
            .all()
        )

        rows: List[Dict[str, Any]] = []
        for mapping, skill in mapping_rows:
            posting = posting_lookup.get(str(mapping.source_entity_id))
            if posting is None:
                continue
            for prefix in ("required_skills", "skills"):
                skills_value = getattr(posting, prefix, None)
                if skills_value is not None:
                    break
            else:
                skills_value = None
            declared = []
            if isinstance(skills_value, dict):
                declared = skills_value.get("declared") or []
            if isinstance(declared, str):
                declared = re.split(r"[,;|]", declared)
            declared = [value for value in declared if value]
            salary_mid = None
            if posting.salary_min is not None or posting.salary_max is not None:
                salary_mid = float(posting.salary_min or 0) if posting.salary_max is None else (
                    (float(posting.salary_min or 0) + float(posting.salary_max or 0)) / 2.0
                )
            rows.append(
                {
                    "row_id": str(mapping.mapping_id),
                    "posting_id": str(posting.posting_id),
                    "job_id": posting.job_id,
                    "skill_id": str(skill.skill_id),
                    "skill_key": skill.skill_key,
                    "skill_name": skill.name,
                    "source": posting.source,
                    "region": posting.region,
                    "country": posting.country,
                    "employment_type": posting.employment_type,
                    "salary_mid": salary_mid,
                    "posting_year": posting.posting_year,
                    "posting_quarter": posting.posting_quarter,
                    "title": posting.job_title,
                    "description": posting.job_description or "",
                    "required_skills": declared,
                    "skills_count": len(declared),
                    "matched_text": mapping.matched_text,
                    "extraction_method": mapping.extraction_method,
                    "confidence": mapping.confidence_score,
                    "evidence_len": len(mapping.evidence_text or ""),
                    "mapping_status": mapping.mapping_status,
                    "reviewed": mapping.reviewed_at is not None,
                    "reviewed_by": mapping.reviewed_by,
                }
            )
        return rows

    def synthetic_fixtures(self, size: int = 600, seed: Optional[int] = None) -> List[Dict[str, Any]]:
        """Generate deterministic synthetic fixture rows (technical UAT only).

        A planted signal is used so the baseline can be sanity-checked:
        approval probability rises with mapping confidence and lexical overlap.
        """
        rng = random.Random(int(seed if seed is not None else self.seed))
        skill_bank = [
            ("python", "Python programming"),
            ("sql", "SQL"),
            ("data-analysis", "Data analysis"),
            ("machine-learning", "Machine learning"),
            ("cloud-computing", "Cloud computing"),
            ("cybersecurity", "Cybersecurity"),
            ("project-management", "Project management"),
            ("statistics", "Statistics"),
        ]
        sources = [
            "ADZUNA_TRIAL_NOT_EMPIRICAL",
            "dpsa_pull",
            "generic_import",
        ]
        regions = ["Western Cape", "Cape Town", "Gauteng", "KwaZulu-Natal"]

        rows: List[Dict[str, Any]] = []
        for index in range(max(0, int(size))):
            posting_id = f"syn-posting-{index:04d}"
            year = 2025 + (index % 2)
            quarter = 1 + (index % 4)
            source = sources[index % len(sources)]
            region = regions[index % len(regions)]
            skill_key, skill_name = skill_bank[(index * 7) % len(skill_bank)]
            confidence = round(0.5 + 0.48 * ((index * 13) % 7) / 7.0, 4)
            overlap_factor = ((index * 31) % 10) / 10.0
            latent = _clip(0.45 * confidence + 0.5 * overlap_factor + rng.uniform(-0.08, 0.08))
            is_approved = latent >= 0.55
            status = "approved" if is_approved else (rng.choice(["needs_review", "rejected", "candidate"]))
            reviewed = status in ("approved", "rejected")
            description = (
                f"We are hiring for a {skill_name} role. Key responsibilities include "
                f"{skill_name} and related duties. The ideal candidate has experience with "
                f"{skill_key}."
            )
            rows.append(
                {
                    "row_id": f"syn-mapping-{index:05d}",
                    "posting_id": posting_id,
                    "job_id": f"syn-job-{index:04d}",
                    "skill_id": f"syn-skill-{(index * 7) % len(skill_bank)}",
                    "skill_key": skill_key,
                    "skill_name": skill_name,
                    "source": source,
                    "region": region,
                    "country": "ZA",
                    "employment_type": "full_time" if index % 2 == 0 else "part_time",
                    "salary_mid": 40000.0 + (index % 5) * 12000.0,
                    "posting_year": year,
                    "posting_quarter": quarter,
                    "title": f"{skill_name.title()} Vacancy",
                    "description": description,
                    "required_skills": [skill_name],
                    "skills_count": 1,
                    "matched_text": skill_name,
                    "extraction_method": (
                        "declared_job_skill" if index % 3 else "curated_text_phrase"
                    ),
                    "confidence": confidence,
                    "evidence_len": 80,
                    "mapping_status": status,
                    "reviewed": reviewed,
                    "reviewed_by": None,
                }
            )
        return rows

    # ------------------------------------------------------------------
    # Cleaning / dedupe / splits
    # ------------------------------------------------------------------

    def deduplicate_rows(self, rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        seen: Dict[str, Mapping[str, Any]] = {}
        for row in rows:
            key = canonical_row_key(row)
            existing = seen.get(key)
            if existing is None:
                seen[key] = row
        return list(seen.values())

    def assign_splits(
        self,
        rows: Sequence[Mapping[str, Any]],
        seed: Optional[int] = None,
    ) -> Dict[str, str]:
        """Assign a split to every *posting* (groups multiple mapping rows)."""
        effective_seed = int(seed if seed is not None else self.seed)
        posting_ids = sorted({str(row["posting_id"]) for row in rows})
        assignment: Dict[str, str] = {}

        if self.scheme == "hash":
            boundaries = []
            cumulative = 0.0
            for split in SPLIT_ORDER:
                cumulative += self.split_ratios[split]
                boundaries.append(round(cumulative * 100.0))
            for posting_id in posting_ids:
                digest = stable_hash(f"{effective_seed}:{posting_id}")[:8]
                bucket = int(digest, 16) % 100
                if bucket < boundaries[0]:
                    assignment[posting_id] = "train"
                elif bucket < boundaries[1]:
                    assignment[posting_id] = "validation"
                else:
                    assignment[posting_id] = "test"
            return assignment

        periods = sorted({f"{row['posting_year']}-Q{row['posting_quarter']}" for row in rows})
        split_assignments: List[str] = []
        cumulative = 0.0
        split_index = 0
        for index, _period in enumerate(periods):
            cumulative += 1.0 / len(periods)
            while split_index < len(SPLIT_ORDER) - 1 and cumulative > self.split_ratios[SPLIT_ORDER[split_index]]:
                split_index += 1
            split_assignments.append(SPLIT_ORDER[split_index])
        period_to_split = dict(zip(periods, split_assignments))
        for posting_id in posting_ids:
            period = next(
                (
                    f"{row['posting_year']}-Q{row['posting_quarter']}"
                    for row in rows
                    if str(row["posting_id"]) == posting_id
                ),
                periods[-1] if periods else "2026-Q1",
            )
            assignment[posting_id] = period_to_split.get(period, "train")
        return assignment

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        rows: Sequence[Mapping[str, Any]],
        seed: Optional[int] = None,
        mask_test_labels: Optional[bool] = None,
    ) -> TrainingDatasetRecord:
        effective_seed = int(seed if seed is not None else self.seed)
        mask = self.mask_test_labels if mask_test_labels is None else bool(mask_test_labels)

        materialised = [dict(row) for row in rows]
        deduped = self.deduplicate_rows(materialised)
        deduplicated = len(materialised) - len(deduped)

        if not deduped:
            raise TrainingDatasetError(
                "cannot build a training dataset because the evidence row set is empty"
            )

        for row in deduped:
            if not row.get("row_id"):
                raise TrainingDatasetError("dataset rows require a stable row_id")
            if not row.get("posting_id"):
                raise TrainingDatasetError("dataset rows require a posting_id (split grouping key)")

        posting_splits = self.assign_splits(deduped, seed=effective_seed)
        for row in deduped:
            row["split"] = posting_splits[str(row["posting_id"])]

        missing: Dict[str, int] = {
            name: 0
            for name in (
                "description",
                "title",
                "confidence",
                "mapping_status",
                "posting_year",
                "posting_quarter",
                "region",
            )
        }
        for row in deduped:
            for name in missing:
                if row.get(name) is None:
                    missing[name] += 1

        distributions: Dict[str, Dict[str, int]] = {}
        for split in SPLIT_ORDER:
            labels: Dict[str, int] = {}
            for row in deduped:
                if row["split"] == split:
                    label = derive_label(row)
                    key = label if label is not None else "unlabelled"
                    labels[key] = labels.get(key, 0) + 1
            distributions[split] = labels
        all_labels: Dict[str, int] = {}
        for split in SPLIT_ORDER:
            for key, count in distributions[split].items():
                all_labels[key] = all_labels.get(key, 0) + count

        if mask:
            for row in deduped:
                if row["split"] == "test":
                    if "mapping_status" in row or derive_label(row) is not None:
                        row["_masked_label"] = derive_label(row)
                    row["mapping_status"] = None

        splits: Dict[str, List[str]] = {}
        for split in SPLIT_ORDER:
            splits[split] = [row["row_id"] for row in deduped if row["split"] == split]

        source_signature = self.source_signature(deduped)
        version = self.version(deduped, source_signature, effective_seed, mask)

        return TrainingDatasetRecord(
            version=version,
            schema_version=DATASET_SCHEMA_VERSION,
            feature_names=list(FEATURE_NAMES),
            target_definition=dict(TARGET_DEFINITION),
            scheme=self.scheme,
            seed=effective_seed,
            source_signature=source_signature,
            rows=[dict(row) for row in deduped],
            splits=splits,
            class_distribution={
                "overall": all_labels,
                "per_split": distributions,
            },
            missing=missing,
            deduplicated=deduplicated,
            masked_test_labels=mask,
        )

    def source_signature(self, rows: Sequence[Mapping[str, Any]]) -> str:
        summary = [
            {
                "posting_id": str(row["posting_id"]),
                "skill_key": row.get("skill_key"),
                "mapping_status": row.get("mapping_status"),
                "split": row.get("split"),
            }
            for row in rows
        ]
        summary.sort(key=lambda item: (item["posting_id"], item["skill_key"], item["mapping_status"]))
        return stable_hash(json.dumps(summary, sort_keys=True, separators=(",", ":")))

    def version(
        self,
        rows: Sequence[Mapping[str, Any]],
        source_signature: str,
        seed: int,
        mask: bool,
    ) -> str:
        payload = {
            "schema": DATASET_SCHEMA_VERSION,
            "features": FEATURE_NAMES,
            "target": TARGET_DEFINITION,
            "scheme": self.scheme,
            "split_ratios": self.split_ratios,
            "seed": seed,
            "source_signature": source_signature,
            "n_rows": len(rows),
            "mask_test_labels": mask,
        }
        digest = stable_hash(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return f"labour-ds-v1-{digest[:16]}"

    def training_rows(self, record: TrainingDatasetRecord) -> List[Dict[str, Any]]:
        """Rows eligible for training: train + validation, labels required."""
        rows = record.split_rows("train") + record.split_rows("validation")
        return [row for row in rows if derive_label(row) is not None]


labour_training_dataset_service = LabourTrainingDatasetService()