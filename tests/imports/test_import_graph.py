from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.import_graph import (
    build_import_graph,
    classify_findings_against_baseline,
    finding_fingerprint,
    validate_architecture_baseline,
)
import router_core


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_governance_accepts_only_declared_stable_top_level_owner_roots(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "scripts" / "audit.py", "print('audit')\n")
    _write(repo / "app" / "main.py", "print('app')\n")
    _write(
        repo / ".project-change-router.yaml",
        """
ownership_rules:
  - path_patterns: ["scripts/**"]
    owner: development-infrastructure
  - path_patterns: ["app/**"]
    owner: app-core
capabilities:
  - id: development-infrastructure
    path_patterns: ["scripts/**"]
    status: stable
    stage: stable
    contracts: [scope, boundary, cross-capability, risk]
  - id: app-core
    path_patterns: ["app/main.py"]
    status: stable
    stage: stable
    contracts: [scope, boundary, cross-capability, risk]
module_overrides:
  - path_patterns: ["scripts/**"]
    layer: infra
""".strip()
        + "\n",
    )
    report = router_core.audit_bundle_governance(repo, router_core.build_router_bundle(repo))
    broad = next(item for item in report["findings"] if item["rule"] == "ownership-rule-too-broad")

    assert "scripts/**" not in broad["details"]["patterns"]
    assert "app/**" in broad["details"]["patterns"]


def test_python_graph_resolves_service_to_api_and_runtime_cycle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(repo / "app" / "__init__.py", ""),
        _write(repo / "app" / "api" / "routes" / "__init__.py", ""),
        _write(repo / "app" / "api" / "routes" / "plots.py", "VALUE = 1\n"),
        _write(repo / "app" / "services" / "__init__.py", ""),
        _write(repo / "app" / "services" / "plots" / "__init__.py", ""),
        _write(
            repo / "app" / "services" / "plots" / "postgres_service.py",
            "from app.api.routes import plots as plot_routes\n",
        ),
        _write(repo / "app" / "cycle" / "__init__.py", ""),
        _write(repo / "app" / "cycle" / "a.py", "from . import b\n"),
        _write(repo / "app" / "cycle" / "b.py", "from . import a\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert any(
        edge.source == "app/services/plots/postgres_service.py"
        and edge.target == "app/api/routes/plots.py"
        and edge.language == "python"
        and edge.runtime
        for edge in snapshot.edges
    )
    assert any(
        cycle.language == "python"
        and cycle.runtime
        and cycle.members == ("app/cycle/a.py", "app/cycle/b.py")
        for cycle in snapshot.cycles
    )


