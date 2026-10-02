"""Static dependency-contract audit; performs no network access."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECT = ROOT / "backend" / "requirements.txt"
LOCK = ROOT / "backend" / "requirements.lock"
APP = ROOT / "backend" / "app"

# Import name -> distribution name. Standard-library and app-local imports are
# intentionally absent. Keep this table explicit so optional dependencies are
# reviewed rather than silently inferred.
IMPORT_DISTRIBUTIONS = {
    "alembic": "alembic", "asyncpg": "asyncpg", "cryptography": "cryptography",
    "dotenv": "python-dotenv", "fastapi": "fastapi", "httpx": "httpx",
    "joblib": "joblib", "jose": "python-jose", "numpy": "numpy",
    "pandas": "pandas", "passlib": "passlib", "pdfplumber": "pdfplumber",
    "pgvector": "pgvector", "psutil": "psutil", "pydantic": "pydantic",
    "pydantic_settings": "pydantic-settings", "requests": "requests",
    "scipy": "scipy", "sentence_transformers": "sentence-transformers",
    "shap": "shap", "sklearn": "scikit-learn", "slowapi": "slowapi",
    "sqlalchemy": "sqlalchemy", "structlog": "structlog",
    "tensorflow": "tensorflow", "torch": "torch", "transformers": "transformers",
    "xgboost": "xgboost",
}


def canonical(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def pins(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise AssertionError(f"Unpinned requirement in {path}: {line}")
        name, version = line.split("==", 1)
        name = name.split("[", 1)[0]
        key = canonical(name)
        if key in result:
            raise AssertionError(f"Duplicate requirement in {path}: {name}")
        result[key] = version
    return result


def imported_names() -> set[str]:
    names: set[str] = set()
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
    return names


def main() -> int:
    direct, lock = pins(DIRECT), pins(LOCK)
    errors: list[str] = []
    for name, version in direct.items():
        if lock.get(name) != version:
            errors.append(f"direct/lock mismatch: {name}=={version}, lock={lock.get(name)!r}")
    imports = imported_names()
    for module, distribution in IMPORT_DISTRIBUTIONS.items():
        if module in imports and canonical(distribution) not in direct:
            errors.append(f"import {module!r} lacks direct pin {distribution!r}")
    # openpyxl is selected dynamically by pandas rather than imported directly.
    if "openpyxl" not in direct:
        errors.append("Excel ingestion requires a direct openpyxl pin")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Dependency contract valid: {len(direct)} direct pins, {len(lock)} locked distributions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
