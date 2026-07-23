from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


def test_module_for_path_preserves_leading_dotfile_name() -> None:
    module = router_core.ModuleEntry(
        id="module-routing-governance-profile",
        path=".router.yaml",
        layer="governance",
        domain="routing-governance",
        purpose="Canonical routing profile.",
    )

    assert router_core.module_for_path(".router.yaml", [module]) is module


def test_specific_path_owner_overrides_broad_parent_without_hiding_shared_exact_owner() -> None:
    bundle = {
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "app/services/agent_runtime/**",
                    "capabilities": ["shared-agent-runtime"],
                },
                {
                    "path_pattern": (
                        "app/services/agent_runtime/assistant_context_persistence.py"
                    ),
                    "capabilities": [
                        "assistant-context-fabric",
                        "database-gateway-runtime",
                    ],
                },
            ]
        }
    }

    assert router_core.path_index_capabilities_for_path(
        bundle,
        "app/services/agent_runtime/assistant_context_persistence.py",
    ) == ["assistant-context-fabric", "database-gateway-runtime"]
    assert router_core.path_index_capabilities_for_path(
        bundle,
        "app/services/agent_runtime/orchestration.py",
    ) == ["shared-agent-runtime"]


def test_module_public_entries_never_duplicate_owner_path() -> None:
    module = router_core.ModuleEntry(
        id="module-villain-conflict",
        path="app/services/villains",
        layer="domain-service",
        domain="villain-conflict",
        purpose="Villain application service",
        public_api="app/services/villains/__init__.py",
        key_files=["__init__.py"],
    )

    assert router_core.infer_public_entries_from_modules([module]) == [
        "app/services/villains/__init__.py"
    ]

    module.public_api = "app.services.villains"
    assert router_core.infer_public_entries_from_modules([module]) == [
        "app/services/villains/__init__.py"
    ]


def test_snapshot_boundary_profile_uses_declared_public_entries() -> None:
    module = router_core.ModuleEntry(
        id="module-assistant-context-fabric",
        path="app/services/assistant_context",
        layer="shared-capability",
        domain="assistant-context-fabric",
        purpose="Assistant Context Fabric",
        public_api="app/services/assistant_context/postgres_repository.py",
    )
    profile = {
        "profile_id": "assistant-context-profile",
        "capabilities": [
            {
                "id": "assistant-context-fabric",
                "name": "Assistant Context Fabric",
                "status": "stable",
                "stage": "stable",
                "path_patterns": ["app/services/assistant_context/**"],
                "public_entries": ["app/services/assistant_context/__init__.py"],
                "lifecycle": {"replace_snapshot_boundaries": True},
            }
        ],
    }

    capabilities, _ = router_core.apply_profile_capabilities(
        Path("/nonexistent-repo"),
        [module],
        profile,
    )

    assert capabilities[0].public_entries == [
        "app/services/assistant_context/__init__.py"
    ]


def test_related_test_inference_excludes_runtime_cache_artifacts(
    tmp_path: Path,
) -> None:
    tests_root = tmp_path / "tests"
    cache_root = tests_root / "__pycache__"
    cache_root.mkdir(parents=True)
    (tests_root / "test_assistant_context.py").write_text(
        "def test_contract():\n    assert True\n",
        encoding="utf-8",
    )
    (tests_root / "assistant_context.feature").write_text(
        "Feature: assistant context lifecycle\n",
        encoding="utf-8",
    )
    (cache_root / "test_assistant_context.cpython-311.pyc").write_bytes(b"cache")
    module = router_core.ModuleEntry(
        id="module-assistant-context-fabric",
        path="app/services/assistant_context",
        layer="shared-capability",
        domain="assistant-context-fabric",
        purpose="Assistant Context Fabric",
    )

    assert router_core.infer_related_tests(tmp_path, [module]) == [
        "tests/assistant_context.feature",
        "tests/test_assistant_context.py",
    ]