def test_typescript_graph_separates_type_only_cycles_and_ignores_css(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(repo / "src" / "types-a.ts", "import type { B } from './types-b'\nexport type A = B\n"),
        _write(repo / "src" / "types-b.ts", "import type { A } from './types-a'\nexport type B = A\n"),
        _write(repo / "src" / "runtime-a.ts", "import { b } from './runtime-b'\nexport const a = b\n"),
        _write(repo / "src" / "runtime-b.ts", "import { a } from './runtime-a'\nexport const b = a\n"),
        _write(repo / "src" / "Panel.tsx", "import './Panel.css'\nexport const Panel = () => null\n"),
        _write(repo / "src" / "Panel.css", ".panel {}\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert any(
        not edge.runtime
        and edge.source == "src/types-a.ts"
        and edge.target == "src/types-b.ts"
        for edge in snapshot.edges
    )
    assert any(
        cycle.members == ("src/runtime-a.ts", "src/runtime-b.ts") and cycle.runtime
        for cycle in snapshot.cycles
    )
    assert any(
        cycle.members == ("src/types-a.ts", "src/types-b.ts") and not cycle.runtime
        for cycle in snapshot.cycles
    )
    assert not any(edge.source == edge.target == "src/Panel.tsx" for edge in snapshot.edges)


def test_exact_baseline_does_not_hide_changed_dependency() -> None:
    finding = {
        "severity": "P1",
        "rule": "dependency-direction",
        "source": "app/services/plots/postgres_service.py",
        "target": "app/api/routes/plots.py",
    }
    baseline = [
        {
            "id": "DEP-001-plots-api",
            "rule": "dependency-direction",
            "source": "app/services/plots/postgres_service.py",
            "target": "app/api/routes/plots.py",
            "owner": "outline-planning",
            "exit_stage": "G4",
            "fingerprint": finding_fingerprint(finding),
        }
    ]

    existing = classify_findings_against_baseline([finding], baseline)
    changed = classify_findings_against_baseline(
        [{**finding, "target": "app/api/routes/workflows.py"}],
        baseline,
    )

    assert existing == [
        {
            **finding,
            "baseline_status": "existing_debt",
            "baseline_id": "DEP-001-plots-api",
            "owner": "outline-planning",
            "exit_stage": "G4",
            "blocking": False,
        }
    ]
    assert changed[0]["baseline_status"] == "new"
    assert changed[0]["baseline_id"] is None
    assert changed[0]["blocking"] is True


def test_change_rules_carry_exact_profile_architecture_baseline() -> None:
    finding = {"rule": "public-export-count", "module": "app.shared", "count": 2}
    baseline = {
        "id": "PUBLIC-001-shared",
        **finding,
        "owner": "shared-agent-runtime",
        "exit_stage": "G4",
        "fingerprint": finding_fingerprint(finding),
    }

    rules = router_core.build_change_rules([], {"guardrails": {"architecture_baseline": [baseline]}}, "structured")

    assert rules["architecture_baseline"] == [baseline]


def test_rebuild_preserves_curated_change_rules(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "auth" / "service.py", "print('auth')\n")
    router_core.bootstrap_bundle(repo, write=True)
    bundle_root = repo / "project-change-router"
    existing = router_core.load_bundle(bundle_root)
    custom_rule = {"name": "curated-route", "when": {"capability_id": "app"}, "action": "review"}
    existing["change_rules"]["route_rules"].append(custom_rule)
    existing["change_rules"]["high_risk_capability_ids"] = ["curated-only"]
    existing["exception_registry"]["exceptions"] = [{"id": "curated-exception"}]
    router_core.write_bundle(bundle_root, existing)

    rebuilt = router_core.build_router_bundle(repo)

    assert custom_rule in rebuilt["change_rules"]["route_rules"]
    assert rebuilt["change_rules"]["high_risk_capability_ids"] == ["curated-only"]
    assert rebuilt["exception_registry"] == existing["exception_registry"]


def test_yaml_writer_rewrites_semantically_equal_text_canonically(tmp_path: Path) -> None:
    path = tmp_path / "curated.yaml"
    original = "items: [one, two]\n"
    path.write_text(original, encoding="utf-8")

    router_core.dump_yaml_file(path, {"items": ["one", "two"]})

    canonical = "items:\n- one\n- two\n"
    assert path.read_text(encoding="utf-8") == canonical

    router_core.dump_yaml_file(path, {"items": ["one", "two"]})

    assert path.read_text(encoding="utf-8") == canonical


def test_yaml_writer_rewrites_crlf_to_canonical_utf8_bytes(tmp_path: Path) -> None:
    path = tmp_path / "curated.yaml"
    path.write_bytes(b"items:\r\n- one\r\n- two\r\n")

    router_core.dump_yaml_file(path, {"items": ["one", "two"]})

    assert path.read_bytes() == b"items:\n- one\n- two\n"


def test_rebuild_missing_paths_excludes_only_planned_modules(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "app.py", "print('app')\n")
    router_core.bootstrap_bundle(repo, write=True)
    bundle_root = repo / "project-change-router"
    existing = router_core.load_bundle(bundle_root)
    for path, status in (("planned/runtime", "planned"), ("active/runtime", "active")):
        existing["module_map"]["modules"].append(
            router_core.ModuleEntry(
                id=f"module-{status}",
                path=path,
                layer="shared-capability",
                domain=f"{status}-runtime",
                purpose=f"{status} runtime",
                source_of_truth="curated",
                generated=False,
                status=status,
            ).to_dict()
        )
    router_core.write_bundle(bundle_root, existing)

    report = router_core.rebuild_index(repo, write_back=False)

    assert "planned/runtime" not in report["missing_paths"]
    assert "active/runtime" in report["missing_paths"]


def test_write_back_rebuild_does_not_attest_weak_evaluation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "app.py", "print('app')\n")
    _write(
        repo / ".project-change-router.yaml",
        """
evaluation:
  mode: curated
  enforcement_enabled: true
  top1_accuracy_threshold: 0
  review_precision_threshold: 0
  minimum_capability_coverage_ratio: 0
  minimum_case_count: 1
  cases:
    - id: app-route
      request: Review a change to the application entry point.
      expected_action: review
      expected_capabilities: []
      expected_modules: []
      expected_reads: []
      changed_paths: ["app.py"]
      risk_level: medium
""".strip()
        + "\n",
    )

    router_core.rebuild_index(repo, write_back=True)
    rebuilt = router_core.load_bundle(repo / "project-change-router")

    assert "attestation" not in rebuilt["config"]["evaluation"]
    assert router_core.policy_for_bundle(rebuilt).passed is False


