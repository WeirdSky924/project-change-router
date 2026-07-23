from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


def test_explicit_module_override_path_materializes_nested_python_module(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "nested-profile-repo"
    package = repo / "app" / "services" / "villains"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "service.py").write_text(
        "class VillainConflictService:\n    pass\n",
        encoding="utf-8",
    )
    profile = {
        "profile_id": "nested-profile",
        "module_overrides": [
            {
                "path": "app/services/villains",
                "path_patterns": ["app/services/villains/**"],
                "layer": "domain-service",
                "domain": "villain-conflict",
                "public_api": "__init__.py",
                "owner": "villain-conflict",
                "import_names": ["app.services.villains"],
            }
        ],
        "ownership_rules": [
            {
                "path_patterns": ["app/services/villains/**"],
                "owner": "villain-conflict",
            }
        ],
        "capabilities": [
            {
                "id": "villain-conflict",
                "name": "Villain Conflict",
                "status": "stable",
                "stage": "stable",
                "path_patterns": ["app/services/villains/**"],
                "public_entries": ["app/services/villains/__init__.py"],
            }
        ],
    }

    modules = router_core.discover_modules(repo, profile=profile)
    module = next(
        item for item in modules if item.path == "app/services/villains"
    )
    capabilities, _ = router_core.apply_profile_capabilities(repo, modules, profile)
    capability = next(item for item in capabilities if item.id == "villain-conflict")
    path_map = router_core.build_path_to_capability_map(
        repo,
        capabilities,
        modules,
        profile,
    )
    path_entry = next(
        item
        for item in path_map["path_index"]
        if item["path_pattern"] == "app/services/villains/**"
    )

    assert module.source_of_truth == "profile"
    assert module.generated is False
    assert module.public_api == "__init__.py"
    assert module.owner == "villain-conflict"
    assert capability.owner_modules == ["app/services/villains"]
    assert capability.public_entries == ["app/services/villains/__init__.py"]
    assert router_core.capability_code_file_count(repo, capability) == 2
    assert path_entry["code_file_count"] == 2


def test_explicit_planned_module_override_materializes_missing_canonical_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "planned-profile-repo"
    legacy = repo / "app" / "services" / "agent_runtime"
    legacy.mkdir(parents=True)
    (legacy / "__init__.py").write_text("", encoding="utf-8")
    (legacy / "assistant_context_persistence.py").write_text(
        "class LegacyAssistantContextPersistence:\n    pass\n",
        encoding="utf-8",
    )
    profile = {
        "profile_id": "planned-profile",
        "module_overrides": [
            {
                "path": "app/services/assistant_context",
                "id": "module-assistant-context-fabric",
                "status": "planned",
                "path_patterns": [
                    "app/services/assistant_context/**",
                    "app/services/agent_runtime/assistant_context_persistence.py",
                ],
                "layer": "shared-capability",
                "domain": "assistant-context-fabric",
                "public_api": "app.services.assistant_context",
                "owner": "assistant-context-fabric",
                "import_names": ["app.services.assistant_context"],
            }
        ],
        "ownership_rules": [
            {
                "path_patterns": ["app/services/assistant_context/**"],
                "owner": "assistant-context-fabric",
            }
        ],
        "capabilities": [
            {
                "id": "assistant-context-fabric",
                "name": "Assistant Context Fabric",
                "status": "stable",
                "stage": "stable",
                "path_patterns": [
                    "app/services/assistant_context/**",
                    "app/services/agent_runtime/assistant_context_persistence.py",
                ],
                "public_entries": ["app/services/assistant_context/__init__.py"],
            }
        ],
    }

    modules = router_core.discover_modules(repo, profile=profile)
    module = next(
        item for item in modules if item.path == "app/services/assistant_context"
    )
    capabilities, _ = router_core.apply_profile_capabilities(repo, modules, profile)
    capability = next(
        item for item in capabilities if item.id == "assistant-context-fabric"
    )

    assert not (repo / module.path).exists()
    assert module.status == "planned"
    assert module.source_of_truth == "profile"
    assert module.owner == "assistant-context-fabric"
    assert module.lifecycle["planned_path"] is True
    assert capability.owner_modules == ["app/services/assistant_context"]
