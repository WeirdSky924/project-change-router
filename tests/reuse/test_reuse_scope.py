from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.reuse_scope import (  # noqa: E402
    RuntimeDependencyEdge,
    resolve_reuse_scope,
)


def test_exact_path_mapping_overrides_broad_owner_and_keeps_exact_shared_owner() -> None:
    result = resolve_reuse_scope(
        changed_paths=["app/api/workflow_provider.py"],
        path_mappings=[
            {
                "path_pattern": "app/api/workflow_provider.py",
                "capabilities": ["workflow"],
            },
            {"path_pattern": "**", "capabilities": ["repository-fallback"]},
        ],
        module_owners=[
            {"path_pattern": "app/api/**", "capabilities": ["api-facade"]},
            {
                "path_pattern": "app/api/workflow_provider.py",
                "capabilities": ["shared-audit"],
                "relationship": "shared",
            },
        ],
    )

    assert result.status == "resolved"
    assert result.completion_status == "complete"
    assert result.evidence_complete is True
    assert result.direct_capability_ids == ("shared-audit", "workflow")
    assert result.capability_ids == ("shared-audit", "workflow")
    assert result.unresolved_paths == ()
    assert {item["capabilities"][0] for item in result.ignored_broad_mappings} == {
        "api-facade",
        "repository-fallback",
    }


def test_unknown_changed_path_is_incomplete_without_repository_fallback() -> None:
    result = resolve_reuse_scope(
        changed_paths=["docs/new-surface.md"],
        path_mappings=[
            {"path_pattern": "**", "capabilities": ["repository-fallback"]},
        ],
        module_owners=[
            {"path_pattern": "app/api/**", "capabilities": ["api-facade"]},
        ],
    )

    assert result.status == "unresolved"
    assert result.completion_status == "incomplete"
    assert result.evidence_complete is False
    assert result.capability_ids == ()
    assert result.unresolved_paths == ("docs/new-surface.md",)
    assert result.to_dict()["mode"] == "changed_paths"


def test_dependency_expansion_uses_runtime_edges_only_and_stays_one_hop() -> None:
    result = resolve_reuse_scope(
        changed_paths=["app/workflow/service.py"],
        path_mappings=[
            {"path_pattern": "app/workflow/service.py", "capabilities": ["workflow"]},
        ],
        runtime_edges=[
            RuntimeDependencyEdge("workflow", "runtime", runtime=True),
            RuntimeDependencyEdge("workflow", "type-contracts", runtime=False),
            RuntimeDependencyEdge("runtime", "transitive-provider", runtime=True),
            {"source": "observability", "target": "workflow", "runtime": True},
        ],
    )

    assert result.direct_capability_ids == ("workflow",)
    assert result.dependency_capability_ids == ("observability", "runtime")
    assert result.capability_ids == ("observability", "runtime", "workflow")
    assert "type-contracts" not in result.capability_ids
    assert "transitive-provider" not in result.capability_ids
    assert result.evidence_complete is True


def test_parse_diagnostic_keeps_scope_but_marks_evidence_incomplete() -> None:
    result = resolve_reuse_scope(
        changed_paths=["app/workflow/service.py"],
        path_mappings=[
            {"path_pattern": "app/workflow/service.py", "capabilities": ["workflow"]},
        ],
        runtime_edges=[
            RuntimeDependencyEdge("workflow", "runtime", runtime=True),
        ],
        diagnostics=[
            {
                "code": "python-parse-error",
                "path": "app/workflow/service.py",
                "message": "invalid syntax",
            }
        ],
    )

    assert result.status == "resolved"
    assert result.completion_status == "incomplete"
    assert result.evidence_complete is False
    assert result.capability_ids == ("runtime", "workflow")
    assert result.diagnostics[0]["code"] == "python-parse-error"


def test_no_changed_paths_is_incomplete_instead_of_implicit_full_scan() -> None:
    result = resolve_reuse_scope(
        changed_paths=[],
        path_mappings=[
            {"path_pattern": "app/**", "capabilities": ["application"]},
        ],
    )

    assert result.status == "unresolved"
    assert result.completion_status == "incomplete"
    assert result.evidence_complete is False
    assert result.capability_ids == ()
    assert result.unresolved_paths == ()