def test_review_intent_distinguishes_domain_history_and_owner_duplication() -> None:
    assert not router_core.request_requires_review("Extend OOC review history count readback from stored state")
    assert not router_core.request_duplicates_existing_owner("Apply supplied saved and duplicate skip markers")
    assert router_core.request_duplicates_existing_owner(
        "Add a duplicate local memory selector and independent cache instead of reusing memory-core"
    )
    assert router_core.request_duplicates_existing_owner(
        "Create a Memory Repository under app repositories as a second formal repository root"
    )


def test_stable_capability_ownership_requires_explicit_profile_record() -> None:
    module = router_core.ModuleEntry(
        id="module-runtime", path="app/runtime", layer="shared-capability", domain="runtime", purpose="Runtime"
    )
    capability = router_core.CapabilityEntry(
        id="runtime", name="Runtime", status="stable", maturity="curated", owner_modules=[module.path]
    )

    owners = router_core.build_ownership([capability], [module], "structured")["owners"]
    capability_owner = next(item for item in owners if item["scope"] == "capability")
    module_owner = next(item for item in owners if item["scope"] == "module")

    assert capability_owner["primary"] == module_owner["primary"] == "unassigned"
    assert capability_owner["reviewers"] == module_owner["reviewers"] == []
    assert capability_owner["provisional"] and module_owner["provisional"]


def test_curated_capability_merge_adds_lifecycle_metadata_without_verified_claim() -> None:
    existing = {
        "capabilities": [
            router_core.CapabilityEntry(
                id="runtime", name="Runtime", status="stable", maturity="curated", stage="stable", source_of_truth="curated"
            ).to_dict()
        ]
    }

    merged = router_core.merge_curated_records(existing, {"capabilities": []}, "capabilities", "id")
    lifecycle = merged["capabilities"][0]["lifecycle"]

    assert lifecycle["definition_version"] == "1.0"
    assert lifecycle["status"] == lifecycle["stage"] == "stable"
    assert "verified" not in str(lifecycle).lower()


def test_profile_backed_capability_overlays_stale_same_id_curated_snapshot() -> None:
    existing = {
        "capabilities": [
            router_core.CapabilityEntry(
                id="api-facade",
                name="API Facade",
                status="stable",
                maturity="curated",
                stage="stable",
                source_of_truth="curated",
                intent_keywords=["stale API keyword"],
            ).to_dict(),
            router_core.CapabilityEntry(
                id="manual-only",
                name="Manual Only",
                status="stable",
                maturity="curated",
                stage="stable",
                source_of_truth="curated",
                intent_keywords=["preserve manual capability"],
            ).to_dict(),
        ]
    }
    generated = {
        "capabilities": [
            router_core.CapabilityEntry(
                id="api-facade",
                name="API Facade",
                status="stable",
                maturity="curated",
                stage="stable",
                source_of_truth="profile",
                intent_keywords=["canonical route installer"],
            ).to_dict()
        ]
    }

    merged = router_core.merge_curated_records(existing, generated, "capabilities", "id")
    by_id = {item["id"]: item for item in merged["capabilities"]}

    assert "canonical route installer" in by_id["api-facade"]["intent_keywords"]
    assert "stale API keyword" in by_id["api-facade"]["intent_keywords"]
    assert by_id["api-facade"]["source_of_truth"] == "profile"
    assert by_id["manual-only"]["intent_keywords"] == ["preserve manual capability"]


