"""Executable backend RBAC contract for portal operational mutations."""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.dependencies import require_role


ROUTER_DIR = Path(__file__).resolve().parents[1] / "app" / "routers"
ROUTERS = (
    "ingestion",
    "curriculum",
    "processing",
    "operations",
    "predictive",
    "admin",
)
AUTHENTICATED_DECISION_ACTIONS = {
    ("predictive", "predict_alignment"),
    ("predictive", "forecast_demand"),
}


def mutation_functions(router_name: str):
    path = ROUTER_DIR / f"{router_name}.py"
    source = path.read_text(encoding="utf-8-sig")
    lines = source.splitlines()
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        methods = []
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"post", "put", "patch", "delete"}
            ):
                methods.append(decorator.func.attr.upper())
        if methods:
            signature = "\n".join(lines[node.lineno - 1 : node.body[0].lineno - 1])
            yield node.name, signature


def test_every_operational_mutation_has_an_explicit_role_gate():
    missing = []
    for router_name in ROUTERS:
        for function_name, signature in mutation_functions(router_name):
            if (router_name, function_name) in AUTHENTICATED_DECISION_ACTIONS:
                continue
            has_role_gate = "require_role(" in signature
            has_admin_permission = (
                router_name == "admin"
                and 'require_permission("system.admin")' in signature
            )
            if not has_role_gate and not has_admin_permission:
                missing.append(f"{router_name}.{function_name}")
    assert missing == [], f"Operational mutations without backend role gates: {missing}"


@pytest.mark.parametrize(
    ("router_name", "function_name", "expected_roles"),
    [
        ("ingestion", "save_source_credentials", {"ADMIN"}),
        ("ingestion", "enqueue_due_schedules", {"ADMIN"}),
        ("ingestion", "update_contract", {"ADMIN", "DATA_SCIENTIST"}),
        (
            "ingestion",
            "generic_source_intake",
            {"ADMIN", "ANALYST", "DATA_SCIENTIST"},
        ),
        (
            "curriculum",
            "upload_curriculum_document",
            {"ADMIN", "ANALYST", "DATA_SCIENTIST"},
        ),
        ("predictive", "train_xgboost", {"ADMIN", "DATA_SCIENTIST"}),
        ("predictive", "promote_registry_entry", {"ADMIN"}),
        (
            "processing",
            "run_full_processing_pipeline",
            {"ADMIN", "ANALYST", "DATA_SCIENTIST"},
        ),
        ("operations", "generate_operations_backup_manifest", {"ADMIN"}),
    ],
)
def test_high_risk_endpoint_role_sets(router_name, function_name, expected_roles):
    signature = dict(mutation_functions(router_name))[function_name]
    match = re.search(r"require_role\((.*?)\)", signature, re.DOTALL)
    assert match, f"No role declaration found for {router_name}.{function_name}"
    declared = set(re.findall(r'"([A-Z_]+)"', match.group(1)))
    assert declared == expected_roles


def test_role_checker_denies_viewer_and_allows_declared_roles():
    checker = require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")
    viewer = SimpleNamespace(
        is_admin=False,
        roles=[SimpleNamespace(role_id="VIEWER")],
    )
    with pytest.raises(HTTPException) as denied:
        asyncio.run(checker(viewer))
    assert denied.value.status_code == 403

    analyst = SimpleNamespace(
        is_admin=False,
        roles=[SimpleNamespace(role_id="ANALYST")],
    )
    assert asyncio.run(checker(analyst)) is analyst

    admin = SimpleNamespace(is_admin=True, roles=[])
    assert asyncio.run(checker(admin)) is admin


def test_system_performance_endpoint_is_admin_only():
    source = (ROUTER_DIR / "operations.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "system_performance"
    )
    signature = "\n".join(source.splitlines()[function.lineno - 1 : function.body[0].lineno - 1])
    assert 'require_role("ADMIN")' in signature
