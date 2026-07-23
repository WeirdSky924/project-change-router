from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import reuse_runtime
import router_core


def reuse_scope_fixture(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "scoped-reuse-repo"
    (repo / "app" / "workflow").mkdir(parents=True)
    (repo / "app" / "billing").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    for index in range(3):
        (repo / "app" / "workflow" / f"worker_{index}.py").write_text(
            f"def execute_workflow_{index}(payload):\n    return payload.get('value', {index})\n",
            encoding="utf-8",
        )
        (repo / "app" / "billing" / f"invoice_{index}.py").write_text(
            f"def create_invoice_{index}(amount):\n    return amount + {index}\n",
            encoding="utf-8",
        )
    test_path = repo / "tests" / "test_workflow_execution.py"
    test_path.write_text(
        "def test_workflow_execution(payload):\n    return payload.get('value', 0)\n",
        encoding="utf-8",
    )
    modules = [
        router_core.ModuleEntry("workflow-module", "app/workflow", "domain-service", "workflow", "Workflow"),
        router_core.ModuleEntry("billing-module", "app/billing", "domain-service", "billing", "Billing"),
    ]
    capabilities = [
        router_core.CapabilityEntry(
            "workflow",
            "Workflow",
            "stable",
            "stable",
            stage="stable",
            owner_modules=["app/workflow"],
            related_tests=["tests/test_workflow_execution.py"],
        ),
        router_core.CapabilityEntry(
            "billing",
            "Billing",
            "stable",
            "stable",
            stage="stable",
            owner_modules=["app/billing"],
        ),
    ]
    bundle = {
        "config": {"generated_at": "2026-01-01T00:00:00Z", "ignore_paths": []},
        "change_rules": {"reuse_scan_budget": {"max_comparisons": 100}},
        "module_map": {"modules": [module.to_dict() for module in modules]},
        "capability_catalog": {"capabilities": [capability.to_dict() for capability in capabilities]},
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "tests/test_workflow_execution.py",
                    "capabilities": ["workflow"],
                },
                {
                    "path_pattern": "**",
                    "capabilities": ["billing"],
                },
            ]
        },
    }
    return repo, bundle


def test_reuse_scan_changed_test_path_does_not_fallback_to_full_scan(tmp_path: Path) -> None:
    repo = tmp_path / "reuse-scan-repo"
    (repo / "app" / "services").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    for index in range(12):
        (repo / "app" / "services" / f"service_{index}.py").write_text(
            f"def service_{index}():\n    return {index}\n",
            encoding="utf-8",
        )
    (repo / "tests" / "test_workflow_execution.py").write_text(
        "def test_workflow_execution():\n    assert True\n",
        encoding="utf-8",
    )
    module = router_core.ModuleEntry(
        id="module-app-services",
        path="app/services",
        layer="domain-service",
        domain="app-services",
        purpose="Application services",
    )
    capability = router_core.CapabilityEntry(
        id="app-services",
        name="Application Services",
        status="stable",
        maturity="stable",
        stage="stable",
        owner_modules=["app/services"],
        public_entries=["app/services"],
        related_tests=["tests/test_workflow_execution.py"],
    )
    bundle = {
        "config": {"generated_at": "2026-01-01T00:00:00Z", "ignore_paths": []},
        "change_rules": {"reuse_scan_budget": {"max_comparisons": 100}},
        "module_map": {"modules": [module.to_dict()]},
        "capability_catalog": {"capabilities": [capability.to_dict()]},
    }
    report = router_core.gather_reuse_report(repo, bundle, ["tests/test_workflow_execution.py"])

    assert report["scan"]["candidate_file_count"] == 1
    assert report["scan"]["candidate_examples"] == ["tests/test_workflow_execution.py"]
    assert report["scan"]["raw_pair_count"] == 12
    assert report["scan"]["scope"]["capability_ids"] == ["app-services"]
    assert report["scan"]["completion_status"] == "complete"


def test_reuse_scan_limits_owner_files_to_resolved_capability(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)

    report = router_core.gather_reuse_report(repo, bundle, ["tests/test_workflow_execution.py"])

    assert report["scan"]["scope"]["direct_capability_ids"] == ["workflow"]
    assert report["scan"]["scope"]["ignored_broad_mappings"] == [
        {
            "path": "tests/test_workflow_execution.py",
            "path_pattern": "**",
            "capabilities": ["billing"],
        }
    ]
    assert report["scan"]["capabilities_scanned"] == 1
    assert report["scan"]["capabilities_skipped_by_scope"] == 1
    assert report["scan"]["owner_file_count"] == 4
    assert report["scan"]["raw_pair_count"] == 3