def test_curated_related_tests_preserve_union_but_drop_runtime_cache() -> None:
    existing = {
        "capabilities": [
            {
                "id": "assistant-context-fabric",
                "source_of_truth": "profile",
                "related_tests": [
                    "tests/test_assistant_context_contract.py",
                    "tests/__pycache__/test_assistant_context.cpython-311.pyc",
                ],
            }
        ]
    }
    generated = {
        "capabilities": [
            {
                "id": "assistant-context-fabric",
                "source_of_truth": "profile",
                "related_tests": [
                    "tests/assistant_context.feature",
                    "tests/test_assistant_context_contract.py",
                ],
            }
        ]
    }

    merged = router_core.merge_curated_records(
        existing,
        generated,
        "capabilities",
        "id",
    )

    assert merged["capabilities"][0]["related_tests"] == [
        "tests/test_assistant_context_contract.py",
        "tests/assistant_context.feature",
    ]


def test_rebuild_replaces_stale_profile_records_instead_of_unioning_lists() -> None:
    existing = {
        "capabilities": [
            {
                "id": "villain-conflict",
                "source_of_truth": "profile",
                "owner_modules": ["app/services/villains", "tests/villains"],
                "contracts": ["stale contract"],
                "forbidden_patterns": ["stale direct DB write"],
                "test_bindings": [{"id": "tests-villains", "label": "stale"}],
                "public_entries": [
                    "app/services/villains/__init__.py",
                    "tests/villains/app/services/villains/__init__.py",
                ],
                "lifecycle": {
                    "persistence_migration": {
                        "affected_callers": [
                            "stale default composition",
                            "supported compatibility export",
                        ]
                    },
                    "public_entry_semantics": {
                        "kind": "declared_public_entry",
                        "heuristic_entries": [
                            "app/services/villains/__init__.py",
                            "app/services/villains/app/services/villains/__init__.py",
                            "tests/villains/app/services/villains/__init__.py",
                        ],
                    }
                },
            }
        ]
    }
    generated = {
        "capabilities": [
            {
                "id": "villain-conflict",
                "name": "Villain Conflict",
                "status": "stable",
                "stage": "stable",
                "source_of_truth": "profile",
                "owner_modules": ["app/services/villains"],
                "contracts": ["canonical contract"],
                "forbidden_patterns": ["DB writes outside canonical adapter"],
                "test_bindings": [{"id": "tests-villains", "label": "canonical"}],
                "public_entries": ["app/services/villains/__init__.py"],
                "lifecycle": {
                    "definition_version": "1.0",
                    "replace_snapshot_boundaries": True,
                    "persistence_migration": {
                        "affected_callers": ["supported compatibility export"]
                    },
                    "public_entry_semantics": {
                        "kind": "declared_public_entry",
                        "heuristic_entries": [
                            "app/services/villains/__init__.py",
                        ],
                    },
                },
            }
        ]
    }

    merged = router_core.merge_curated_records(
        existing,
        generated,
        "capabilities",
        "id",
    )
    capability = merged["capabilities"][0]

    assert capability["owner_modules"] == ["app/services/villains"]
    assert capability["public_entries"] == ["app/services/villains/__init__.py"]
    assert capability["contracts"] == ["canonical contract"]
    assert capability["forbidden_patterns"] == [
        "DB writes outside canonical adapter"
    ]
    assert capability["test_bindings"] == [
        {"id": "tests-villains", "label": "canonical"}
    ]
    assert capability["lifecycle"]["public_entry_semantics"] == {
        "kind": "declared_public_entry",
        "heuristic_entries": ["app/services/villains/__init__.py"],
    }
    assert capability["lifecycle"]["persistence_migration"][
        "affected_callers"
    ] == ["supported compatibility export"]


