from __future__ import annotations

import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_core import (
    CapabilityEntry,
    build_write_constraints,
    required_checks_for,
)


OWNER_MODULES = ["app/services/outline", "app/services/plots"]
OUTLINE_CHANGED_PATHS = [
    "app/services/outline/repository.py",
    "app/services/outline/postgres_repository.py",
    "app/services/outline/postgres_wiring.py",
    "app/services/outline/repository_compatibility.py",
]
CROSS_OWNER_CHANGED_PATHS = [
    "app/database/postgres.py",
    "app/api/project_postgres_app.py",
]
BASE_REQUIRED_CHECKS = {
    "check-reuse",
    "check-deps",
    "check-public-api",
    "check-structure",
    "check-index-freshness",
}


def _outline_capability() -> CapabilityEntry:
    return CapabilityEntry(
        id="outline-planning",
        name="Outline Planning",
        status="stable",
        maturity="curated",
        owner_modules=OWNER_MODULES,
    )


def _path_scoped_test_capability() -> CapabilityEntry:
    capability = _outline_capability()
    capability.test_bindings = [
        {
            "id": "tests-outline-readiness",
            "when_actions": ["extend", "extract"],
            "when_changed_paths": ["app/services/outline/**"],
        },
        {
            "id": "tests-creative-planning",
            "when_actions": ["extend", "extract"],
            "when_changed_paths": [
                "app/services/plots/creative_planning/**"
            ],
        },
        {
            "id": "tests-outline-planning-general",
            "when_actions": ["extend", "extract"],
        },
    ]
    return capability


@pytest.mark.parametrize("action", ["extend", "extract"])
def test_mutating_action_scopes_broad_owner_writes_to_changed_owner_module(
    action: str,
) -> None:
    changed_paths = [*OUTLINE_CHANGED_PATHS, *CROSS_OWNER_CHANGED_PATHS]

    allowed, forbidden, _ = build_write_constraints(
        action,
        _outline_capability(),
        changed_paths,
        [],
    )

    assert "app/services/outline/**" in allowed
    assert "app/services/plots/**" not in allowed
    assert set(CROSS_OWNER_CHANGED_PATHS) <= set(allowed)
    assert forbidden == []


@pytest.mark.parametrize("action", ["extend", "extract"])
def test_mutating_action_keeps_only_exact_cross_owner_paths_without_owner_match(
    action: str,
) -> None:
    allowed, forbidden, _ = build_write_constraints(
        action,
        _outline_capability(),
        CROSS_OWNER_CHANGED_PATHS,
        [],
    )

    assert set(allowed) == {
        *CROSS_OWNER_CHANGED_PATHS,
    }
    assert forbidden == []


@pytest.mark.parametrize("action", ["extend", "extract"])
def test_mutating_action_keeps_owner_module_fallback_without_declared_paths(
    action: str,
) -> None:
    allowed, forbidden, _ = build_write_constraints(
        action,
        _outline_capability(),
        [],
        [],
    )

    assert set(allowed) == {
        "app/services/outline/**",
        "app/services/plots/**",
    }
    assert forbidden == []


def test_reuse_still_allows_only_exact_changed_paths_and_forbids_owner_modules() -> None:
    changed_paths = [OUTLINE_CHANGED_PATHS[0], CROSS_OWNER_CHANGED_PATHS[0]]

    allowed, forbidden, _ = build_write_constraints(
        "reuse",
        _outline_capability(),
        changed_paths,
        ["restricted/**"],
    )

    assert allowed == changed_paths
    assert forbidden == [
        "restricted/**",
        "app/services/outline/**",
        "app/services/plots/**",
    ]


def test_review_still_forbids_every_write() -> None:
    allowed, forbidden, _ = build_write_constraints(
        "review",
        _outline_capability(),
        [OUTLINE_CHANGED_PATHS[0]],
        ["restricted/**"],
    )

    assert allowed == []
    assert forbidden == ["restricted/**", "**"]


@pytest.mark.parametrize(
    ("action", "changed_path", "selected", "excluded"),
    [
        (
            "extract",
            "app/services/outline/repository.py",
            "tests-outline-readiness",
            "tests-creative-planning",
        ),
        (
            "extend",
            "app/services/plots/creative_planning/repository.py",
            "tests-creative-planning",
            "tests-outline-readiness",
        ),
    ],
)
def test_required_checks_select_only_path_matching_bindings(
    action: str,
    changed_path: str,
    selected: str,
    excluded: str,
) -> None:
    checks = required_checks_for(
        _path_scoped_test_capability(),
        action,
        {},
        [changed_path],
    )

    assert BASE_REQUIRED_CHECKS <= set(checks)
    assert selected in checks
    assert excluded not in checks
    assert "tests-outline-planning-general" in checks