def test_reuse_scan_unknown_path_returns_incomplete_without_repo_scan(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    unknown = repo / "tests" / "test_unmapped_feature.py"
    unknown.write_text("def test_unmapped():\n    assert True\n", encoding="utf-8")

    report = router_core.gather_reuse_report(repo, bundle, ["tests/test_unmapped_feature.py"])

    assert report["scan"]["scope"]["status"] == "unresolved"
    assert report["scan"]["raw_pair_count"] == 0
    assert report["scan"]["completion_status"] == "incomplete"
    assert any(finding["rule"] == "reuse-scan-scope-unresolved" for finding in report["findings"])


def test_reuse_scan_persistent_fingerprint_cache_is_reused(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    runtime_root = tmp_path / "runtime"
    options = {
        "runtime_root": str(runtime_root),
        "run_id": "first",
        "cache_mode": "auto",
        "soft_timeout_seconds": 10,
        "checkpoint_interval_seconds": 0.1,
    }

    first = router_core.gather_reuse_report(
        repo, bundle, ["tests/test_workflow_execution.py"], runtime_options=options
    )
    options["run_id"] = "second"
    second = router_core.gather_reuse_report(
        repo, bundle, ["tests/test_workflow_execution.py"], runtime_options=options
    )

    assert first["scan"]["fingerprint_cache_misses"] > 0
    assert first["scan"]["fingerprints_written"] > 0
    assert second["scan"]["fingerprint_cache_hits"] == first["scan"]["fingerprint_cache_misses"]
    assert second["scan"]["fingerprint_cache_misses"] == 0


def test_reuse_scan_soft_timeout_emits_incomplete_evidence(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)

    report = router_core.gather_reuse_report(
        repo,
        bundle,
        ["tests/test_workflow_execution.py"],
        runtime_options={"soft_timeout_seconds": 0.000001},
    )

    assert report["scan"]["completion_status"] == "timeout"
    assert report["scan"]["termination_reason"] == "soft_timeout"
    assert report["scan"]["evidence_complete"] is False
    assert any(finding["rule"] == "reuse-scan-incomplete" for finding in report["findings"])


def test_reuse_scan_reports_large_file_fingerprint_candidate_without_exact_match(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    candidate_text = (repo / "tests" / "test_workflow_execution.py").read_text(encoding="utf-8")
    (repo / "app" / "workflow" / "worker_0.py").write_text(candidate_text, encoding="utf-8")

    report = router_core.gather_reuse_report(
        repo,
        bundle,
        ["tests/test_workflow_execution.py"],
        budget_overrides={"max_file_bytes_for_full_similarity": 10},
    )

    candidates = [
        finding for finding in report["findings"] if finding["rule"] == "duplicate-fingerprint-candidate"
    ]
    assert candidates
    assert candidates[0]["fingerprint_score"] >= 0.55
    assert report["scan"]["comparisons_run"] == 0
    assert report["scan"]["completion_status"] == "bounded"


def test_reuse_scan_top_k_truncation_is_bounded_evidence(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    candidate = repo / "tests" / "test_workflow_execution.py"
    (repo / "app" / "workflow" / "worker_0.py").write_text(
        candidate.read_text(encoding="utf-8"), encoding="utf-8"
    )

    report = router_core.gather_reuse_report(
        repo,
        bundle,
        ["tests/test_workflow_execution.py"],
        budget_overrides={"top_k_owner_files_per_candidate": 0},
    )

    assert report["scan"]["comparisons_skipped_by_top_k"] > 0
    assert report["scan"]["completion_status"] == "bounded"
    assert report["scan"]["evidence_complete"] is False


def test_reuse_scan_stale_path_map_capability_is_incomplete(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    bundle["capability_catalog"]["capabilities"][0]["related_tests"] = []
    bundle["path_to_capability_map"]["path_index"] = [
        {
            "path_pattern": "tests/test_workflow_execution.py",
            "capabilities": ["deleted-capability"],
        }
    ]

    report = router_core.gather_reuse_report(
        repo, bundle, ["tests/test_workflow_execution.py"]
    )

    assert report["scan"]["capabilities_scanned"] == 0
    assert report["scan"]["completion_status"] == "incomplete"
    assert report["scan"]["evidence_complete"] is False
    diagnostics = report["scan"]["scope"]["diagnostics"]
    assert any(item.get("code") == "unknown-scope-capability" for item in diagnostics)


def test_reuse_scan_preserves_root_dotfile_path_identity(tmp_path: Path) -> None:
    repo = tmp_path / "dotfile-scope-repo"
    repo.mkdir()
    (repo / ".router.py").write_text("ROUTES = {}\n", encoding="utf-8")
    module = router_core.ModuleEntry(
        "module-root", ".", "shared-capability", "routing", "Root routing metadata"
    )
    capability = router_core.CapabilityEntry(
        "routing-governance",
        "Routing Governance",
        "stable",
        "stable",
        stage="stable",
        owner_modules=["."],
        public_entries=[".router.py"],
    )
    bundle = {
        "config": {"ignore_paths": []},
        "change_rules": {},
        "module_map": {"modules": [module.to_dict()]},
        "capability_catalog": {"capabilities": [capability.to_dict()]},
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": ".router.py",
                    "capabilities": ["routing-governance"],
                }
            ]
        },
    }

    report = router_core.gather_reuse_report(repo, bundle, [".router.py"])

    assert report["scan"]["candidate_examples"] == [".router.py"]
    assert report["scan"]["scope"]["direct_capability_ids"] == [
        "routing-governance"
    ]
    assert report["scan"]["completion_status"] == "complete"


def test_reuse_scan_preserves_leading_dot_directory_path_identity(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "dot-directory-scope-repo"
    changed_path = ".claude/skills/project-change-router/scripts/router_core.py"
    source = repo / changed_path
    source.parent.mkdir(parents=True)
    source.write_text("ROUTES = {}\n", encoding="utf-8")
    module = router_core.ModuleEntry(
        "module-router-skill",
        ".claude/skills/project-change-router",
        "shared-capability",
        "routing",
        "Vendored routing skill",
    )
    capability = router_core.CapabilityEntry(
        "routing-governance",
        "Routing Governance",
        "stable",
        "stable",
        stage="stable",
        owner_modules=[".claude/skills/project-change-router"],
        public_entries=[changed_path],
    )
    bundle = {
        "config": {"ignore_paths": []},
        "change_rules": {},
        "module_map": {"modules": [module.to_dict()]},
        "capability_catalog": {"capabilities": [capability.to_dict()]},
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": changed_path,
                    "capabilities": ["routing-governance"],
                }
            ]
        },
    }

    report = router_core.gather_reuse_report(repo, bundle, [changed_path])

    assert report["scan"]["candidate_examples"] == [changed_path]
    assert report["scan"]["scope"]["direct_capability_ids"] == [
        "routing-governance"
    ]
    assert report["scan"]["scope"]["unresolved_paths"] == []
    assert report["scan"]["completion_status"] == "complete"