def test_cycle_baseline_requires_exact_members() -> None:
    finding = {
        "severity": "P1",
        "rule": "runtime-cycle",
        "language": "python",
        "members": ["app/a.py", "app/b.py"],
    }
    baseline = [
        {
            "id": "DEP-001-cycle",
            "rule": "runtime-cycle",
            "language": "python",
            "members": ["app/a.py", "app/b.py"],
            "owner": "shared-agent-runtime",
            "exit_stage": "G4",
            "fingerprint": finding_fingerprint(finding),
        }
    ]

    existing = classify_findings_against_baseline([finding], baseline)
    expanded = classify_findings_against_baseline(
        [{**finding, "members": ["app/a.py", "app/b.py", "app/c.py"]}],
        baseline,
    )

    assert existing[0]["baseline_status"] == "existing_debt"
    assert existing[0]["blocking"] is False
    assert expanded[0]["baseline_status"] == "new"
    assert expanded[0]["blocking"] is True


def test_dependency_guard_reports_exact_baseline_and_intra_module_cycle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "app" / "__init__.py", "")
    _write(repo / "app" / "api" / "__init__.py", "")
    _write(repo / "app" / "api" / "routes" / "__init__.py", "")
    _write(repo / "app" / "api" / "routes" / "plots.py", "VALUE = 1\n")
    _write(repo / "app" / "shared" / "__init__.py", "")
    _write(repo / "app" / "shared" / "helper.py", "VALUE = 2\n")
    _write(repo / "app" / "services" / "plots" / "__init__.py", "")
    _write(
        repo / "app" / "services" / "plots" / "postgres_service.py",
        "from app.api.routes import plots as plot_routes\n"
        "from app.shared.helper import VALUE\n"
        "from . import cycle_a\n",
    )
    _write(repo / "app" / "services" / "plots" / "cycle_a.py", "from . import cycle_b\n")
    _write(repo / "app" / "services" / "plots" / "cycle_b.py", "from . import cycle_a\n")
    bundle = {
        "config": {"ignore_paths": []},
        "module_map": {
            "modules": [
                {
                    "id": "module-api",
                    "path": "app/api",
                    "layer": "adapter",
                    "domain": "api-facade",
                    "purpose": "HTTP facade",
                    "owner": "api-facade",
                },
                {
                    "id": "module-plots",
                    "path": "app/services/plots",
                    "layer": "domain-service",
                    "domain": "outline-planning",
                    "purpose": "Plot persistence",
                    "owner": "outline-planning",
                },
            ]
        },
        "change_rules": {
            "architecture_baseline": [
                {
                    "id": "DEP-001-plots-api",
                    "rule": "dependency-direction",
                    "source": "app/services/plots/postgres_service.py",
                    "target": "app/api/routes/plots.py",
                    "owner": "outline-planning",
                    "exit_stage": "G4",
                    "fingerprint": finding_fingerprint(
                        {
                            "rule": "dependency-direction",
                            "source": "app/services/plots/postgres_service.py",
                            "target": "app/api/routes/plots.py",
                        }
                    ),
                }
            ]
        },
    }

    findings = router_core.gather_dependency_findings(repo, bundle)
    dependency = next(item for item in findings if item["rule"] == "dependency-direction")
    cycle = next(item for item in findings if item["rule"] == "runtime-cycle")

    assert dependency["baseline_status"] == "existing_debt"
    assert dependency["blocking"] is False
    assert cycle["members"] == [
        "app/services/plots/cycle_a.py",
        "app/services/plots/cycle_b.py",
    ]
    assert cycle["baseline_status"] == "new"
    assert cycle["blocking"] is True
    assert not [item for item in findings if item["rule"] == "import-graph-diagnostic"]


