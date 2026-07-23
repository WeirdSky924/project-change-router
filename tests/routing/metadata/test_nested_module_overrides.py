from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


def test_profile_module_snapshot_replacement_drops_stale_structure(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "provider-repo"
    module_root = repo / "app" / "services" / "provider_execution"
    module_root.mkdir(parents=True)
    (repo / ".git").mkdir()
    (module_root / "contracts.py").write_text("class Contract:\n    pass\n", encoding="utf-8")
    (module_root / "gateway.py").write_text("class Gateway:\n    pass\n", encoding="utf-8")
    profile = {
        "module_overrides": [
            {
                "id": "module-provider-execution-gateway",
                "path": "app/services/provider_execution",
                "status": "migrating",
                "layer": "shared-capability",
                "domain": "provider-execution-gateway",
                "public_api": "contracts.py",
                "key_files": ["contracts.py", "gateway.py"],
                "allowed_inbound_from": ["app/services/foundation"],
                "lifecycle": {
                    "replace_snapshot_boundaries": True,
                    "implementation_state": "gateway_core_active",
                },
            }
        ]
    }

    discovered = router_core.discover_modules(repo, profile=profile)
    replacement = next(
        item.to_dict()
        for item in discovered
        if item.path == "app/services/provider_execution"
    )
    existing = {
        "modules": [
            {
                "id": "module-provider-execution-gateway",
                "path": "app/services/provider_execution",
                "status": "planned",
                "public_api": "__init__.py",
                "source_of_truth": "profile",
                "key_files": [
                    "app/services/provider_execution/__init__.py",
                    "app/services/provider_execution/contracts.py",
                ],
                "allowed_inbound_from": ["app/services/legacy"],
                "lifecycle": {"implementation_state": "planned"},
            }
        ]
    }

    merged = router_core.merge_curated_records(
        existing,
        {"modules": [replacement]},
        "modules",
        "path",
    )["modules"][0]

    assert merged["status"] == "migrating"
    assert merged["public_api"] == "contracts.py"
    assert merged["key_files"] == ["contracts.py", "gateway.py"]
    assert merged["allowed_inbound_from"] == ["app/services/foundation"]
    assert merged["lifecycle"]["implementation_state"] == "gateway_core_active"
    assert merged["lifecycle"]["replace_snapshot_boundaries"] is True


def test_profile_module_override_can_split_a_file_from_its_package(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "layered-python-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "app" / "services" / "memory").mkdir(parents=True)
    (repo / "app" / "services" / "memory" / "core.py").write_text(
        "class MemoryCore:\n    pass\n", encoding="utf-8"
    )
    (repo / "app" / "services" / "memory" / "persistence.py").write_text(
        "from .core import MemoryCore\n", encoding="utf-8"
    )
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: layered-memory
module_overrides:
  - id: module-memory-persistence
    path: app/services/memory
    layer: domain-service
    domain: memory-core
  - id: module-memory-core
    path: app/services/memory/core.py
    layer: shared-capability
    domain: memory-core
""".strip()
        + "\n",
        encoding="utf-8",
    )

    bundle = router_core.bootstrap_bundle(repo, write=True)
    modules = {item["path"]: item for item in bundle["module_map"]["modules"]}
    capability = router_core.CapabilityEntry(
        id="memory-core",
        name="Memory Core",
        status="stable",
        maturity="curated",
        owner_modules=["app/services/memory", "app/services/memory/core.py"],
    )

    assert modules["app/services/memory"]["layer"] == "domain-service"
    assert "core.py" not in modules["app/services/memory"]["key_files"]
    assert modules["app/services/memory/core.py"]["layer"] == "shared-capability"
    assert modules["app/services/memory/core.py"]["key_files"] == ["core.py"]
    assert router_core.capability_code_file_count(repo, capability) == 2


def test_nested_module_boundary_does_not_authorize_observed_adapter_import(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "layered-python-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "app" / "services" / "memory").mkdir(parents=True)
    (repo / "app" / "services" / "plots").mkdir(parents=True)
    (repo / "app" / "services" / "memory" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (repo / "app" / "services" / "memory" / "persistence.py").write_text(
        "from app.services.plots.postgres_adapter import PlotAdapter\n",
        encoding="utf-8",
    )
    (repo / "app" / "services" / "memory" / "core.py").write_text(
        "class MemoryCore:\n    pass\n", encoding="utf-8"
    )
    (repo / "app" / "services" / "plots" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (repo / "app" / "services" / "plots" / "postgres_adapter.py").write_text(
        "class PlotAdapter:\n    pass\n", encoding="utf-8"
    )
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: layered-memory
module_overrides:
  - id: module-memory-persistence
    path: app/services/memory
    layer: domain-service
    domain: memory-core
    nested_module_boundary: true
  - id: module-memory-core
    path: app/services/memory/core.py
    layer: shared-capability
    domain: memory-core
  - id: module-plots-adapter
    path: app/services/plots
    layer: adapter
    domain: plots
""".strip()
        + "\n",
        encoding="utf-8",
    )

    bundle = router_core.bootstrap_bundle(repo, write=True)
    findings = router_core.gather_dependency_findings(repo, bundle)

    assert any(
        finding["rule"] == "dependency-direction"
        and finding["source"] == "app/services/memory/persistence.py"
        and finding["target"] == "app/services/plots/postgres_adapter.py"
        and finding["blocking"] is True
        for finding in findings
    )


def test_strict_nested_module_does_not_fall_back_to_an_allowed_layer() -> None:
    source = router_core.ModuleEntry(
        id="module-skill-execution-audit-persistence",
        path="app/services/agent_runtime/skill_execution_audit_persistence",
        layer="adapter",
        domain="shared-agent-runtime",
        purpose="Skill execution audit persistence",
        lifecycle={
            "nested_module_boundary": True,
            "declared_allowed_outbound_to": ["app/database"],
            "allowed_outbound_layers": ["domain-service"],
        },
    )
    database = router_core.ModuleEntry(
        id="module-database-gateway",
        path="app/database",
        layer="infrastructure",
        domain="database-schema-migrations",
        purpose="Database infrastructure",
    )
    workflow = router_core.ModuleEntry(
        id="module-workflow-execution",
        path="app/services/workflow",
        layer="domain-service",
        domain="workflow-execution-adapter",
        purpose="Workflow execution",
    )

    assert router_core.matches_dependency(source, database) is True
    assert router_core.matches_dependency(source, workflow) is False


def test_nested_module_distinguishes_missing_and_empty_path_policies() -> None:
    workflow = router_core.ModuleEntry(
        id="module-workflow-execution",
        path="app/services/workflow",
        layer="domain-service",
        domain="workflow-execution-adapter",
        purpose="Workflow execution",
    )
    legacy_source = router_core.ModuleEntry(
        id="module-legacy-nested-boundary",
        path="app/services/legacy",
        layer="adapter",
        domain="legacy",
        purpose="Legacy nested boundary pending explicit path migration",
        lifecycle={
            "nested_module_boundary": True,
            "allowed_outbound_layers": ["domain-service"],
        },
    )
    deny_all_source = router_core.ModuleEntry(
        id="module-deny-all-nested-boundary",
        path="app/services/isolated",
        layer="adapter",
        domain="isolated",
        purpose="Strict nested boundary with no outbound dependencies",
        lifecycle={
            "nested_module_boundary": True,
            "declared_allowed_outbound_to": [],
            "allowed_outbound_layers": ["domain-service"],
        },
    )

    assert router_core.matches_dependency(legacy_source, workflow) is True
    assert router_core.matches_dependency(deny_all_source, workflow) is False


def test_profile_rebuild_removes_a_stale_nested_path_policy() -> None:
    existing = {
        "modules": [
            {
                "id": "module-character-aggregate",
                "path": "app/services/character",
                "source_of_truth": "profile",
                "lifecycle": {
                    "nested_module_boundary": True,
                    "declared_allowed_outbound_to": [],
                },
            }
        ]
    }
    generated = {
        "modules": [
            {
                "id": "module-character-aggregate",
                "path": "app/services/character",
                "source_of_truth": "profile",
                "lifecycle": {"nested_module_boundary": True},
            }
        ]
    }

    merged = router_core.merge_curated_records(
        existing,
        generated,
        "modules",
        "path",
    )

    assert "declared_allowed_outbound_to" not in merged["modules"][0]["lifecycle"]


def test_strict_nested_policy_matches_the_concrete_import_target() -> None:
    source = router_core.ModuleEntry(
        id="module-lore-postgres-service",
        path="app/services/lore/postgres_service.py",
        layer="domain-service",
        domain="lore-core",
        purpose="Lore application service",
        lifecycle={
            "nested_module_boundary": True,
            "declared_allowed_outbound_to": ["app/services/lore/repository.py"],
            "allowed_outbound_layers": ["domain-service"],
        },
    )
    parent_target = router_core.ModuleEntry(
        id="module-lore-package",
        path="app/services/lore",
        layer="domain-service",
        domain="lore-core",
        purpose="Lore package",
    )

    assert router_core.matches_dependency(
        source,
        parent_target,
        dependency_path="app/services/lore/repository.py",
    ) is True