def test_runtime_store_deduplicates_canonical_reports_and_cleans_diagnostics(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime-store"
    canonical = {
        "run_id": "run-one",
        "result_status": "pass",
        "completion_status": "complete",
        "findings": [],
    }
    semantic = {"result_status": "pass", "findings": []}
    with reuse_runtime.ReuseRuntimeStore(runtime_root) as store:
        first = store.persist_report("canonical", canonical, semantic)
        canonical["run_id"] = "run-two"
        second = store.persist_report("canonical", canonical, semantic)
        diagnostic = store.persist_report(
            "diagnostic",
            {"run_id": "diag", "result_status": "warn", "completion_status": "bounded"},
        )
        policy = reuse_runtime.ReuseRetentionPolicy(diagnostic_max_count=0)
        removed = store.cleanup(tmp_path, policy)

    assert first.deduplicated is False
    assert second.deduplicated is True
    assert second.occurrence_count == 2
    assert first.path == second.path
    assert removed["diagnostic"] == 1
    assert not diagnostic.path.exists()


def test_runtime_store_preserves_and_rebuilds_corrupt_fingerprint_database(tmp_path: Path) -> None:
    runtime_root = tmp_path / "corrupt-runtime"
    runtime_root.mkdir()
    (runtime_root / "reuse-runtime.sqlite3").write_bytes(b"not-a-sqlite-database")

    with reuse_runtime.ReuseRuntimeStore(runtime_root) as store:
        recovery = store.recovery_event
        store.put_fingerprint(
            "app/service.py",
            "stat-key",
            {
                "suffix": ".py",
                "file_size": 10,
                "normalized_length": 8,
                "token_count": 2,
                "token_sketch": ["a", "b"],
                "content_digest": "digest",
            },
        )
        cached = store.get_fingerprint("app/service.py", "stat-key")

    assert recovery and recovery["reason"] == "sqlite_database_rebuilt"
    assert Path(recovery["preserved_corrupt_database"]).exists()
    assert cached and cached["content_digest"] == "digest"


def test_check_reuse_hard_timeout_returns_canonical_incomplete_report(tmp_path: Path) -> None:
    repo, _bundle = reuse_scope_fixture(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "check_reuse.py"),
            "--repo",
            str(repo),
            "--changed-path",
            "tests/test_workflow_execution.py",
            "--timeout-seconds",
            "0",
            "--hard-timeout-seconds",
            "0.02",
            "--runtime-dir",
            str(tmp_path / "hard-timeout-runtime"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(result.stdout)
    assert result.returncode == 2
    assert report["report_class"] == "canonical"
    assert report["result_status"] == "warn"
    assert report["completion_status"] == "timeout"
    assert report["evidence_complete"] is False
    assert Path(report["artifacts"]["checkpoint"]).exists()
    assert router_core.validate_against_schema(
        report,
        SKILL_ROOT / "schemas" / "reuse-scan-report.schema.json",
    ) == []


def test_reuse_output_examples_match_report_schema() -> None:
    schema = SKILL_ROOT / "schemas" / "reuse-scan-report.schema.json"
    for filename in ("check-reuse.pass.json", "check-reuse.warn.json", "check-reuse.timeout.json"):
        report = json.loads((SKILL_ROOT / "examples" / "outputs" / filename).read_text(encoding="utf-8"))
        assert router_core.validate_against_schema(report, schema) == []


def test_reuse_report_expands_one_hop_runtime_import_but_not_type_only_import(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "runtime-scope-repo"
    for module_name in ("workflow", "runtime", "contracts"):
        (repo / "app" / module_name).mkdir(parents=True)
    changed = repo / "app" / "workflow" / "service.ts"
    changed.write_text(
        'import { run } from "../runtime/engine";\n'
        'import type { Contract } from "../contracts/types";\n'
        "export const execute = (value: Contract) => run(value);\n",
        encoding="utf-8",
    )
    (repo / "app" / "runtime" / "engine.ts").write_text(
        "export const run = (value: unknown) => value;\n", encoding="utf-8"
    )
    (repo / "app" / "contracts" / "types.ts").write_text(
        "export type Contract = unknown;\n", encoding="utf-8"
    )
    modules = [
        router_core.ModuleEntry(
            f"module-{name}", f"app/{name}", "domain-service", name, name
        )
        for name in ("workflow", "runtime", "contracts")
    ]
    capabilities = [
        router_core.CapabilityEntry(
            name,
            name.title(),
            "stable",
            "stable",
            stage="stable",
            owner_modules=[f"app/{name}"],
        )
        for name in ("workflow", "runtime", "contracts")
    ]
    bundle = {
        "config": {"ignore_paths": []},
        "change_rules": {
            "reuse_scan_scope": {"include_dependency_neighbors": True}
        },
        "module_map": {"modules": [module.to_dict() for module in modules]},
        "capability_catalog": {
            "capabilities": [capability.to_dict() for capability in capabilities]
        },
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "app/workflow/service.ts",
                    "capabilities": ["workflow"],
                }
            ]
        },
    }

    report = router_core.gather_reuse_report(
        repo, bundle, ["app/workflow/service.ts"]
    )

    scope = report["scan"]["scope"]
    assert scope["direct_capability_ids"] == ["workflow"]
    assert scope["dependency_capability_ids"] == ["runtime"]
    assert scope["capability_ids"] == ["runtime", "workflow"]
    assert scope["completion_status"] == "complete"


