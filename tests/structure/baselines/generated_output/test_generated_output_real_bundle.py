from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import yaml

import router_core

from generated_output_test_support import (
    SKILL_ROOT,
    build_and_write_bundle,
    create_real_router_repo,
    git,
    make_real_rule,
    profile_with_rule,
)
from router_support.generated_output_baseline import (
    PCR_BUNDLE_ARTIFACTS,
    canonical_yaml_text,
    verify_generated_output_baseline,
)
from router_support.schema_validation import validator_for_schema


COMMIT_BEARING_KEYS = {
    "capability_catalog",
    "module_map",
    "path_to_capability_map",
    "exception_registry",
}
NULL_COMMIT_KEYS = {
    "ownership",
    "change_rules",
    "evaluation_set",
}


def test_real_builder_pin_preserves_mixed_source_commit_contract(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    source_commit = git(repo, "rev-parse", "HEAD")
    bundle = build_and_write_bundle(repo)

    assert {
        key for key, payload in bundle.items()
        if key in PCR_BUNDLE_ARTIFACTS and payload.get("source_commit") == source_commit
    } == COMMIT_BEARING_KEYS
    assert {
        key for key, payload in bundle.items()
        if key in PCR_BUNDLE_ARTIFACTS and payload.get("source_commit") is None
    } == NULL_COMMIT_KEYS

    rule = make_real_rule(repo, bundle)
    result = verify_generated_output_baseline(
        repo,
        profile_with_rule(repo, rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.findings == ()
    assert result.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())


def test_pin_records_each_artifacts_own_ancestor_source_commit(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    historical_commit = git(repo, "rev-parse", "HEAD")
    service = repo / "services" / "payments" / "service.py"
    service.write_text(
        "def charge():\n    return bool(1)\n",
        encoding="utf-8",
    )
    git(repo, "add", "services/payments/service.py")
    git(repo, "commit", "-m", "advance canonical source")
    bundle = build_and_write_bundle(repo)
    bundle["exception_registry"]["source_commit"] = historical_commit
    exception_path = repo / PCR_BUNDLE_ARTIFACTS["exception_registry"]
    exception_path.write_bytes(
        canonical_yaml_text(bundle["exception_registry"]).encode("utf-8")
    )

    rule = make_real_rule(repo, bundle)
    artifact = next(
        item
        for item in rule["artifacts"]
        if item["bundle_key"] == "exception_registry"
    )

    assert artifact["source_commit"] == historical_commit


def test_real_pin_keeps_pinned_metadata_with_exact_projected_rebuild(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    pinned_bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, pinned_bundle)
    pinned_commit = git(repo, "rev-parse", "HEAD")
    service = repo / "services" / "payments" / "service.py"
    service.write_text(
        "def charge():\n    return True  # reviewed implementation\n",
        encoding="utf-8",
    )
    git(repo, "add", "services/payments/service.py")
    git(repo, "commit", "-m", "advance source state")

    rebuilt = router_core.build_write_ready_router_bundle(repo)
    current_commit = git(repo, "rev-parse", "HEAD")
    stale = verify_generated_output_baseline(
        repo,
        profile_with_rule(repo, rule),
        rebuilt,
        enforce_provenance=False,
    )

    assert current_commit != pinned_commit
    assert all(
        isinstance(rebuilt[key]["source_commit"], str)
        for key in COMMIT_BEARING_KEYS
    )
    assert current_commit in {
        rebuilt[key]["source_commit"] for key in COMMIT_BEARING_KEYS
    }
    assert all(rebuilt[key]["source_commit"] is None for key in NULL_COMMIT_KEYS)
    assert stale.findings == ()
    assert stale.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())
    assert any(
        item.get("source_commit_match_mode") == "pinned_ancestor_rebuild"
        for item in stale.evidence
    )

    router_core.write_bundle(repo / "project-change-router", rebuilt)
    refreshed = verify_generated_output_baseline(
        repo,
        profile_with_rule(repo, rule),
        rebuilt,
        enforce_provenance=False,
    )

    assert refreshed.verified_paths == frozenset()
    assert any(
        finding["diagnostic_code"]
        == "generated_output_artifact_source_commit_mismatch"
        for finding in refreshed.findings
    )


def test_rebuilt_source_commit_mode_drift_is_blocking(tmp_path: Path) -> None:
    repo = create_real_router_repo(tmp_path)
    pinned_bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, pinned_bundle)
    rebuilt = copy.deepcopy(pinned_bundle)
    rebuilt["capability_catalog"]["source_commit"] = None
    rebuilt["ownership"]["source_commit"] = git(repo, "rev-parse", "HEAD")

    result = verify_generated_output_baseline(
        repo,
        profile_with_rule(repo, rule),
        rebuilt,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert {
        finding["diagnostic_code"] for finding in result.findings
    } >= {"generated_output_artifact_source_commit_mismatch"}


def test_actual_null_commit_artifact_cannot_adopt_the_rule_commit(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    ownership_path = repo / PCR_BUNDLE_ARTIFACTS["ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["source_commit"] = git(repo, "rev-parse", "HEAD")
    ownership_path.write_bytes(canonical_yaml_text(ownership).encode("utf-8"))

    result = verify_generated_output_baseline(
        repo,
        profile_with_rule(repo, rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        finding["diagnostic_code"]
        == "generated_output_artifact_source_commit_mismatch"
        and finding["bundle_key"] == "ownership"
        for finding in result.findings
    )


def test_actual_commit_bearing_artifact_rejects_source_mismatch(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    catalog_path = repo / PCR_BUNDLE_ARTIFACTS["capability_catalog"]
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["source_commit"] = "f" * 40
    catalog_path.write_bytes(canonical_yaml_text(catalog).encode("utf-8"))

    result = verify_generated_output_baseline(
        repo,
        profile_with_rule(repo, rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        finding["diagnostic_code"]
        == "generated_output_artifact_source_commit_mismatch"
        and finding["bundle_key"] == "capability_catalog"
        for finding in result.findings
    )


def test_malformed_capability_lifecycle_returns_structured_findings(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    rebuilt = copy.deepcopy(bundle)
    rebuilt["capability_catalog"]["capabilities"][0]["lifecycle"] = "invalid"

    result = verify_generated_output_baseline(
        repo,
        profile_with_rule(repo, rule),
        rebuilt,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert result.findings
    json.dumps(result.findings, allow_nan=False, ensure_ascii=False)


def test_tracked_pin_survives_rebuild_commit_and_joint_guardrails(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    profile = profile_with_rule(repo, rule)
    (repo / ".project-change-router.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    git(repo, "add", ".project-change-router.yaml", "project-change-router")
    git(repo, "commit", "-m", "pin tracked generated outputs")
    comparison_commit = git(repo, "rev-parse", "HEAD")
    pinned_bytes = {
        key: (repo / relative_path).read_bytes()
        for key, relative_path in PCR_BUNDLE_ARTIFACTS.items()
    }
    service = repo / "services" / "payments" / "service.py"
    service.write_text(
        "def charge():\n    return bool(1)\n",
        encoding="utf-8",
    )
    git(repo, "add", "services/payments/service.py")
    git(repo, "commit", "-m", "change payment implementation")
    rebuild_report = router_core.rebuild_index(repo, write_back=True)

    assert rebuild_report["status"] == "pass"
    validator = validator_for_schema(
        SKILL_ROOT / "schemas/index-rebuild-report.schema.json"
    )
    assert list(validator.iter_errors(rebuild_report)) == []
    assert set(rebuild_report["preserved_generated_output_keys"]) == set(
        PCR_BUNDLE_ARTIFACTS
    )
    assert {
        key: (repo / relative_path).read_bytes()
        for key, relative_path in PCR_BUNDLE_ARTIFACTS.items()
    } == pinned_bytes
    git(repo, "add", "project-change-router")
    git(repo, "commit", "-m", "record current router observation")

    structure = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "check_structure.py"),
            "--repo",
            str(repo),
            "--comparison-commit",
            comparison_commit,
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    freshness = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "check_index_freshness.py"),
            "--repo",
            str(repo),
            "--comparison-commit",
            comparison_commit,
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert structure.returncode == 0, structure.stdout + structure.stderr
    assert json.loads(structure.stdout)["status"] == "pass"
    assert freshness.returncode == 0, freshness.stdout + freshness.stderr
    assert json.loads(freshness.stdout)["status"] == "pass"
