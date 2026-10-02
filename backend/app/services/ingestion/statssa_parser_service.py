# =========================================================
# StatsSA Parser Service
# =========================================================

"""
Refactored from standalone extractor script into backend service.

Purpose:
- Parse StatsSA QLFS PDFs
- Extract tables
- Clean data
- Return structured dataset (NOT write files)

Author: Yolisa Luwaca (refactored for backend)
"""

import pdfplumber
import pandas as pd
import numpy as np
import re
import logging

from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Optional, List, Dict, Tuple, Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# =========================================================
# DEFAULT CONFIG (simplified for backend)
# =========================================================

DEFAULT_CONFIG = {
    "min_table_rows": 3,
    "min_table_cols": 2,
    "header_keywords": [
        "Thousand", "Per cent", "Population", "Employed",
        "Unemployed", "Labour force", "Not economically active",
        "Rate", "Industry", "Province", "Occupation", "Sex"
    ],
    "numeric_cleaning": {
        "thousand_sep": " ",
        "missing_values": ["..", ".", "-", "", "N/A", "—", "–", "*", "#"],
        "replace_missing_with": None,
        "negative_parentheses": True
    }
}


# =========================================================
# UTILITY FUNCTIONS
# =========================================================

def parse_filename(filename: str) -> Dict:
    metadata = {
        "year": None,
        "quarter": None,
        "series_code": None
    }

    series_match = re.match(r'^([A-Z]\d{4})', filename, re.I)
    if series_match:
        metadata["series_code"] = series_match.group(1)

    year_match = re.search(r'(19|20)\d{2}', filename)
    if year_match:
        metadata["year"] = int(year_match.group())

    if "1stQuarter" in filename:
        metadata["quarter"] = "Q1"
    elif "2ndQuarter" in filename:
        metadata["quarter"] = "Q2"
    elif "3rdQuarter" in filename:
        metadata["quarter"] = "Q3"
    elif "4thQuarter" in filename:
        metadata["quarter"] = "Q4"

    return metadata


def clean_numeric_value(value: Any, config: Dict):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return value

    try:
        value_str = str(value).strip()
    except Exception:
        return None

    if not value_str:
        return None

    if value_str in config["missing_values"]:
        return None

    numeric_candidate = value_str.replace(config["thousand_sep"], "")

    if config["negative_parentheses"]:
        if numeric_candidate.startswith("(") and numeric_candidate.endswith(")"):
            numeric_candidate = "-" + numeric_candidate[1:-1]

    try:
        cleaned = re.sub(r'[^\d.\-]', '', numeric_candidate)

        if cleaned in {"", "-", "."}:
            return value_str

        numeric_digits = re.sub(r'\D', '', cleaned)
        if len(numeric_digits) > 15:
            return value_str

        if "." not in cleaned:
            return int(cleaned)

        return float(cleaned)

    except Exception:
        return value_str


def make_columns_unique(df: pd.DataFrame) -> pd.DataFrame:
    cols = []
    seen = {}

    for col in df.columns:
        col = str(col).strip()

        if col in seen:
            seen[col] += 1
            cols.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            cols.append(col)

    df.columns = cols
    return df


# =========================================================
# CORE PARSER SERVICE
# =========================================================