def test_reuse_report_marks_import_parse_diagnostics_incomplete(tmp_path: Path) -> None:
    repo = tmp_path / "parse-diagnostic-repo"
    source = repo / "app" / "workflow" / "service.py"
    source.parent.mkdir(parents=True)
    source.write_text("def broken(:\n", encoding="utf-8")
    module = router_core.ModuleEntry(
        "module-workflow", "app/workflow", "domain-service", "workflow", "Workflow"
    )
    capability = router_core.CapabilityEntry(
        "workflow",
        "Workflow",
        "stable",
        "stable",
        stage="stable",
        owner_modules=["app/workflow"],
    )
    bundle = {
        "config": {"ignore_paths": []},
        "change_rules": {},
        "module_map": {"modules": [module.to_dict()]},
        "capability_catalog": {"capabilities": [capability.to_dict()]},
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "app/workflow/service.py",
                    "capabilities": ["workflow"],
                }
            ]
        },
    }

    report = router_core.gather_reuse_report(
        repo, bundle, ["app/workflow/service.py"]
    )

    assert report["scan"]["scope"]["status"] == "resolved"
    assert report["scan"]["scope"]["diagnostics"]
    assert report["scan"]["completion_status"] == "incomplete"
    assert report["scan"]["evidence_complete"] is False


