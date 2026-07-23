from __future__ import annotations

import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support.repository_surfaces import (
    STANDARD_REPOSITORY_SURFACE_DIRECTORIES,
    STANDARD_REPOSITORY_SURFACE_FILES,
)


def _write(path: Path, content: str = "name: ci\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_standard_ci_surfaces_use_one_development_infrastructure_capability(
    tmp_path: Path,
) -> None:
    surface_files = {
        ".github/workflows": ".github/workflows/ci.yml",
        ".github/actions": ".github/actions/setup/action.yml",
        ".circleci": ".circleci/config.yml",
        ".buildkite": ".buildkite/pipeline.yml",
    }
    for relative in surface_files.values():
        _write(tmp_path / relative)
    for relative in STANDARD_REPOSITORY_SURFACE_FILES:
        _write(tmp_path / relative, "pipeline\n")
    _write(tmp_path / ".private/tool.py", "VALUE = 1\n")

    modules = router_core.discover_modules(tmp_path)
    standard_modules = [
        module
        for module in modules
        if module.lifecycle.get("discovery_strategy")
        == "standard-repository-surface"
    ]
    capabilities = router_core.infer_capabilities_from_modules(
        tmp_path,
        modules,
        {},
        "structured",
    )
    path_map = router_core.build_path_to_capability_map(
        tmp_path,
        capabilities,
        modules,
    )

    assert {module.path for module in standard_modules} == {
        *STANDARD_REPOSITORY_SURFACE_DIRECTORIES,
        *STANDARD_REPOSITORY_SURFACE_FILES,
    }
    assert all(module.layer == "infra" for module in standard_modules)
    assert all(
        module.domain == "development-infrastructure"
        for module in standard_modules
    )
    assert all(
        module.owner == "provisional:development-infrastructure"
        for module in standard_modules
    )
    assert ".private" not in {module.path for module in modules}
    assert path_map["lookup"][".github/workflows/**"] == [
        "development-infrastructure"
    ]
    assert path_map["lookup"][".circleci/**"] == [
        "development-infrastructure"
    ]
    assert path_map["lookup"][".buildkite/**"] == [
        "development-infrastructure"
    ]
    assert path_map["lookup"]["Jenkinsfile"] == [
        "development-infrastructure"
    ]
    assert "Jenkinsfile/**" not in path_map["lookup"]


def test_standard_ci_surface_discovery_respects_explicit_ignore(
    tmp_path: Path,
) -> None:
    _write(tmp_path / ".github/workflows/ci.yml")
    _write(tmp_path / ".circleci/config.yml")

    modules = router_core.discover_modules(
        tmp_path,
        config={"ignore_paths": [".github/workflows/**"]},
    )

    paths = {module.path for module in modules}
    assert ".github/workflows" not in paths
    assert ".circleci" in paths


@pytest.mark.parametrize(
    "pattern",
    (".github/workflows/**", "/.github/workflows/*"),
)
def test_standard_ci_surface_uses_codeowners_file_evidence(
    tmp_path: Path,
    pattern: str,
) -> None:
    _write(tmp_path / ".github/workflows/ci.yml")
    _write(tmp_path / ".github/CODEOWNERS", f"{pattern} @release-team\n")

    modules = router_core.discover_modules(tmp_path)

    workflow = next(
        module for module in modules if module.path == ".github/workflows"
    )
    assert workflow.owner == "@release-team"


def test_standard_ci_surface_rejects_partial_codeowners_consensus(
    tmp_path: Path,
) -> None:
    for index in range(7):
        _write(tmp_path / f".github/workflows/{index:02d}.yml")
    _write(
        tmp_path / ".github/CODEOWNERS",
        (
            ".github/workflows/** @release-team\n"
            ".github/workflows/06.yml @other-team\n"
        ),
    )

    modules = router_core.discover_modules(tmp_path)

    workflow = next(
        module for module in modules if module.path == ".github/workflows"
    )
    assert len(workflow.key_files) == 6
    assert workflow.owner == "provisional:development-infrastructure"


def test_exact_profile_override_owns_standard_surface_without_duplicate_capability(
    tmp_path: Path,
) -> None:
    _write(tmp_path / ".github/workflows/ci.yml")
    profile = {
        "profile_id": "release-automation-profile",
        "module_overrides": [
            {
                "id": "module-release-automation",
                "path": ".github/workflows",
                "layer": "infra",
                "domain": "release-automation",
                "purpose": "Curated release automation boundary",
                "owner": "release-platform",
            }
        ],
        "capabilities": [
            {
                "id": "release-automation",
                "name": "Release Automation",
                "status": "stable",
                "stage": "stable",
                "path_patterns": [".github/workflows/**"],
                "public_entries": [".github/workflows/ci.yml"],
            }
        ],
    }

    modules = router_core.discover_modules(tmp_path, profile=profile)
    capabilities = router_core.infer_capabilities_from_modules(
        tmp_path,
        modules,
        profile,
        "structured",
    )
    path_map = router_core.build_path_to_capability_map(
        tmp_path,
        capabilities,
        modules,
        profile,
    )

    matched = [module for module in modules if module.path == ".github/workflows"]
    assert len(matched) == 1
    assert matched[0].id == "module-release-automation"
    assert matched[0].domain == "release-automation"
    assert matched[0].owner == "release-platform"
    assert matched[0].source_of_truth == "profile"
    assert matched[0].generated is False
    assert matched[0].index_sources == ["profile.module_overrides"]
    assert matched[0].lifecycle["definition_source"] == (
        "profile.module_overrides"
    )
    assert [capability.id for capability in capabilities] == [
        "release-automation"
    ]
    assert path_map["lookup"][".github/workflows/**"] == [
        "release-automation"
    ]