def test_partial_duplicate_unknown_and_orphan_baselines_are_rejected() -> None:
    finding = {
        "severity": "P1",
        "rule": "dependency-direction",
        "source": "app/services/plots/postgres_service.py",
        "target": "app/api/routes/plots.py",
    }
    fingerprint = finding_fingerprint(finding)
    valid = {
        "id": "DEP-001-plots-api",
        "rule": "dependency-direction",
        "source": finding["source"],
        "target": finding["target"],
        "owner": "outline-planning",
        "exit_stage": "G4",
        "fingerprint": fingerprint,
    }

    partial = {"id": "bad", "rule": "dependency-direction"}
    unknown_owner = {**valid, "id": "unknown", "owner": "UNKNOWN"}
    duplicate = [valid, {**valid}]
    orphan = {**valid, "id": "orphan", "fingerprint": "0" * 64}

    classified = classify_findings_against_baseline([finding], [partial])
    assert classified[0]["baseline_status"] == "new"
    assert classified[0]["blocking"] is True

    partial_errors = validate_architecture_baseline([partial], [finding])
    unknown_errors = validate_architecture_baseline([unknown_owner], [finding])
    duplicate_errors = validate_architecture_baseline(duplicate, [finding])
    orphan_errors = validate_architecture_baseline([orphan], [finding])

    assert {item["code"] for item in partial_errors} >= {
        "baseline_missing_identity",
        "baseline_missing_owner",
        "baseline_missing_exit_stage",
        "baseline_missing_fingerprint",
    }
    assert "baseline_unknown_owner" in {item["code"] for item in unknown_errors}
    assert "baseline_duplicate_id" in {item["code"] for item in duplicate_errors}
    assert "baseline_duplicate_fingerprint" in {item["code"] for item in duplicate_errors}
    assert "baseline_orphan" in {item["code"] for item in orphan_errors}


def test_python_public_exports_imported_symbols_and_growth_are_visible(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_file = _write(
        repo / "app" / "shared" / "__init__.py",
        "from .public import PublicThing\n__all__ = ['PublicThing', 'StablePort']\n",
    )
    public_file = _write(repo / "app" / "shared" / "public.py", "class PublicThing: pass\nStablePort = object\n")
    consumer = _write(
        repo / "app" / "feature.py",
        "from app.shared import PublicThing, StablePort\n",
    )

    snapshot = build_import_graph(repo, [init_file, public_file, consumer])

    assert {(item.source, item.symbol) for item in snapshot.exports} == {
        ("app/shared/__init__.py", "PublicThing"),
        ("app/shared/__init__.py", "StablePort"),
    }
    edge = next(item for item in snapshot.edges if item.source == "app/feature.py")
    assert edge.imported_symbols == ("PublicThing", "StablePort")

    baseline_finding = {
        "severity": "P1",
        "rule": "public-export-count",
        "module": "app.shared",
        "count": 2,
    }
    baseline = [
        {
            "id": "PUBLIC-001-shared",
            "rule": "public-export-count",
            "module": "app.shared",
            "count": 2,
            "owner": "shared-agent-runtime",
            "exit_stage": "G4",
            "fingerprint": finding_fingerprint(baseline_finding),
        }
    ]
    existing = classify_findings_against_baseline([baseline_finding], baseline)
    growth = classify_findings_against_baseline([{**baseline_finding, "count": 3}], baseline)
    assert existing[0]["blocking"] is False
    assert growth[0]["baseline_status"] == "new"
    assert growth[0]["blocking"] is True


def test_python_type_checking_and_parse_diagnostics_are_not_silent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(repo / "app" / "__init__.py", ""),
        _write(repo / "app" / "types.py", "class OnlyType: pass\n"),
        _write(
            repo / "app" / "consumer.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from .types import OnlyType\n"
            "def run():\n"
            "    from .runtime import execute\n"
            "    return execute()\n",
        ),
        _write(repo / "app" / "runtime.py", "def execute(): return True\n"),
        _write(repo / "app" / "broken.py", "def broken(:\n"),
        _write(repo / "app" / "missing_consumer.py", "from .missing import value\n"),
    ]

    snapshot = build_import_graph(repo, files)

    type_edge = next(item for item in snapshot.edges if item.target == "app/types.py")
    runtime_edge = next(item for item in snapshot.edges if item.target == "app/runtime.py")
    assert type_edge.runtime is False
    assert runtime_edge.runtime is True
    assert {item.code for item in snapshot.diagnostics} >= {
        "python-parse-error",
        "unresolved-local-import",
    }
    assert all(item.blocking for item in snapshot.diagnostics)