def test_reuse_scan_missing_canonical_owner_surface_is_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "missing-owner-repo"
    candidate = repo / "app/new.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("def feature(): return True\n", encoding="utf-8")
    capability = router_core.CapabilityEntry(
        "core",
        "Core",
        "stable",
        "stable",
        stage="stable",
        owner_modules=["app/missing"],
    )
    bundle = {
        "config": {"ignore_paths": []},
        "change_rules": {},
        "module_map": {"modules": []},
        "capability_catalog": {"capabilities": [capability.to_dict()]},
        "path_to_capability_map": {
            "path_index": [
                {"path_pattern": "app/new.py", "capabilities": ["core"]}
            ]
        },
    }

    report = router_core.gather_reuse_report(repo, bundle, ["app/new.py"])

    assert report["scan"]["capabilities_scanned"] == 1
    assert report["scan"]["owner_file_count"] == 0
    assert report["scan"]["completion_status"] == "incomplete"
    assert report["scan"]["evidence_complete"] is False
    assert any(
        finding["rule"] == "reuse-owner-surface-missing"
        for finding in report["findings"]
    )


def test_reuse_full_scan_without_capabilities_is_incomplete(tmp_path: Path) -> None:
    repo = tmp_path / "empty-capability-repo"
    source = repo / "app/new.py"
    source.parent.mkdir(parents=True)
    source.write_text("def feature(): return True\n", encoding="utf-8")
    bundle = {
        "config": {"ignore_paths": []},
        "change_rules": {},
        "module_map": {"modules": []},
        "capability_catalog": {"capabilities": []},
    }

    report = router_core.gather_reuse_report(repo, bundle)

    assert report["scan"]["capabilities_scanned"] == 0
    assert report["scan"]["completion_status"] == "incomplete"
    assert report["scan"]["evidence_complete"] is False


def test_reuse_full_scan_without_candidate_or_owner_sources_is_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "empty-full-scan-repo"
    repo.mkdir()
    capability = router_core.CapabilityEntry(
        "core",
        "Core",
        "stable",
        "stable",
        stage="stable",
        owner_modules=["app/missing"],
    )
    module = router_core.ModuleEntry(
        "missing-module",
        "app/missing",
        "domain-service",
        "core",
        "Missing owner surface",
    )
    bundle = {
        "config": {"ignore_paths": []},
        "change_rules": {},
        "module_map": {"modules": [module.to_dict()]},
        "capability_catalog": {"capabilities": [capability.to_dict()]},
        "path_to_capability_map": {"path_index": []},
    }

    report = router_core.gather_reuse_report(repo, bundle)

    assert report["scan"]["candidate_file_count"] == 0
    assert report["scan"]["completion_status"] == "incomplete"
    assert report["scan"]["evidence_complete"] is False
    assert any(
        diagnostic["code"] == "no-candidate-source"
        for diagnostic in report["scan"]["scope"]["diagnostics"]
    )


@pytest.mark.parametrize(
    "invalid_budget",
    (
        {"max_length_ratio": 0.1},
        {"min_token_jaccard": 2.0, "min_path_token_overlap": 2.0},
        {"max_comparisons": "5000"},
    ),
)
def test_reuse_scan_invalid_prefilter_budget_is_incomplete(
    tmp_path: Path,
    invalid_budget: dict[str, object],
) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    bundle["change_rules"]["reuse_scan_budget"].update(invalid_budget)

    report = router_core.gather_reuse_report(
        repo,
        bundle,
        ["tests/test_workflow_execution.py"],
    )

    assert report["scan"]["completion_status"] == "incomplete"
    assert report["scan"]["evidence_complete"] is False
    assert any(
        finding["rule"] == "reuse-scan-configuration-invalid"
        for finding in report["findings"]
    )
