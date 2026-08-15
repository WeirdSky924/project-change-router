from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support.freshness_checks import canonical_bundle_snapshot_paths


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _persisted_route_bundle(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], Path]:
    repo = tmp_path / "repo"
    source = repo / "src" / "formatter" / "service.py"
    source.parent.mkdir(parents=True)
    source.write_text("def format_value(value):\n    return str(value)\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "router@example.test")
    _git(repo, "config", "user.name", "Router Test")
    _git(repo, "add", "src/formatter/service.py")
    _git(repo, "commit", "-m", "baseline")

    bundle_root = repo / "project-change-router"
    marker = bundle_root / "references" / "module-map.yaml"
    marker.parent.mkdir(parents=True)
    marker.write_text("modules: []\n", encoding="utf-8")
    categories = (
        ("positive_extend", "extend"),
        ("positive_reuse", "reuse"),
        ("extract_boundary", "extract"),
        ("review_veto", "review"),
        ("false_positive_regression", "extend"),
        ("false_negative_regression", "review"),
    )
    evaluation_cases = [
        {
            "id": f"formatter-{index}",
            "request": "Extend formatter output compatibility.",
            "expected_action": categories[index % len(categories)][1],
            "expected_capabilities": ["formatter"],
            "expected_primary_capability": "formatter",
            "changed_paths": ["src/formatter/service.py"],
            "risk_level": "high",
            "calibration_category": categories[index % len(categories)][0],
        }
        for index in range(30)
    ]
    bundle: dict[str, object] = {
        "root": bundle_root,
        "config": {
            "source_commit": _git(repo, "rev-parse", "HEAD"),
            "repo_stage": "governed",
            "ignore_paths": ["project-change-router/**"],
            "freshness_windows": {"module_map_days": 30},
            "evaluation": {
                "enforcement_enabled": True,
                "top1_accuracy_threshold": 0.85,
                "top1_capability_accuracy_threshold": 0.85,
                "review_precision_threshold": 0.90,
                "review_recall_threshold": 1.0,
                "minimum_capability_coverage_ratio": 0.80,
                "secondary_contract_accuracy_threshold": 1.0,
                "minimum_case_count": 30,
            },
        },
        "module_map": {
            "modules": [
                {
                    "id": "module-formatter",
                    "path": "src/formatter",
                    "layer": "domain-service",
                    "domain": "formatter",
                    "purpose": "Format values",
                    "public_api": "service.py",
                    "source_of_truth": "curated",
                    "generated": False,
                    "owner": "formatter-team",
                }
            ]
        },
        "capability_catalog": {
            "capabilities": [
                {
                    "id": "formatter",
                    "name": "Formatter",
                    "status": "stable",
                    "maturity": "curated",
                    "stage": "stable",
                    "source_of_truth": "profile",
                    "intent_keywords": ["formatter", "format"],
                    "owner_modules": ["src/formatter"],
                    "public_entries": ["src/formatter/service.py"],
                    "extension_points": ["src/formatter/service.py"],
                    "contracts": ["Keep formatter output compatible"],
                }
            ]
        },
        "ownership": {
            "owners": [
                {
                    "scope": "capability",
                    "target": "formatter",
                    "primary": "formatter-team",
                    "reviewers": ["formatter-reviewers"],
                    "provisional": False,
                }
            ]
        },
        "change_rules": {
            "confidence": {
                "auto_route_threshold": 0.78,
                "guarded_route_threshold": 0.58,
            },
            "high_risk_capability_ids": [],
        },
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "src/formatter/**",
                    "capabilities": ["formatter"],
                    "relationship": "unique",
                }
            ]
        },
        "evaluation_set": {
            "mode": "curated",
            "curated_case_ids": [case["id"] for case in evaluation_cases],
            "cases": evaluation_cases,
        },
    }
    bundle["config"]["evaluation"]["attestation"] = (
        router_core.make_evaluation_attestation(
            bundle,
            {
                "top1_action_accuracy": 1,
                "top1_capability_accuracy": 1,
                "review_precision": 1,
                "review_recall": 1,
                "capability_coverage_ratio": 1,
                "secondary_contract_accuracy": 1,
                "case_count": 30,
                "strict_secondary_case_count": 0,
            },
        )
    )
    snapshot = router_core.build_structure_snapshot(
        repo,
        router_core.default_ignore_patterns(bundle["config"]),
        required_patterns=canonical_bundle_snapshot_paths(repo, bundle_root),
    )
    latest = bundle_root / "reports" / "index-rebuild" / "latest.json"
    router_core.dump_json_file(
        latest,
        {
            "source_commit": "0" * 40,
            "structure_digest": "0" * 64,
            "indexed_paths": list(snapshot.paths),
            "mapped_path_patterns": ["src/formatter/**"],
            "stale_entries": [],
            "diagnostics": [],
            "status": "pass",
        },
    )
    return repo, bundle, latest