def test_profile_package_module_replaces_stale_same_id_file_module() -> None:
    existing = {
        "modules": [
            {
                "id": "module-narrative-state",
                "path": "app/services/narrative_state/core.py",
                "source_of_truth": "curated",
                "owner": "UNKNOWN",
            }
        ]
    }
    generated = {
        "modules": [
            {
                "id": "module-narrative-state",
                "path": "app/services/narrative_state",
                "source_of_truth": "profile",
                "owner": "narrative-state",
            }
        ]
    }

    merged = router_core.merge_curated_records(
        existing,
        generated,
        "modules",
        "path",
    )

    assert merged["modules"] == generated["modules"]


def test_active_canonical_root_uses_indexed_consumer_and_test_paths() -> None:
    capability = router_core.CapabilityEntry(
        id="narrative-state",
        name="Narrative State",
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="profile",
        owner_modules=["app/services/narrative_state"],
        lifecycle={"canonical_root": {"status": "active"}},
    )
    bundle = {
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "tests/narrative_state/**",
                    "capabilities": ["narrative-state"],
                }
            ]
        }
    }

    assert router_core.capability_path_proximity(
        capability,
        ["tests/narrative_state/test_repository_contract.py"],
        bundle,
    ) == 1.0


def test_capability_consumer_paths_are_indexed_without_becoming_owner_modules(
    tmp_path: Path,
) -> None:
    capability = router_core.CapabilityEntry(
        id="narrative-state",
        name="Narrative State",
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="profile",
        owner_modules=["app/services/narrative_state"],
        lifecycle={
            "consumer_path_patterns": [
                "app/api/project_postgres_app.py",
                "app/services/workflow/execution_state_writeback.py",
            ]
        },
    )

    path_map = router_core.build_path_to_capability_map(
        tmp_path,
        [capability],
        [],
    )
    consumer = next(
        item
        for item in path_map["path_index"]
        if item["path_pattern"] == "app/api/project_postgres_app.py"
    )

    assert consumer["capabilities"] == []
    assert consumer["consumer_capabilities"] == ["narrative-state"]
    assert consumer["sources"] == ["capability.consumer_path_patterns"]
    assert consumer["modules"] == []
    assert router_core.path_index_capabilities_for_path(
        {"path_to_capability_map": path_map},
        "app/api/project_postgres_app.py",
    ) == []
    assert router_core.path_index_evidence_capabilities_for_path(
        {"path_to_capability_map": path_map},
        "app/api/project_postgres_app.py",
    ) == ["narrative-state"]
    assert capability.owner_modules == ["app/services/narrative_state"]


def test_rebuild_preserves_curated_profile_extensions_by_default(
    tmp_path: Path,
) -> None:
    existing = {
        "capabilities": [
            {
                "id": "workflow-execution-adapter",
                "source_of_truth": "profile",
                "owner_modules": [
                    "app/services/workflow/execution.py",
                    "app/services/workflow/agent_capability_runtime_evidence.py",
                ],
                "public_entries": [
                    "app/services/workflow/execution.py",
                    "app/services/workflow/agent_capability_runtime_evidence.py",
                ],
                "contracts": ["preserve reviewed runtime evidence ownership"],
                "lifecycle": {
                    "public_entry_semantics": {
                        "kind": "declared_public_entry",
                        "heuristic_entries": ["existing-curated-entry"],
                    }
                },
            }
        ]
    }
    generated = {
        "capabilities": [
            {
                "id": "workflow-execution-adapter",
                "source_of_truth": "profile",
                "owner_modules": ["app/services/workflow/execution.py"],
                "public_entries": ["app/services/workflow/execution.py"],
                "contracts": ["preserve reviewed runtime evidence ownership"],
                "lifecycle": {
                    "definition_version": "1.0",
                    "public_entry_semantics": {
                        "kind": "declared_public_entry",
                        "heuristic_entries": ["generated-profile-entry"],
                    },
                },
            }
        ]
    }

    merged = router_core.merge_curated_records(
        existing,
        generated,
        "capabilities",
        "id",
    )
    capability = merged["capabilities"][0]

    assert capability["owner_modules"] == existing["capabilities"][0]["owner_modules"]
    assert capability["public_entries"] == existing["capabilities"][0]["public_entries"]
    assert capability["lifecycle"]["public_entry_semantics"]["heuristic_entries"] == [
        "existing-curated-entry",
        "generated-profile-entry",
    ]

    evidence_path = "app/services/workflow/agent_capability_runtime_evidence.py"
    evidence_file = tmp_path / evidence_path
    evidence_file.parent.mkdir(parents=True)
    evidence_file.write_text("class RuntimeEvidence:\n    pass\n", encoding="utf-8")
    path_map = router_core.build_path_to_capability_map(
        tmp_path,
        [
            router_core.CapabilityEntry(
                id="workflow-execution-adapter",
                name="Workflow Execution Adapter",
                status="stable",
                maturity="curated",
                stage="stable",
                source_of_truth="profile",
                owner_modules=capability["owner_modules"],
                public_entries=capability["public_entries"],
            )
        ],
        [
            router_core.ModuleEntry(
                id="module-workflow-agent-capability-runtime-evidence",
                path=evidence_path,
                layer="domain-service",
                domain="workflow-execution-adapter",
                purpose="Runtime evidence projection",
                generated=False,
            )
        ],
    )

    assert path_map["uncovered_modules"] == []
    assert path_map["lookup"][evidence_path] == ["workflow-execution-adapter"]


