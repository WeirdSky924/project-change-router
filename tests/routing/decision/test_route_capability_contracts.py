from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.route_capability_contracts import (  # noqa: E402
    compare_capability_contract,
    ordered_secondary_capabilities,
)


def test_changed_path_owners_replace_semantic_secondary_noise() -> None:
    owners = {
        "app/services/observability/postgres_service.py": ["observability-core"],
        "app/database/postgres.py": ["database-gateway-runtime"],
        "app/services/workflow/trace_readback.py": ["workflow-execution-adapter"],
        "app/api/project_postgres_app.py": ["api-facade"],
    }
    scores = {
        "observability-core": 0.89,
        "api-facade": 0.64,
        "frontend-transport-hooks": 0.60,
        "workflow-runtime-orchestration": 0.46,
        "workflow-execution-adapter": 0.42,
        "database-gateway-runtime": 0.41,
    }

    secondary = ordered_secondary_capabilities(
        primary_capability="observability-core",
        changed_paths=list(owners),
        scored_capabilities=scores,
        guarded_threshold=0.45,
        dependency_priority={
            "database-gateway-runtime": 1,
            "workflow-execution-adapter": 1,
            "observability-core": 4,
            "api-facade": 6,
            "frontend-transport-hooks": 7,
            "workflow-runtime-orchestration": 8,
        },
        path_capabilities=lambda path: owners[path],
    )

    assert secondary == [
        "workflow-execution-adapter",
        "database-gateway-runtime",
        "api-facade",
    ]


def test_score_fallback_remains_for_requests_without_changed_paths() -> None:
    secondary = ordered_secondary_capabilities(
        primary_capability="observability-core",
        changed_paths=[],
        scored_capabilities={
            "observability-core": 0.80,
            "api-facade": 0.60,
            "frontend-transport-hooks": 0.40,
        },
        guarded_threshold=0.45,
        dependency_priority={},
        path_capabilities=lambda path: [],
    )

    assert secondary == ["api-facade"]


def test_exact_secondary_contract_reports_missing_and_unexpected() -> None:
    case = {
        "expected_capabilities": ["observability-core"],
        "expected_primary_capability": "observability-core",
        "expected_secondary_capabilities": [
            "database-gateway-runtime",
            "workflow-execution-adapter",
            "api-facade",
        ],
        "secondary_match": "exact",
    }

    comparison = compare_capability_contract(
        case,
        predicted_primary="observability-core",
        predicted_secondary=[
            "workflow-execution-adapter",
            "api-facade",
            "frontend-transport-hooks",
        ],
    )

    assert comparison["primary_ok"] is True
    assert comparison["secondary_ok"] is False
    assert comparison["missing_secondary_capabilities"] == [
        "database-gateway-runtime"
    ]
    assert comparison["unexpected_secondary_capabilities"] == [
        "frontend-transport-hooks"
    ]


def test_legacy_primary_membership_remains_compatible_without_opt_in() -> None:
    comparison = compare_capability_contract(
        {"expected_capabilities": ["observability-core", "api-facade"]},
        predicted_primary="api-facade",
        predicted_secondary=["observability-core"],
    )

    assert comparison["strict_secondary"] is False
    assert comparison["primary_ok"] is True
    assert comparison["secondary_ok"] is True


def test_exact_primary_does_not_imply_a_strict_secondary_contract() -> None:
    comparison = compare_capability_contract(
        {
            "expected_capabilities": ["observability-core"],
            "expected_primary_capability": "observability-core",
        },
        predicted_primary="observability-core",
        predicted_secondary=["incidental-capability"],
    )

    assert comparison["strict_primary"] is True
    assert comparison["strict_secondary"] is False
    assert comparison["primary_ok"] is True
    assert comparison["secondary_ok"] is True