def test_synthetic_repository_import_facts_are_detected_before_baseline(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    python_files = [
        _write(repo / "pkg" / "__init__.py", ""),
        _write(repo / "pkg" / "api" / "__init__.py", ""),
        _write(repo / "pkg" / "api" / "routes.py", "VALUE = 1\n"),
        _write(repo / "pkg" / "services" / "__init__.py", ""),
        _write(
            repo / "pkg" / "services" / "repository.py",
            "from pkg.api import routes\n",
        ),
        _write(repo / "pkg" / "cycle" / "__init__.py", ""),
        _write(repo / "pkg" / "cycle" / "left.py", "from . import right\n"),
        _write(repo / "pkg" / "cycle" / "right.py", "from . import left\n"),
    ]
    frontend_files = [
        _write(
            repo / "web" / "model-a.ts",
            "import type { ModelB } from './model-b'\nexport type ModelA = ModelB\n",
        ),
        _write(
            repo / "web" / "model-b.ts",
            "import type { ModelA } from './model-a'\nexport type ModelB = ModelA\n",
        ),
        _write(
            repo / "web" / "entry.ts",
            "import { render } from './render'\nrender()\n",
        ),
        _write(repo / "web" / "render.ts", "export const render = () => true\n"),
    ]

    python_snapshot = build_import_graph(repo, python_files)
    frontend_snapshot = build_import_graph(repo, frontend_files)

    assert any(
        edge.source == "pkg/services/repository.py"
        and edge.target == "pkg/api/routes.py"
        for edge in python_snapshot.edges
    )
    assert (
        "pkg/cycle/left.py",
        "pkg/cycle/right.py",
    ) in {cycle.members for cycle in python_snapshot.cycles if cycle.runtime}
    assert not [cycle for cycle in frontend_snapshot.cycles if cycle.runtime]
    assert {
        cycle.members for cycle in frontend_snapshot.cycles if not cycle.runtime
    } == {("web/model-a.ts", "web/model-b.ts")}


def test_public_guard_reports_export_baseline_private_bypass_and_growth(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "app" / "shared" / "__init__.py", "__all__ = ['PublicThing', 'StablePort']\n")
    _write(repo / "app" / "shared" / "internal" / "__init__.py", "")
    _write(repo / "app" / "shared" / "internal" / "secret.py", "SECRET = 'x'\n")
    _write(
        repo / "app" / "feature" / "use_shared.py",
        "from app.shared.internal.secret import SECRET\n",
    )
    export_finding = {
        "rule": "public-export-count",
        "module": "app.shared",
        "count": 2,
    }
    bundle = {
        "config": {"ignore_paths": []},
        "module_map": {
            "modules": [
                {
                    "id": "module-shared",
                    "path": "app/shared",
                    "layer": "shared-capability",
                    "domain": "shared-agent-runtime",
                    "purpose": "Shared runtime",
                    "public_api": "__init__.py",
                    "owner": "shared-agent-runtime",
                },
                {
                    "id": "module-feature",
                    "path": "app/feature",
                    "layer": "domain-service",
                    "domain": "feature",
                    "purpose": "Feature consumer",
                    "owner": "feature",
                    "depends_on": ["app/shared"],
                },
            ]
        },
        "change_rules": {
            "architecture_baseline": [
                {
                    "id": "PUBLIC-001-shared-export-count",
                    **export_finding,
                    "owner": "shared-agent-runtime",
                    "exit_stage": "G4",
                    "fingerprint": finding_fingerprint(export_finding),
                }
            ]
        },
    }

    findings = router_core.gather_public_api_findings(repo, bundle)
    export_count = next(item for item in findings if item["rule"] == "public-export-count")
    bypass = next(item for item in findings if item["rule"] == "public-api-bypass")

    assert export_count["count"] == 2
    assert export_count["baseline_status"] == "existing_debt"
    assert export_count["blocking"] is False
    assert bypass["source"] == "app/feature/use_shared.py"
    assert bypass["target"] == "app/shared/internal/secret.py"
    assert bypass["baseline_status"] == "new"
    assert bypass["blocking"] is True

    _write(
        repo / "app" / "shared" / "__init__.py",
        "__all__ = ['PublicThing', 'StablePort', 'NewExport']\n",
    )
    grown = router_core.gather_public_api_findings(repo, bundle)
    grown_count = next(item for item in grown if item["rule"] == "public-export-count")
    assert grown_count["count"] == 3
    assert grown_count["baseline_status"] == "new"
    assert grown_count["blocking"] is True