def test_rebuild_preserves_explicit_profile_module_without_discovery_replacement() -> None:
    existing = {
        "modules": [
            {
                "id": "module-provider-egress",
                "path": "app/services/provider_egress",
                "source_of_truth": "profile",
                "generated": False,
            }
        ]
    }

    merged = router_core.merge_curated_records(
        existing,
        {"modules": []},
        "modules",
        "path",
    )

    assert merged["modules"] == existing["modules"]

def test_single_changed_path_excludes_semantic_secondary_capability(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "secondary-capability-repo"
    (repo / ".git").mkdir(parents=True)
    for name in ("billing", "shipping"):
        package = repo / "services" / name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "service.py").write_text(
            f"def {name}_service():\n    return True\n",
            encoding="utf-8",
        )
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: composite-consistency
capabilities:
  - id: billing-core
    name: Billing Core
    status: stable
    stage: stable
    path_patterns: ["services/billing/**"]
    keywords: ["invoice", "coordination", "billing"]
    public_entries: ["services/billing/service.py"]
    extension_points: ["services/billing/service.py"]
  - id: shipping-core
    name: Shipping Core
    status: stable
    stage: stable
    path_patterns: ["services/shipping/**"]
    keywords: ["invoice", "coordination", "shipping"]
    public_entries: ["services/shipping/service.py"]
    extension_points: ["services/shipping/service.py"]
ownership_rules:
  - path_patterns: ["services/billing/**"]
    owner: billing-team
  - path_patterns: ["services/shipping/**"]
    owner: shipping-team