def test_resolve_blocks_stale_commit_and_digest_despite_fresh_marker(
    tmp_path: Path,
) -> None:
    repo, bundle, _latest = _persisted_route_bundle(tmp_path)
    marker = repo / "project-change-router" / "references" / "module-map.yaml"
    assert marker.exists()

    decision = router_core.resolve_request(
        "Extend formatter output compatibility.",
        ["src/formatter/service.py"],
        bundle,
        repo / "project-change-router",
    )

    assert decision.action == "extend"
    assert decision.review_required is True
    assert decision.execution_gate["state"] == "blocked"
    assert decision.gate_shadow["legacy_state"] == "blocked"
    assert decision.block_reason["code"] == "stale_bundle"
    assert decision.allowed_write_paths == []
    assert "**" in decision.forbidden_write_paths
    assert bundle["_runtime"]["freshness"]["failure_reasons"] == [
        "source_commit",
        "structure_digest",
    ]


def test_resolve_blocks_when_persisted_freshness_snapshot_is_missing(
    tmp_path: Path,
) -> None:
    repo, bundle, latest = _persisted_route_bundle(tmp_path)
    latest.unlink()

    decision = router_core.resolve_request(
        "Extend formatter output compatibility.",
        ["src/formatter/service.py"],
        bundle,
        repo / "project-change-router",
    )

    assert decision.action == "extend"
    assert decision.block_reason["code"] == "stale_bundle"
    assert decision.allowed_write_paths == []
    assert decision.execution_gate["state"] == "blocked"
    assert bundle["_runtime"]["freshness"]["status"] == "fail"


def test_resolve_explicit_route_paths_cannot_hide_other_git_changes(
    tmp_path: Path,
) -> None:
    repo, bundle, _latest = _persisted_route_bundle(tmp_path)
    outside = repo / "outside/unmapped.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("VALUE = 1\n", encoding="utf-8")

    decision = router_core.resolve_request(
        "Extend formatter output compatibility.",
        ["src/formatter/service.py"],
        bundle,
        repo / "project-change-router",
    )

    freshness = bundle["_runtime"]["freshness"]
    assert decision.action == "extend"
    assert "outside/unmapped.py" in freshness["changed_paths"]
    assert freshness["unmapped_changed_paths"] == ["outside/unmapped.py"]
    assert decision.execution_gate["state"] == "blocked"


def test_resolve_allows_proven_unrelated_freshness_debt(
    tmp_path: Path,
) -> None:
    repo, bundle, latest = _persisted_route_bundle(tmp_path)
    (repo / ".gitignore").write_text(
        "project-change-router/\n", encoding="utf-8"
    )
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore generated router bundle")

    bundle["module_map"]["modules"].append(
        {
            "id": "module-reports",
            "path": "src/reports",
            "layer": "domain-service",
            "domain": "reports",
            "purpose": "Build reports",
            "public_api": "service.py",
            "source_of_truth": "curated",
            "generated": False,
            "owner": "reports-team",
        }
    )
    bundle["capability_catalog"]["capabilities"].append(
        {
            "id": "reports",
            "name": "Reports",
            "status": "stable",
            "maturity": "curated",
            "stage": "stable",
            "source_of_truth": "profile",
            "intent_keywords": ["report"],
            "owner_modules": ["src/reports"],
            "public_entries": ["src/reports/service.py"],
            "extension_points": ["src/reports/service.py"],
            "contracts": ["Keep report generation isolated"],
        }
    )
    bundle["ownership"]["owners"].append(
        {
            "scope": "capability",
            "target": "reports",
            "primary": "reports-team",
            "reviewers": ["reports-reviewers"],
            "provisional": False,
        }
    )
    bundle["path_to_capability_map"]["path_index"].append(
        {
            "path_pattern": "src/reports/**",
            "capabilities": ["reports"],
            "relationship": "unique",
        }
    )
    bundle["config"]["source_commit"] = _git(repo, "rev-parse", "HEAD")
    bundle["config"]["evaluation"]["attestation"] = (
        router_core.make_evaluation_attestation(
            bundle,
            bundle["config"]["evaluation"]["attestation"]["metrics"],
        )
    )
    snapshot = router_core.build_structure_snapshot(
        repo,
        router_core.default_ignore_patterns(bundle["config"]),
        required_patterns=canonical_bundle_snapshot_paths(
            repo, repo / "project-change-router"
        ),
    )
    router_core.dump_json_file(
        latest,
        {
            "source_commit": snapshot.source_commit,
            "structure_digest": snapshot.digest,
            "indexed_paths": list(snapshot.paths),
            "mapped_path_patterns": ["src/formatter/**", "src/reports/**"],
            "stale_entries": [],
            "diagnostics": [],
            "status": "pass",
        },
    )
    unrelated = repo / "src/reports/new_report.py"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("def render():\n    return 'ok'\n", encoding="utf-8")

    decision = router_core.resolve_request(
        "Extend formatter output compatibility.",
        ["src/formatter/service.py"],
        bundle,
        repo / "project-change-router",
        enforce_evaluation_policy=False,
        freshness_context="route",
    )

    freshness = bundle["_runtime"]["freshness"]
    assert freshness["status"] == "fail"
    assert freshness["route_status"] == "pass"
    assert freshness["route_assessment"]["classification"] == "baseline_unchanged"
    assert freshness["route_assessment"]["unrelated_changed_paths"] == [
        "src/reports/new_report.py"
    ]
    assert decision.action == "extend", decision.to_dict()
    assert decision.review_required is False
    assert "**" not in decision.forbidden_write_paths
    assert decision.execution_gate["state"] == "conditional"
    assert decision.gate_shadow["classification"] == "more_restrictive"


