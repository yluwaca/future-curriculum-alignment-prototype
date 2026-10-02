"""Build leakage-safe XGBoost inputs from an immutable reviewed-label snapshot."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from sqlalchemy.orm import Session

from app.models.label_dataset_snapshot import LabelDatasetSnapshot, LabelDatasetSnapshotRow
from app.services.label_dataset_snapshot_service import label_dataset_snapshot_service


class ReviewedAlignmentTrainingDatasetService:
    """Verify locked membership and derive features only from source evidence."""

    FEATURE_CONTRACT_ID = "reviewed_alignment_lexical_v1"
    WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}")
    DATE_KEYS = ("window_end", "period_end", "evidence_date", "observed_at", "as_of", "date", "year")

    def load(self, db: Session, snapshot: LabelDatasetSnapshot) -> Dict[str, Any]:
        if snapshot.lifecycle_state != "approved_locked":
            raise RuntimeError("Reviewed-label snapshot is not approved and locked")

        rows = (
            db.query(LabelDatasetSnapshotRow)
            .filter(LabelDatasetSnapshotRow.snapshot_id == snapshot.snapshot_id)
            .order_by(LabelDatasetSnapshotRow.row_index.asc())
            .all()
        )
        if len(rows) != snapshot.row_count:
            raise RuntimeError("Locked reviewed-label snapshot row-count integrity check failed")

        payloads: List[Dict[str, Any]] = []
        records: List[Dict[str, Any]] = []
        for row in rows:
            payload = dict(row.row_payload or {})
            if label_dataset_snapshot_service.fingerprint(payload) != row.row_fingerprint:
                raise RuntimeError(f"Locked reviewed-label row integrity check failed at index {row.row_index}")
            if int(payload.get("final_alignment_label", 0)) != int(row.final_alignment_label):
                raise RuntimeError(f"Locked reviewed-label target mismatch at index {row.row_index}")
            payloads.append(payload)
            records.append(
                {
                    "row_index": int(row.row_index),
                    "task_id": str(row.task_id),
                    "document_id": str(payload.get("document_id")),
                    "version_id": str(payload.get("version_id")),
                    "group_id": str(payload.get("version_id") or row.task_id),
                    "features": self.build_features(payload),
                    "continuous_target": (float(row.final_alignment_label) - 1.0) / 4.0,
                    "final_alignment_label": int(row.final_alignment_label),
                    "faculty": self._faculty(payload.get("evidence_metadata")),
                    "chronology": self._chronology(payload, row.row_index),
                }
            )

        fingerprint_payload = {
            "schema": snapshot.feature_schema,
            "rubric": snapshot.label_rubric,
            "inclusion_rules": snapshot.inclusion_rules,
            "rows": payloads,
        }
        if label_dataset_snapshot_service.fingerprint(fingerprint_payload) != snapshot.dataset_fingerprint:
            raise RuntimeError("Locked reviewed-label snapshot fingerprint integrity check failed")

        records.sort(key=lambda item: (item["chronology"]["sort_key"], item["row_index"]))
        dated = sum(1 for item in records if item["chronology"]["dated"])
        chronology_values = sorted({
            item["chronology"]["value"] for item in records if item["chronology"]["dated"]
        })
        return {
            "snapshot_id": str(snapshot.snapshot_id),
            "snapshot_version": snapshot.snapshot_version,
            "dataset_fingerprint": snapshot.dataset_fingerprint,
            "records": records,
            "row_count": len(records),
            "ordering_policy": (
                "evidence_chronology_then_locked_row_index"
                if dated == len(records)
                else "available_evidence_chronology_then_locked_row_index"
            ),
            "dated_row_count": dated,
            "undated_row_count": len(records) - dated,
            "distinct_chronology_values": len(chronology_values),
            "chronology_range": (
                [chronology_values[0], chronology_values[-1]] if chronology_values else []
            ),
            "feature_contract": {
                "contract_id": self.FEATURE_CONTRACT_ID,
                "contract_version": 1,
                "source": "immutable label_dataset_snapshot_row.row_payload",
                "allowed_inputs": ["curriculum_evidence", "labour_market_evidence"],
                "excluded_inputs": [
                    "expert labels",
                    "reviewer identities",
                    "review justifications",
                    "present/missing skill annotations",
                    "generated model scores",
                ],
                "target": "(final_alignment_label - 1) / 4",
                "missing_feature_policy": "zero",
            },
        }

    def build_serving_features(
        self,
        curriculum: Any,
        labour_market_records: Iterable[Any],
    ) -> Dict[str, float]:
        """Apply the training feature algorithm to live, label-free evidence.

        Only fields available before prediction are projected.  Keeping this
        projection here prevents the serving path from silently reverting to
        the unrelated TF-IDF feature generator.
        """
        curriculum_evidence = " ".join(
            str(value)
            for value in (
                getattr(curriculum, "module_name", None),
                getattr(curriculum, "description", None),
                getattr(curriculum, "faculty", None),
                getattr(curriculum, "programme", None),
            )
            if value
        )
        labour_market_evidence = [
            {
                "job_title": getattr(record, "job_title", None),
                "job_description": getattr(record, "job_description", None),
                "required_skills": getattr(record, "required_skills", None),
                "education_level": getattr(record, "education_level", None),
                "experience_years": getattr(record, "experience_years", None),
                "region": getattr(record, "region", None),
                "posted_date": getattr(record, "posted_date", None),
            }
            for record in labour_market_records
        ]
        return self.build_features(
            {
                "curriculum_evidence": curriculum_evidence,
                "labour_market_evidence": labour_market_evidence,
            }
        )

    def build_features(self, payload: Dict[str, Any]) -> Dict[str, float]:
        curriculum_text = self._text(payload.get("curriculum_evidence"))
        labour_items = payload.get("labour_market_evidence") or []
        labour_text = self._text(labour_items)
        curriculum_tokens = self._tokens(curriculum_text)
        labour_tokens = self._tokens(labour_text)
        curriculum_set = set(curriculum_tokens)
        labour_set = set(labour_tokens)
        overlap = curriculum_set & labour_set
        union = curriculum_set | labour_set

        return {
            "curriculum_character_count": float(len(curriculum_text)),
            "curriculum_token_count": float(len(curriculum_tokens)),
            "curriculum_unique_token_count": float(len(curriculum_set)),
            "curriculum_lexical_diversity": self._ratio(len(curriculum_set), len(curriculum_tokens)),
            "labour_evidence_record_count": float(len(labour_items) if isinstance(labour_items, list) else 1),
            "labour_character_count": float(len(labour_text)),
            "labour_token_count": float(len(labour_tokens)),
            "labour_unique_token_count": float(len(labour_set)),
            "labour_lexical_diversity": self._ratio(len(labour_set), len(labour_tokens)),
            "shared_unique_token_count": float(len(overlap)),
            "vocabulary_jaccard": self._ratio(len(overlap), len(union)),
            "curriculum_vocabulary_coverage": self._ratio(len(overlap), len(curriculum_set)),
            "labour_vocabulary_coverage": self._ratio(len(overlap), len(labour_set)),
            "evidence_length_ratio": self._ratio(len(curriculum_tokens), len(labour_tokens)),
        }

    def _chronology(self, payload: Dict[str, Any], fallback_index: int) -> Dict[str, Any]:
        """Prefer genuine labour observation dates, then curriculum metadata.

        A task can contain several vacancy/signal dates.  The latest date is the
        end of the evidence window that was available when the alignment label
        was formed.  This is a pre-label field and is safe for ordering only.
        """
        sources = (
            ("labour_market_evidence", payload.get("labour_market_evidence")),
            ("evidence_metadata", payload.get("evidence_metadata")),
        )
        for source_name, source_value in sources:
            candidates: List[tuple[datetime, str]] = []
            if source_name == "labour_market_evidence" and isinstance(source_value, list):
                for index, item in enumerate(source_value):
                    if not isinstance(item, dict) or item.get("year") is None:
                        continue
                    quarter = str(item.get("quarter") or "").strip().upper()
                    period = f"{item['year']} {quarter}" if re.fullmatch(r"Q[1-4]", quarter) else item["year"]
                    parsed = self._parse_date(period)
                    if parsed:
                        candidates.append((parsed, f"[{index}].year_quarter"))
            for key, value in self._items(source_value):
                if source_name == "labour_market_evidence" and key.endswith(".year"):
                    # A labour year has already been combined with its quarter
                    # above; do not let a synthetic 31 December year-end sort
                    # after the genuine quarter observation.
                    continue
                if any(candidate in key.lower() for candidate in self.DATE_KEYS):
                    parsed = self._parse_date(value)
                    if parsed:
                        candidates.append((parsed, key))
            if candidates:
                parsed, key = max(candidates, key=lambda item: item[0])
                return {
                    "dated": True,
                    "value": parsed.isoformat(),
                    "sort_key": parsed.timestamp(),
                    "source": source_name,
                    "source_key": key,
                    "candidate_date_count": len(candidates),
                }
        return {
            "dated": False,
            "value": None,
            "sort_key": float(fallback_index),
            "source": "locked_row_index_fallback",
            "source_key": None,
            "candidate_date_count": 0,
        }

    def _items(self, value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
        if isinstance(value, dict):
            for key in sorted(value):
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                yield from self._items(value[key], next_prefix)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from self._items(item, f"{prefix}[{index}]")
        else:
            yield prefix, value

    @staticmethod
    def _parse_date(value: Any) -> datetime | None:
        if isinstance(value, int) and 1900 <= value <= 2100:
            return datetime(value, 12, 31, tzinfo=timezone.utc)
        if not isinstance(value, str):
            return None
        text = value.strip()
        quarter = re.fullmatch(r"(\d{4})\s*[- ]?Q([1-4])", text, flags=re.IGNORECASE)
        if quarter:
            year, q = int(quarter.group(1)), int(quarter.group(2))
            month = q * 3
            # The first day of the following month minus one day is unnecessary
            # for ordering; month-end at midnight provides a stable period end.
            return datetime(year, month, 1, tzinfo=timezone.utc)
        if re.fullmatch(r"\d{4}", text):
            return datetime(int(text), 12, 31, tzinfo=timezone.utc)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _tokens(self, text: str) -> List[str]:
        return [token.lower() for token in self.WORD_RE.findall(text)]

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)

    @staticmethod
    def _ratio(numerator: int | float, denominator: int | float) -> float:
        if not denominator:
            return 0.0
        value = float(numerator) / float(denominator)
        return value if math.isfinite(value) else 0.0

    @staticmethod
    def _faculty(metadata: Any) -> str:
        if isinstance(metadata, dict):
            return str(metadata.get("faculty") or metadata.get("department") or "unknown")
        return "unknown"


reviewed_alignment_training_dataset_service = ReviewedAlignmentTrainingDatasetService()
