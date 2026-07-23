from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
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
    generated_output_rule_fingerprint,
    make_pinned_generated_output_baseline,
    validate_generated_output_rules,
    verify_generated_output_baseline,
)


def _commit_pin(repo: Path) -> tuple[dict[str, object], dict[str, bytes]]:
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    profile = profile_with_rule(repo, rule)
    (repo / ".project-change-router.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False),
        encoding="utf-8",
    )
    git(repo, "add", ".project-change-router.yaml", "project-change-router")
    git(repo, "commit", "-m", "pin generated outputs")
    return rule, {
        key: (repo / relative_path).read_bytes()
        for key, relative_path in PCR_BUNDLE_ARTIFACTS.items()
    }


def _bundle_bytes(repo: Path) -> dict[str, bytes]:
    bundle_root = repo / "project-change-router"
    return {
        str(path.relative_to(bundle_root)): path.read_bytes()
        for path in bundle_root.rglob("*")
        if path.is_file()
    }


def test_failed_rebuild_preserves_every_bundle_file_and_skips_report(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    _commit_pin(repo)
    module_map = repo / PCR_BUNDLE_ARTIFACTS["module_map"]
    module_map.write_text(
        module_map.read_text(encoding="utf-8") + "# drift\n",
        encoding="utf-8",
    )
    before = _bundle_bytes(repo)
    latest = repo / "project-change-router/reports/index-rebuild/latest.json"

    report = router_core.rebuild_index(repo, write_back=True)

    assert report["status"] == "fail"
    assert report["write_performed"] is False
    assert set(report["preserved_generated_output_keys"]) == set(
        PCR_BUNDLE_ARTIFACTS
    )
    assert report["generated_output_findings"]
    assert _bundle_bytes(repo) == before
    assert not latest.exists()


def test_malformed_falsy_pin_declaration_cannot_trigger_rewrite(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    _, pinned = _commit_pin(repo)
    profile_path = repo / ".project-change-router.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["guardrails"]["generated_output_baseline"] = {}
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False),
        encoding="utf-8",
    )

    report = router_core.rebuild_index(repo, write_back=True)

    assert report["status"] == "fail"
    assert report["write_performed"] is False
    assert report["generated_output_findings"]
    assert {
        key: (repo / relative_path).read_bytes()
        for key, relative_path in PCR_BUNDLE_ARTIFACTS.items()
    } == pinned


def test_uncommitted_pin_removal_remains_protected_until_commit(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    _, pinned = _commit_pin(repo)
    profile_path = repo / ".project-change-router.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["guardrails"].pop("generated_output_baseline")
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False),
        encoding="utf-8",
    )

    pending = router_core.rebuild_index(repo, write_back=True)

    assert pending["status"] == "fail"
    assert pending["write_performed"] is False
    assert any(
        item["diagnostic_code"]
        == "generated_output_baseline_removal_not_committed"
        for item in pending["generated_output_findings"]
    )
    assert {
        key: (repo / relative_path).read_bytes()
        for key, relative_path in PCR_BUNDLE_ARTIFACTS.items()
    } == pinned

    git(repo, "add", ".project-change-router.yaml")
    git(repo, "commit", "-m", "remove generated output pin")
    released = router_core.rebuild_index(repo, write_back=True)

    assert released["status"] == "pass"
    assert released["write_performed"] is True
    assert released["preserved_generated_output_keys"] == []


def test_bootstrap_cannot_clear_an_existing_pinned_bundle(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    _commit_pin(repo)
    before = _bundle_bytes(repo)

    with pytest.raises(RuntimeError, match="generated output"):
        router_core.bootstrap_bundle(repo, write=True)

    assert _bundle_bytes(repo) == before


def test_bootstrap_cli_reports_pin_block_as_structured_json(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    _commit_pin(repo)

    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts/bootstrap_router.py"),
            "--repo",
            str(repo),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    report = json.loads(result.stdout)
    assert result.returncode == 2
    assert report["status"] == "fail"
    assert report["error_code"] == "generated_output_write_blocked"
    assert "Traceback" not in result.stderr


def test_rule_source_commit_requires_full_immutable_sha(tmp_path: Path) -> None:
    repo = create_real_router_repo(tmp_path)
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    rule["source_commit"] = "HEAD"
    rule["fingerprint"] = generated_output_rule_fingerprint(rule)
    profile = profile_with_rule(repo, rule)

    findings = validate_generated_output_rules(profile, repo_root=repo)

    assert any(
        item["diagnostic_code"] == "generated_output_baseline_invalid"
        and "source_commit" in item.get("invalid_fields", [])
        for item in findings
    )
    with pytest.raises(ValueError, match="full immutable Git SHA"):
        make_pinned_generated_output_baseline(
            repo,
            bundle,
            baseline_id="PCR-GEN-SYMBOLIC",
            source_commit="HEAD",
            owner="payment-core",
            reason="Reject symbolic pin sources.",
            exit_stage="PCR-GEN-CANONICAL-INPUTS",
            exit_condition="Remove after canonical inputs converge.",
            initialization_authorization="Explicit test authorization.",
        )


def test_sha256_repository_rejects_a_40_character_commit_prefix(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path, object_format="sha256")
    bundle = build_and_write_bundle(repo)
    full_source = git(repo, "rev-parse", "HEAD")
    assert len(full_source) == 64

    with pytest.raises(ValueError, match="full immutable Git SHA"):
        make_pinned_generated_output_baseline(
            repo,
            bundle,
            baseline_id="PCR-GEN-SHA256",
            source_commit=full_source[:40],
            owner="payment-core",
            reason="Reject abbreviated SHA-256 provenance.",
            exit_stage="PCR-GEN-CANONICAL-INPUTS",
            exit_condition="Remove after canonical inputs converge.",
            initialization_authorization="Explicit test authorization.",
        )


def test_rebuild_cli_requires_exact_fingerprint_for_a_new_pin(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    profile = profile_with_rule(repo, rule)
    (repo / ".project-change-router.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(SKILL_ROOT / "scripts/rebuild_index.py"),
        "--repo",
        str(repo),
        "--format",
        "json",
    ]

    denied = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    allowed = subprocess.run(
        [
            *command,
            "--initialize-generated-output-baseline",
            str(rule["fingerprint"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    denied_report = json.loads(denied.stdout)
    allowed_report = json.loads(allowed.stdout)
    assert denied.returncode == 2
    assert denied_report["generated_output_write_state"] == "blocked"
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert allowed_report["generated_output_write_state"] == "preserved_verified"
    assert set(allowed_report["preserved_generated_output_keys"]) == set(
        PCR_BUNDLE_ARTIFACTS
    )


def test_source_mismatch_diagnostic_separates_rule_and_artifact_provenance(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    artifact = next(
        item
        for item in rule["artifacts"]
        if item["bundle_key"] == "capability_catalog"
    )
    artifact_source = str(artifact["source_commit"])
    rebuilt = copy.deepcopy(bundle)
    rebuilt["capability_catalog"]["source_commit"] = "f" * 40

    result = verify_generated_output_baseline(
        repo,
        profile_with_rule(repo, rule),
        rebuilt,
        enforce_provenance=False,
    )

    finding = next(
        item
        for item in result.findings
        if item["diagnostic_code"]
        == "generated_output_artifact_source_commit_mismatch"
    )
    assert finding["rule_source_commit"] == rule["source_commit"]
    assert finding["pinned_artifact_source_commit"] == artifact_source
    assert "pinned_source_commit" not in finding