def test_route_freshness_blocks_reverse_dependency_closure_delta() -> None:
    bundle = {
        "module_map": {
            "modules": [
                {
                    "id": "module-api",
                    "path": "src/api",
                    "layer": "interface",
                    "domain": "api",
                    "purpose": "Expose API handlers",
                    "depends_on": ["src/core"],
                },
                {
                    "id": "module-core",
                    "path": "src/core",
                    "layer": "domain-service",
                    "domain": "core",
                    "purpose": "Own core behavior",
                    "depends_on": [],
                },
            ]
        },
        "capability_catalog": {
            "capabilities": [
                {
                    "id": "api",
                    "name": "API",
                    "status": "stable",
                    "maturity": "curated",
                    "owner_modules": ["src/api"],
                },
                {
                    "id": "core",
                    "name": "Core",
                    "status": "stable",
                    "maturity": "curated",
                    "owner_modules": ["src/core"],
                },
            ]
        },
        "path_to_capability_map": {
            "path_index": [
                {"path_pattern": "src/api/**", "capabilities": ["api"]},
                {"path_pattern": "src/core/**", "capabilities": ["core"]},
            ]
        },
    }
    report = {
        "status": "fail",
        "failure_reasons": ["structure_digest"],
        "repository_changed_paths": ["src/core/service.py"],
        "checks": [],
    }

    assessment = router_core._route_freshness_assessment(
        bundle, report, ["src/api/handler.py"]
    )

    assert assessment["status"] == "fail"
    assert assessment["classification"] == "task_local_new"
    assert assessment["relevant_capabilities"] == ["api", "core"]
    assert assessment["relevant_changed_paths"] == ["src/core/service.py"]


def test_route_freshness_does_not_localize_untrusted_source_commit() -> None:
    bundle = {
        "module_map": {"modules": []},
        "capability_catalog": {"capabilities": []},
        "path_to_capability_map": {
            "path_index": [
                {"path_pattern": "src/api/**", "capabilities": ["api"]},
                {"path_pattern": "src/reports/**", "capabilities": ["reports"]},
            ]
        },
    }
    report = {
        "status": "fail",
        "failure_reasons": ["source_commit", "structure_digest"],
        "repository_changed_paths": ["src/reports/service.py"],
        "comparison_delta_complete": False,
        "checks": [],
    }

    assessment = router_core._route_freshness_assessment(
        bundle, report, ["src/api/handler.py"]
    )

    assert assessment["status"] == "fail"
    assert assessment["classification"] == "unknown"
    assert assessment["unrelated_changed_paths"] == ["src/reports/service.py"]


def test_evaluation_self_check_does_not_require_a_persisted_freshness_snapshot(
    tmp_path: Path,
) -> None:
    repo, bundle, latest = _persisted_route_bundle(tmp_path)
    latest.unlink()

    report = router_core.evaluate_bundle(bundle, repo)

    assert report["per_case_results"][0]["predicted_action"] == "extend"
    assert report["per_case_results"][0]["action_ok"] is True
