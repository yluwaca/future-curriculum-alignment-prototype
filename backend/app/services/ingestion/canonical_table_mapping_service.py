"""
Canonical table mapping for public PDF/table sources.
"""

from __future__ import annotations

import re
from typing import Any, Dict


CANONICAL_TABLE_RULES = [
    {
        "source_family": "statssa",
        "patterns": [r"\bemploy(?:ed|ment)?\b", r"labou?r\s+force", r"absorption\s+rate"],
        "indicator_group": "employment",
        "domain": "labour_market",
        "measure_type": "count_or_rate",
        "confidence": 0.88,
    },
    {
        "source_family": "statssa",
        "patterns": [r"\bunemploy(?:ed|ment)?\b", r"not\s+economically\s+active", r"discouraged\s+work"],
        "indicator_group": "unemployment",
        "domain": "labour_market",
        "measure_type": "count_or_rate",
        "confidence": 0.9,
    },
    {
        "source_family": "statssa",
        "patterns": [r"occupation", r"professional", r"technician", r"clerical", r"manager"],
        "indicator_group": "occupation",
        "domain": "labour_market",
        "measure_type": "distribution",
        "confidence": 0.86,
    },
    {
        "source_family": "statssa",
        "patterns": [r"industry", r"sector", r"manufactur", r"construction", r"finance", r"community\s+and\s+social"],
        "indicator_group": "industry",
        "domain": "labour_market",
        "measure_type": "distribution",
        "confidence": 0.86,
    },
    {
        "source_family": "statssa",
        "patterns": [r"province", r"western\s+cape", r"gauteng", r"kwazulu", r"eastern\s+cape"],
        "indicator_group": "province",
        "domain": "labour_market",
        "measure_type": "geographic_distribution",
        "confidence": 0.8,
    },
    {
        "source_family": "statssa",
        "patterns": [r"age\s+group", r"\b15[\s-]+24\b", r"\b25[\s-]+34\b", r"youth"],
        "indicator_group": "age_group",
        "domain": "labour_market",
        "measure_type": "demographic_distribution",
        "confidence": 0.78,
    },
    {
        "source_family": "statssa",
        "patterns": [r"education", r"qualification", r"tertiary", r"matric", r"higher\s+education"],
        "indicator_group": "education_level",
        "domain": "labour_market",
        "measure_type": "education_distribution",
        "confidence": 0.78,
    },
    {
        "source_family": "che",
        "patterns": [r"enrol", r"headcount", r"student\s+numbers", r"first-time\s+entering"],
        "indicator_group": "enrolment",
        "domain": "higher_education_supply",
        "measure_type": "count",
        "confidence": 0.88,
    },
    {
        "source_family": "che",
        "patterns": [r"graduate", r"graduation", r"completion", r"qualification\s+awarded"],
        "indicator_group": "graduation",
        "domain": "higher_education_supply",
        "measure_type": "count_or_rate",
        "confidence": 0.88,
    },
    {
        "source_family": "che",
        "patterns": [r"throughput", r"retention", r"dropout", r"success\s+rate", r"progression"],
        "indicator_group": "throughput",
        "domain": "higher_education_supply",
        "measure_type": "rate",
        "confidence": 0.86,
    },
    {
        "source_family": "che",
        "patterns": [r"field\s+of\s+study", r"cesm", r"science", r"engineering", r"technology", r"business"],
        "indicator_group": "field_of_study",
        "domain": "higher_education_supply",
        "measure_type": "distribution",
        "confidence": 0.8,
    },
    {
        "source_family": "che",
        "patterns": [r"institution", r"university", r"university\s+of\s+technology", r"cput"],
        "indicator_group": "institution",
        "domain": "higher_education_supply",
        "measure_type": "institution_distribution",
        "confidence": 0.76,
    },
]


class CanonicalTableMappingService:
    def map_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        title = str(row.get("meta_table_title") or "")
        source_file = str(row.get("meta_source_file") or "")
        canonical_table = str(row.get("meta_canonical_table") or "")
        descriptors = " ".join(
            str(value) for key, value in row.items()
            if not str(key).startswith("meta_") and value is not None and not isinstance(value, (int, float))
        )
        text = " ".join([title, source_file, canonical_table, descriptors]).lower()
        source_family = self.detect_source_family(text)
        for rule in CANONICAL_TABLE_RULES:
            if rule["source_family"] != source_family:
                continue
            matched_pattern = next((pattern for pattern in rule["patterns"] if re.search(pattern, text)), None)
            if matched_pattern:
                return {
                    "source_family": source_family,
                    "canonical_indicator_group": rule["indicator_group"],
                    "canonical_domain": rule["domain"],
                    "measure_type": rule["measure_type"],
                    "mapping_confidence": rule.get("confidence", 0.82),
                    "matched_rule": matched_pattern,
                }
        fallback_group = self.fallback_indicator_group(canonical_table, text)
        return {
            "source_family": source_family,
            "canonical_indicator_group": fallback_group,
            "canonical_domain": "higher_education_supply" if source_family == "che" else "labour_market" if source_family == "statssa" and fallback_group != "unknown" else "unknown",
            "measure_type": "unknown",
            "mapping_confidence": 0.52 if fallback_group != "unknown" else 0.1,
            "matched_rule": None,
        }

    @staticmethod
    def detect_source_family(text: str) -> str:
        if re.search(r"\b(vital\s*stats|che|higher\s+education|graduation|enrolment|throughput)\b", text):
            return "che"
        if re.search(r"\b(qlfs|statssa|stats\s*sa|labou?r\s+force|unemploy|employ)\b", text) or re.search(r"p0?211", text):
            return "statssa"
        return "unknown"


    @staticmethod
    def fallback_indicator_group(canonical_table: str, text: str) -> str:
        value = (canonical_table or "").strip().lower().replace(" ", "_")
        if value and value not in {"unknown", "statssa_qlfs_extracted_table", "stats_sa_qlfs_extracted_table"}:
            return value[:120]
        if any(term in text for term in ["total", "number", "rate", "percentage", "thousand", "per cent", "quarter", "year-on-year"]):
            return "general_indicator"
        return "unknown"


canonical_table_mapping_service = CanonicalTableMappingService()