class StatsSAParserService:

    def __init__(self):
        self.input_dir = settings.statssa_path

    # -----------------------------------------------------
    # Extract tables from single PDF
    # -----------------------------------------------------
    def extract_tables(
        self,
        pdf_path: Path,
        page_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[Dict]:

        tables_data = []
        metadata = parse_filename(pdf_path.name)

        logger.info(f"Processing PDF: {pdf_path.name}")

        try:
            with pdfplumber.open(pdf_path) as pdf:

                page_total = len(pdf.pages)

                for page_index, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    if not self.should_attempt_table_extraction(page_text):
                        if page_callback:
                            page_callback(page_index + 1, page_total)
                        continue

                    tables = page.extract_tables()

                    for table_index, table in enumerate(tables):

                        if not table:
                            continue

                        if len(table) < DEFAULT_CONFIG["min_table_rows"]:
                            continue

                        title = self.detect_table_title(page_text, table_index + 1)
                        tables_data.append({
                            "raw_data": table,
                            "page": page_index + 1,
                            "table_index": table_index + 1,
                            "title": title,
                            "canonical_table": self.classify_table(title or page_text),
                            "source_file": pdf_path.name,
                            "year": metadata["year"],
                            "quarter": metadata["quarter"],
                            "series_code": metadata["series_code"],
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })

                    if page_callback:
                        page_callback(page_index + 1, page_total)

        except Exception as e:
            logger.error(f"Error processing {pdf_path.name}: {e}")

        return tables_data

    @staticmethod
    def should_attempt_table_extraction(page_text: str) -> bool:
        text = (page_text or "").lower()
        if not text.strip():
            return False

        indicators = [
            "table",
            "thousand",
            "per cent",
            "employment",
            "employed",
            "unemployed",
            "labour force",
            "not economically active",
            "quarter",
            "province",
            "industry",
            "occupation",
            "qlfs",
        ]
        return any(indicator in text for indicator in indicators)

    @staticmethod
    def detect_table_title(page_text: str, table_index: int) -> str:
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in (page_text or "").splitlines()
            if line and line.strip()
        ]
        table_lines = [
            line for line in lines
            if re.search(r"\btable\b|\bfigure\b", line, re.I)
            and len(line) <= 180
        ]
        if table_index <= len(table_lines):
            return table_lines[table_index - 1]
        for line in lines:
            if any(keyword in line.lower() for keyword in DEFAULT_CONFIG["header_keywords"]) and len(line) <= 180:
                return line
        return "StatsSA QLFS extracted table"

    @staticmethod
    def classify_table(text: str) -> str:
        value = (text or "").lower()
        patterns = [
            ("employment_by_industry", ["industry", "employed"]),
            ("employment_by_occupation", ["occupation", "employed"]),
            ("employment_by_province", ["province", "employed"]),
            ("labour_force_status", ["labour force", "unemployed", "not economically active"]),
            ("unemployment_rate", ["unemployment rate", "rate"]),
            ("demographic_breakdown", ["sex", "age", "population group"]),
        ]
        for key, terms in patterns:
            if all(term in value for term in terms):
                return key
        return "qlfs_general_table"

    # -----------------------------------------------------
    # Clean table into DataFrame
    # -----------------------------------------------------
    def clean_table(self, table_info: Dict) -> pd.DataFrame:

        raw_table = table_info["raw_data"]

        df = pd.DataFrame(raw_table)
        df = df.dropna(how='all').reset_index(drop=True)

        if df.empty:
            return df

        # Set first row as header
        df.columns = [str(c).strip() for c in df.iloc[0]]
        df = df.iloc[1:].reset_index(drop=True)
        df = make_columns_unique(df)

        # Clean numeric values
        for col in df.columns:
            df[col] = df[col].apply(
                lambda x: clean_numeric_value(x, DEFAULT_CONFIG["numeric_cleaning"])
            )

        # Add metadata
        df["meta_year"] = table_info["year"]
        df["meta_quarter"] = table_info["quarter"]
        df["meta_source_file"] = table_info["source_file"]
        df["meta_table_title"] = table_info.get("title")
        df["meta_canonical_table"] = table_info.get("canonical_table")

        return df

    # -----------------------------------------------------
    # Parse ALL PDFs
    # -----------------------------------------------------
    def parse_all(self) -> List[Dict]:

        pdf_files = list(self.input_dir.glob("*.pdf"))

        logger.info(f"Found {len(pdf_files)} PDF files")

        results = []

        for pdf in pdf_files:

            tables = self.extract_tables(pdf)

            for tbl in tables:

                df = self.clean_table(tbl)

                if df.empty:
                    continue

                results.append({
                    "year": tbl["year"],
                    "quarter": tbl["quarter"],
                    "data": df.to_dict(orient="records")
                })

        logger.info(f"Parsed datasets: {len(results)}")

        return results