""".strip()
        + "\n",
        encoding="utf-8",
    )

    bundle = router_core.bootstrap_bundle(repo, write=True)
    bundle["change_rules"]["confidence"]["guarded_route_threshold"] = 0.5
    decision = router_core.resolve_request(
        "Modify invoice coordination behavior in the existing billing service",
        ["services/billing/service.py"],
        bundle,
        repo / "project-change-router",
        enforce_evaluation_policy=False,
    )

    assert decision.primary_capability == "billing-core"
    assert decision.secondary_capabilities == []
    assert decision.composite_route_required is False
    assert decision.composite_route["required"] is False
    assert [
        item["capability"] for item in decision.composite_route["participants"]
    ] == ["billing-core"]


def test_database_owner_converges_across_profile_and_generated_bundle(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "profile-repo"
    package = repo / "src" / "infrastructure" / "database"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "gateway.py").write_text(
        "class DatabaseGateway:\n    pass\n",
        encoding="utf-8",
    )
    profile = {
        "profile_id": "database-profile",
        "module_overrides": [
            {
                "id": "module-database-runtime",
                "path": "src/infrastructure/database",
                "path_patterns": ["src/infrastructure/database/**"],
                "layer": "infra",
                "domain": "database-runtime",
                "public_api": "__init__.py",
                "owner": "database-runtime",
                "status": "active",
                "nested_module_boundary": True,
                "allowed_outbound_to": ["migrations"],
                "import_names": ["src.infrastructure.database"],
            }
        ],
        "ownership_rules": [
            {
                "path_patterns": ["src/infrastructure/database/**"],
                "owner": "database-runtime",
            }
        ],
        "capability_ownership": [
            {
                "target": "database-runtime",
                "primary": "database-runtime",
                "reviewers": ["database-architecture-reviewers"],
            }
        ],
        "capabilities": [
            {
                "id": "database-runtime",
                "name": "Database Runtime",
                "status": "stable",
                "stage": "stable",
                "path_patterns": ["src/infrastructure/database/**"],
                "public_entries": ["src/infrastructure/database/__init__.py"],
                "lifecycle": {
                    "implementation_state": "active_infrastructure_debt_migrating"
                },
            }
        ],
    }

    modules = router_core.discover_modules(repo, profile=profile)
    capabilities, _ = router_core.apply_profile_capabilities(repo, modules, profile)
    ownership = router_core.build_ownership(
        capabilities, modules, "structured", profile
    )
    path_map = router_core.build_path_to_capability_map(
        repo,
        capabilities,
        modules,
        profile,
    )

    module_override = profile["module_overrides"][0]
    assert module_override["id"] == "module-database-runtime"
    assert module_override["owner"] == "database-runtime"
    assert module_override["status"] == "active"
    assert module_override["nested_module_boundary"] is True
    assert module_override["allowed_outbound_to"] == ["migrations"]

    profile_owner = next(
        item
        for item in profile["ownership_rules"]
        if "src/infrastructure/database/**" in item.get("path_patterns", [])
    )
    assert profile_owner["owner"] == "database-runtime"

    capability = next(
        item
        for item in capabilities
        if item.id == "database-runtime"
    )
    assert capability.source_of_truth == "profile"
    assert capability.lifecycle["implementation_state"] == (
        "active_infrastructure_debt_migrating"
    )

    module = next(
        item for item in modules if item.path == "src/infrastructure/database"
    )
    assert module.id == "module-database-runtime"
    assert module.source_of_truth == "profile"
    assert module.owner == "database-runtime"
    assert module.status == "active"
    assert module.lifecycle["nested_module_boundary"] is True
    assert module.lifecycle["declared_allowed_outbound_to"] == ["migrations"]

    module_owner = next(
        item
        for item in ownership["owners"]
        if item["scope"] == "module"
        and item["target"] == "src/infrastructure/database"
    )
    assert module_owner["primary"] == "database-runtime"
    assert module_owner["reviewers"] == ["database-architecture-reviewers"]
    assert module_owner["provisional"] is False

    capability_owner = next(
        item
        for item in ownership["owners"]
        if item["scope"] == "capability"
        and item["target"] == "database-runtime"
    )
    assert capability_owner["primary"] == "database-runtime"
    assert capability_owner["reviewers"] == [
        "database-architecture-reviewers"
    ]
    assert capability_owner["provisional"] is False

    path_owner = next(
        item
        for item in path_map["path_index"]
        if item["path_pattern"] == "src/infrastructure/database/**"
    )
    assert path_owner["capabilities"] == ["database-runtime"]
    assert path_owner["relationship"] == "unique"
    assert path_owner["modules"] == ["src/infrastructure/database"]

    business_module = router_core.ModuleEntry(
        id="module-orders-domain",
        path="src/domain/orders",
        layer="domain-service",
        domain="orders-domain",
        purpose="Forbidden database dependency target",
    )
    assert not router_core.matches_dependency(
        module,
        business_module,
        "src/domain/orders/service.py",
    )
