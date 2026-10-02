"""
Normalise cleaned labour-market ingestion records into trend facts.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.cleaned_ingestion_record import CleanedIngestionRecord
from app.models.labour_market_signal import LabourMarketSignal
from app.models.labour_market_trend import LabourMarketTrend
from app.services.ingestion.lineage_service import lineage_service


PROVINCES = {
    "western cape",
    "eastern cape",
    "northern cape",
    "free state",
    "kwazulu-natal",
    "north west",
    "gauteng",
    "mpumalanga",
    "limpopo",
    "south africa",
}

INDUSTRIES = {
    "agriculture",
    "mining",
    "manufacturing",
    "utilities",
    "construction",
    "trade",
    "transport",
    "finance",
    "community and social services",
    "private households",
}

OCCUPATIONS = {
    "manager",
    "professional",
    "technician",
    "clerk",
    "sales and services",
    "skilled agriculture",
    "craft and related trade",
    "plant and machine operator",
    "elementary",
    "domestic worker",
}

IGNORE_LABELS = {
    "estimate",
    "p-value",
    "lower",
    "upper",
    "cv",
    "other",
    "both sexes",
    "men",
    "women",
    "total",
    "rates (%)",
    "thousand",
    "per cent",
}

CANONICAL_INDICATORS = [
    {
        "key": "unemployment_rate",
        "name": "Unemployment rate",
        "patterns": ("unemployment rate", "unemployed", "unemployment"),
        "unit": "percent",
        "risk_weight": 0.95,
    },
    {
        "key": "employment_count",
        "name": "Employment count",
        "patterns": ("employed", "employment"),
        "unit": "thousand",
        "risk_weight": 0.85,
    },
    {
        "key": "labour_force",
        "name": "Labour force",
        "patterns": ("labour force", "labor force"),
        "unit": "thousand",
        "risk_weight": 0.80,
    },
    {
        "key": "absorption_rate",
        "name": "Absorption rate",
        "patterns": ("absorption rate", "absorption"),
        "unit": "percent",
        "risk_weight": 0.75,
    },
    {
        "key": "labour_force_participation_rate",
        "name": "Labour force participation rate",
        "patterns": ("participation rate", "labour force participation"),
        "unit": "percent",
        "risk_weight": 0.75,
    },
    {
        "key": "not_economically_active",
        "name": "Not economically active",
        "patterns": ("not economically active", "inactive"),
        "unit": "thousand",
        "risk_weight": 0.65,
    },
    {
        "key": "discouraged_workseekers",
        "name": "Discouraged workseekers",
        "patterns": ("discouraged", "discouraged work"),
        "unit": "thousand",
        "risk_weight": 0.70,
    },
]


class LabourMarketTrendService:
    """
    Converts cleaned ingestion records into model-ready trend facts.
    """

    def normalise_from_cleaned_records(
        self,
        db: Session,
        job_id: Optional[str] = None,
        limit: int = 1000,
        actor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = db.query(CleanedIngestionRecord).order_by(CleanedIngestionRecord.created_at.asc())
        if job_id:
            query = query.filter(CleanedIngestionRecord.job_id == job_id)

        records = query.limit(limit).all()
        trends_seen = 0
        trends_inserted = 0
        skipped_records = 0

        existing_hashes = {
            row[0]
            for row in db.query(LabourMarketTrend.observation_hash).all()
        }

        for record in records:
            payload = record.cleaned_payload or {}
            if payload.get("record_type") != "statssa_qlfs_table":
                skipped_records += 1
                continue

            facts = self.extract_facts(record)
            trends_seen += len(facts)

            inserted_for_record = 0
            for fact in facts:
                if fact["observation_hash"] in existing_hashes:
                    continue
                trend = LabourMarketTrend(**fact)
                db.add(trend)
                existing_hashes.add(fact["observation_hash"])
                inserted_for_record += 1
                trends_inserted += 1

            if inserted_for_record:
                lineage_service.record_event(
                    db=db,
                    job_id=record.job_id,
                    source_id=record.source_id,
                    input_record_id=record.raw_record_id,
                    source_system=record.source.name if record.source else "unknown",
                    processing_stage="labour_market_trend_normalisation",
                    transformation_description="Normalised cleaned labour-market table record into trend facts.",
                    actor_id=actor_id,
                    metadata={
                        "cleaned_record_id": str(record.cleaned_record_id),
                        "facts_inserted": inserted_for_record,
                    },
                )

        db.flush()
        return {
            "records_seen": len(records),
            "records_skipped": skipped_records,
            "trend_facts_seen": trends_seen,
            "trend_facts_inserted": trends_inserted,
        }

    def generate_signals(
        self,
        db: Session,
        limit: int = 50000,
        actor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        trends = (
            db.query(
                LabourMarketTrend.trend_id,
                LabourMarketTrend.indicator_name,
                LabourMarketTrend.measure_name,
                LabourMarketTrend.dimension_type,
                LabourMarketTrend.dimension_value,
                LabourMarketTrend.year,
                LabourMarketTrend.quarter,
                LabourMarketTrend.value,
                LabourMarketTrend.unit,
                LabourMarketTrend.source_file,
                LabourMarketTrend.table_title,
            )
            .order_by(LabourMarketTrend.created_at.asc())
            .limit(limit)
            .all()
        )

        grouped: Dict[tuple, Dict[str, Any]] = {}
        skipped = 0
        for trend in trends:
            canonical = self.classify_canonical_indicator(trend)
            if not canonical:
                skipped += 1
                continue

            group_key = (
                canonical["key"],
                trend.dimension_type or "category",
                trend.dimension_value or "unknown",
                trend.year,
                trend.quarter,
            )
            bucket = grouped.setdefault(
                group_key,
                {
                    "canonical": canonical,
                    "dimension_type": trend.dimension_type or "category",
                    "dimension_value": trend.dimension_value or "unknown",
                    "year": trend.year,
                    "quarter": trend.quarter,
                    "values": [],
                    "units": [],
                    "trend_ids": [],
                    "source_files": set(),
                    "table_titles": set(),
                },
            )
            bucket["values"].append(float(trend.value))
            if trend.unit:
                bucket["units"].append(trend.unit)
            bucket["trend_ids"].append(str(trend.trend_id))
            if trend.source_file:
                bucket["source_files"].add(trend.source_file)
            if trend.table_title:
                bucket["table_titles"].add(trend.table_title)

        max_by_indicator: Dict[str, float] = defaultdict(float)
        for bucket in grouped.values():
            observed = sum(bucket["values"]) / max(len(bucket["values"]), 1)
            max_by_indicator[bucket["canonical"]["key"]] = max(
                max_by_indicator[bucket["canonical"]["key"]],
                abs(observed),
            )

        existing_hashes = {
            row[0]
            for row in db.query(LabourMarketSignal.signal_hash).all()
        }
        seen = 0
        inserted = 0

        for bucket in grouped.values():
            canonical = bucket["canonical"]
            observed = sum(bucket["values"]) / max(len(bucket["values"]), 1)
            max_value = max(max_by_indicator.get(canonical["key"], 0.0), 1.0)
            normalised = min(1.0, abs(observed) / max_value)
            confidence = min(0.95, 0.45 + min(len(bucket["values"]), 25) / 50)
            demand_score = min(
                1.0,
                (normalised * 0.75)
                + (canonical["risk_weight"] * 0.15)
                + (confidence * 0.10),
            )
            signal_hash = self.hash_signal(
                canonical["key"],
                bucket["dimension_type"],
                bucket["dimension_value"],
                bucket["year"],
                str(bucket["quarter"]),
            )
            seen += 1
            if signal_hash in existing_hashes:
                continue

            db.add(
                LabourMarketSignal(
                    canonical_key=canonical["key"],
                    canonical_name=canonical["name"],
                    signal_type="labour_market",
                    dimension_type=bucket["dimension_type"],
                    dimension_value=bucket["dimension_value"],
                    year=bucket["year"],
                    quarter=str(bucket["quarter"]),
                    observed_value=round(observed, 4),
                    normalised_value=round(normalised, 4),
                    demand_score=round(demand_score, 4),
                    confidence_score=round(confidence, 4),
                    evidence_count=len(bucket["values"]),
                    unit=self.pick_unit(bucket["units"], canonical.get("unit")),
                    method="canonical_signal_v1",
                    source_summary=", ".join(sorted(bucket["source_files"]))[:2000],
                    signal_hash=signal_hash,
                    signal_metadata={
                        "trend_ids": bucket["trend_ids"][:100],
                        "source_file_count": len(bucket["source_files"]),
                        "table_titles": sorted(bucket["table_titles"])[:20],
                        "classification_patterns": canonical["patterns"],
                    },
                )
            )
            existing_hashes.add(signal_hash)
            inserted += 1

        if inserted:
            lineage_service.record_event(
                db=db,
                job_id=None,
                source_id=None,
                input_record_id=None,
                source_system="labour_market_trend",
                processing_stage="canonical_labour_market_signal_generation",
                transformation_description="Aggregated labour-market trend facts into canonical model-ready demand signals.",
                actor_id=actor_id,
                metadata={
                    "signals_seen": seen,
                    "signals_inserted": inserted,
                    "trend_facts_seen": len(trends),
                    "trend_facts_skipped": skipped,
                },
            )

        db.flush()
        return {
            "trend_facts_seen": len(trends),
            "trend_facts_skipped": skipped,
            "signals_seen": seen,
            "signals_inserted": inserted,
        }

    def extract_facts(self, record: CleanedIngestionRecord) -> List[Dict[str, Any]]:
        payload = record.cleaned_payload or {}
        raw_payload = payload.get("raw_payload") or {}
        normalised = payload.get("normalised_payload") or {}
        rows = raw_payload.get("rows") or []
        year = self.to_int(raw_payload.get("year") or normalised.get("year"))
        quarter = raw_payload.get("quarter") or normalised.get("quarter")
        source_file = raw_payload.get("source_file") or payload.get("source_record_id")
        table_title = self.extract_table_title(raw_payload, rows)

        if not year or not quarter:
            return []

        facts: List[Dict[str, Any]] = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            label = self.extract_row_label(row)
            if not label:
                continue
            dimension_type = self.infer_dimension_type(label, table_title)

            for measure_name, value in self.numeric_values(row):
                if measure_name.startswith("meta_"):
                    continue
                if self.is_header_measure(measure_name, value):
                    continue

                indicator_name = self.build_indicator_name(table_title, label, measure_name)
                fact = {
                    "cleaned_record_id": record.cleaned_record_id,
                    "raw_record_id": record.raw_record_id,
                    "job_id": record.job_id,
                    "source_id": record.source_id,
                    "indicator_name": indicator_name[:500],
                    "measure_name": str(measure_name)[:255],
                    "dimension_type": dimension_type,
                    "dimension_value": label[:255],
                    "year": year,
                    "quarter": str(quarter),
                    "value": float(value),
                    "unit": self.infer_unit(table_title, measure_name, label),
                    "source_file": source_file,
                    "table_title": table_title,
                    "observation_hash": self.hash_fact(
                        str(record.cleaned_record_id),
                        row_index,
                        indicator_name,
                        year,
                        str(quarter),
                        float(value),
                    ),
                    "extraction_metadata": {
                        "row_index": row_index,
                        "table_index": raw_payload.get("table_index"),
                        "page": raw_payload.get("page"),
                        "series_code": raw_payload.get("series_code"),
                        "normalisation_method": "heuristic_statsa_table_v1",
                    },
                }
                facts.append(fact)
        return facts

    @staticmethod
    def extract_table_title(raw_payload: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
        for key in ("title", "table_title"):
            if raw_payload.get(key):
                return str(raw_payload[key])
        for row in rows[:3]:
            for key in row.keys():
                if key.startswith("meta_"):
                    continue
                if len(str(key)) > 20 and not str(key).startswith("None"):
                    return str(key)
        return "StatsSA QLFS extracted table"

    @staticmethod
    def extract_row_label(row: Dict[str, Any]) -> Optional[str]:
        for key, value in row.items():
            if key.startswith("meta_"):
                continue
            if not isinstance(value, str):
                continue
            cleaned = " ".join(value.strip().split())
            if not cleaned:
                continue
            if cleaned.lower() in IGNORE_LABELS:
                continue
            if cleaned.replace(".", "", 1).replace("-", "", 1).isdigit():
                continue
            return cleaned
        return None

    @staticmethod
    def numeric_values(row: Dict[str, Any]) -> Iterable[tuple[str, float]]:
        for key, value in row.items():
            if key.startswith("meta_"):
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                yield str(key), float(value)

    @staticmethod
    def is_header_measure(measure_name: str, value: float) -> bool:
        if measure_name in {"None", "None_1"} and value in {2008.0, 2009.0, 2010.0, 2011.0, 2012.0}:
            return True
        return False

    @staticmethod
    def infer_dimension_type(label: str, table_title: str) -> str:
        normalized = label.strip().lower()
        if normalized in PROVINCES:
            return "province"
        if normalized in INDUSTRIES:
            return "industry"
        if normalized in OCCUPATIONS:
            return "occupation"
        title = table_title.lower()
        if "province" in title:
            return "province"
        if "industry" in title:
            return "industry"
        if "occupation" in title:
            return "occupation"
        if "sex" in title:
            return "sex"
        return "category"

    @staticmethod
    def infer_unit(table_title: str, measure_name: str, label: str) -> Optional[str]:
        combined = " ".join([table_title, measure_name, label]).lower()
        if "%" in combined or "rate" in combined or "per cent" in combined:
            return "percent"
        if "thousand" in combined:
            return "thousand"
        return None

    @staticmethod
    def build_indicator_name(table_title: str, label: str, measure_name: str) -> str:
        title = " ".join(table_title.split())
        return f"{title} | {label} | {measure_name}"

    @staticmethod
    def hash_fact(
        cleaned_record_id: str,
        row_index: int,
        indicator_name: str,
        year: int,
        quarter: str,
        value: float,
    ) -> str:
        payload = {
            "cleaned_record_id": cleaned_record_id,
            "row_index": row_index,
            "indicator_name": indicator_name,
            "year": year,
            "quarter": quarter,
            "value": value,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def to_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def summary(self, db: Session) -> Dict[str, Any]:
        total = db.query(func.count(LabourMarketTrend.trend_id)).scalar() or 0
        signal_total = db.query(func.count(LabourMarketSignal.signal_id)).scalar() or 0
        by_dimension = (
            db.query(LabourMarketTrend.dimension_type, func.count(LabourMarketTrend.trend_id))
            .group_by(LabourMarketTrend.dimension_type)
            .order_by(LabourMarketTrend.dimension_type)
            .all()
        )
        by_signal = (
            db.query(LabourMarketSignal.canonical_key, func.count(LabourMarketSignal.signal_id))
            .group_by(LabourMarketSignal.canonical_key)
            .order_by(LabourMarketSignal.canonical_key)
            .all()
        )
        by_time = (
            db.query(LabourMarketTrend.year, LabourMarketTrend.quarter, func.count(LabourMarketTrend.trend_id))
            .group_by(LabourMarketTrend.year, LabourMarketTrend.quarter)
            .order_by(LabourMarketTrend.year.desc(), LabourMarketTrend.quarter.desc())
            .limit(12)
            .all()
        )
        return {
            "total_trends": total,
            "total_signals": signal_total,
            "by_dimension_type": {dimension: count for dimension, count in by_dimension},
            "by_canonical_signal": {signal: count for signal, count in by_signal},
            "recent_periods": [
                {"year": year, "quarter": quarter, "count": count}
                for year, quarter, count in by_time
            ],
        }

    @staticmethod
    def classify_canonical_indicator(trend: LabourMarketTrend) -> Optional[Dict[str, Any]]:
        combined = " ".join(
            [
                trend.indicator_name or "",
                trend.measure_name or "",
                trend.dimension_value or "",
                trend.table_title or "",
            ]
        ).lower()
        for indicator in CANONICAL_INDICATORS:
            if any(pattern in combined for pattern in indicator["patterns"]):
                return indicator
        return None

    @staticmethod
    def pick_unit(units: List[str], fallback: Optional[str]) -> Optional[str]:
        if not units:
            return fallback
        counts: Dict[str, int] = defaultdict(int)
        for unit in units:
            counts[unit] += 1
        return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]

    @staticmethod
    def hash_signal(
        canonical_key: str,
        dimension_type: str,
        dimension_value: str,
        year: int,
        quarter: str,
    ) -> str:
        payload = {
            "canonical_key": canonical_key,
            "dimension_type": dimension_type,
            "dimension_value": dimension_value,
            "year": year,
            "quarter": quarter,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


labour_market_trend_service = LabourMarketTrendService()
