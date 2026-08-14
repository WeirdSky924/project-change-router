from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.generated_output_baseline import (
    PCR_BUNDLE_ARTIFACTS,
    canonical_yaml_text,
    generated_output_rule_fingerprint,
    make_pinned_generated_output_baseline,
    validate_generated_output_rules,
    verify_generated_output_baseline,
)


def _bundle() -> dict[str, dict[str, object]]:
    return {
        key: {
            "schema_version": 1,
            "generated_at": "2026-07-23T00:00:00Z",
            "generated_by": "bootstrap_router",
            "source_repository": "example",
            "source_commit": "a" * 40,
            "payload": {"key": key, "enabled": True},
        }
        for key in PCR_BUNDLE_ARTIFACTS
    }


def _write_bundle(repo: Path, bundle: dict[str, dict[str, object]]) -> None:
    for key, relative_path in PCR_BUNDLE_ARTIFACTS.items():
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_yaml_text(bundle[key]), encoding="utf-8")


def _rule(
    repo: Path,
    bundle: dict[str, dict[str, object]],
    *,
    source_commit: str = "a" * 40,
) -> dict[str, object]:
    if not any(
        (repo / name).is_file()
        for name in (".project-change-router.yaml", ".project-change-router.yml")
    ):
        (repo / ".project-change-router.yaml").write_text(
            "profile_id: test\n", encoding="utf-8"
        )
    if not (repo / ".git").exists():
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "pcr@example.invalid")
        _git(repo, "config", "user.name", "PCR Test")
        canonical_profile = next(
            repo / name
            for name in (".project-change-router.yaml", ".project-change-router.yml")
            if (repo / name).is_file()
        )
        _git(repo, "add", canonical_profile.name)
        _git(repo, "commit", "-qm", "canonical profile source")
    if source_commit == "a" * 40:
        source_commit = _git(repo, "rev-parse", "HEAD")
    for payload in bundle.values():
        payload["source_commit"] = source_commit
    _write_bundle(repo, bundle)
    return make_pinned_generated_output_baseline(
        repo,
        bundle,
        baseline_id="PCR-GEN-001",
        source_commit=source_commit,
        owner="rebuild-governance",
        reason="Freeze reviewed generated outputs during canonical profile migration.",
        exit_stage="PCR-GEN-CANONICAL-INPUTS",
        exit_condition="Remove after canonical-only rebuild converges.",
        initialization_authorization="Explicit repository-owner review for this migration.",
    )


def _profile(rule: dict[str, object]) -> dict[str, object]:
    return {
        "capabilities": [
            {
                "id": "rebuild-governance",
                "status": "stable",
                "stage": "stable",
            }
        ],
        "capability_ownership": [
            {
                "target": "rebuild-governance",
                "primary": "rebuild-governance",
                "reviewers": ["rebuild-governance-reviewers"],
            }
        ],
        "guardrails": {"generated_output_baseline": [rule]},
    }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_exact_pinned_idempotent_bundle_verifies_atomically(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.findings == ()
    assert result.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())
    assert {item["bundle_key"] for item in result.evidence} == set(
        PCR_BUNDLE_ARTIFACTS
    )


def test_comment_or_formatting_drift_is_not_hidden_by_semantic_digest(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    target = repo / PCR_BUNDLE_ARTIFACTS["module_map"]
    target.write_text(target.read_text(encoding="utf-8") + "# manual note\n", encoding="utf-8")

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code") == "generated_output_artifact_noncanonical"
        for item in result.findings
    )


def test_one_artifact_mismatch_invalidates_the_whole_group(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    changed = copy.deepcopy(bundle)
    changed["ownership"]["payload"] = {"key": "ownership", "enabled": False}

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        changed,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code")
        in {
            "generated_output_artifact_digest_mismatch",
            "generated_output_artifact_not_idempotent",
        }
        for item in result.findings
    )


def test_unknown_artifact_and_fingerprint_drift_fail_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    rule["artifacts"][0]["bundle_key"] = "arbitrary_output"
    rule["fingerprint"] = "0" * 64

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code") == "generated_output_baseline_invalid"
        for item in result.findings
    )
    assert any(
        item.get("diagnostic_code")
        == "generated_output_baseline_fingerprint_mismatch"
        for item in result.findings
    )


def test_non_json_rule_scalar_returns_structured_invalid_finding(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    rule["reason"] = yaml.safe_load("value: 2026-07-23\n")["value"]

    findings = validate_generated_output_rules(
        _profile(rule), repo_root=repo
    )

    assert any(
        item.get("diagnostic_code") == "generated_output_baseline_invalid"
        for item in findings
    )


def test_non_json_artifact_scalar_returns_structured_noncanonical_finding(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    target = repo / PCR_BUNDLE_ARTIFACTS["module_map"]
    changed = yaml.safe_load(target.read_text(encoding="utf-8"))
    changed["payload"]["reviewed_on"] = yaml.safe_load(
        "value: 2026-07-23\n"
    )["value"]
    target.write_text(canonical_yaml_text(changed), encoding="utf-8")

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code") == "generated_output_artifact_noncanonical"
        for item in result.findings
    )


def test_generated_at_only_change_keeps_the_pin_valid(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    target = repo / PCR_BUNDLE_ARTIFACTS["module_map"]
    changed = copy.deepcopy(bundle["module_map"])
    changed["generated_at"] = "2026-07-24T00:00:00Z"
    target.write_text(canonical_yaml_text(changed), encoding="utf-8")

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.findings == ()
    assert result.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())


def test_path_map_code_file_count_comparison_contract(tmp_path: Path) -> None:
    cases = (
        ("changed", 3, 4, None),
        ("missing", 3, None, "generated_output_artifact_not_idempotent"),
        ("tampered", 4, 4, "generated_output_artifact_digest_mismatch"),
    )
    for name, actual_count, rebuilt_count, expected_code in cases:
        repo = tmp_path / name
        bundle = _bundle()
        entry = {
            "path_pattern": "frontend/src/**",
            "capabilities": ["frontend-transport-hooks"],
            "code_file_count": 3,
        }
        bundle["path_to_capability_map"]["path_index"] = [entry]
        _write_bundle(repo, bundle)
        rule = _rule(repo, bundle)
        if actual_count != 3:
            entry["code_file_count"] = actual_count
            target = repo / PCR_BUNDLE_ARTIFACTS["path_to_capability_map"]
            target.write_text(canonical_yaml_text(bundle["path_to_capability_map"]), encoding="utf-8")
        rebuilt = copy.deepcopy(bundle)
        if rebuilt_count is None:
            del rebuilt["path_to_capability_map"]["path_index"][0]["code_file_count"]
        else:
            rebuilt["path_to_capability_map"]["path_index"][0]["code_file_count"] = rebuilt_count

        result = verify_generated_output_baseline(
            repo, _profile(rule), rebuilt, enforce_provenance=False
        )
        if expected_code is None:
            assert result.findings == ()
            assert result.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())
        else:
            assert result.verified_paths == frozenset()
            assert any(item.get("diagnostic_code") == expected_code for item in result.findings)


def test_crlf_generated_artifact_is_not_accepted_as_canonical(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    target = repo / PCR_BUNDLE_ARTIFACTS["module_map"]
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code") == "generated_output_artifact_noncanonical"
        for item in result.findings
    )


def test_pin_owner_requires_stable_capability_and_distinct_reviewer(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    profile = _profile(rule)
    profile["capability_ownership"] = []

    result = verify_generated_output_baseline(
        repo,
        profile,
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code") == "generated_output_baseline_owner_invalid"
        for item in result.findings
    )


def test_pin_owner_rejects_provisional_ownership(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    for section in ("capabilities", "capability_ownership"):
        profile = _profile(rule)
        profile[section][0]["provisional"] = True

        result = verify_generated_output_baseline(
            repo,
            profile,
            bundle,
            enforce_provenance=False,
        )

        assert result.verified_paths == frozenset()
        assert any(
            item.get("diagnostic_code")
            == "generated_output_baseline_owner_invalid"
            for item in result.findings
        )


def test_pin_owner_rejects_case_variant_self_reviewer(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    profile = _profile(rule)
    profile["capability_ownership"][0]["reviewers"] = ["REBUILD-GOVERNANCE"]

    result = verify_generated_output_baseline(
        repo,
        profile,
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code") == "generated_output_baseline_owner_invalid"
        for item in result.findings
    )


def test_pin_owner_allows_distinct_steward_identity_for_capability(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    profile = _profile(rule)
    profile["capability_ownership"][0]["primary"] = "routing-maintainers"

    result = verify_generated_output_baseline(
        repo,
        profile,
        bundle,
        enforce_provenance=False,
    )

    assert result.findings == ()
    assert result.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())


def test_pin_owner_rejects_untrusted_stewards_reviewers_and_duplicates(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    profiles: list[dict[str, object]] = []
    for primary in ("UNKNOWN", "provisional:routing-maintainers"):
        profile = _profile(rule)
        profile["capability_ownership"][0]["primary"] = primary
        profiles.append(profile)
    for reviewers in (
        [],
        ["UNKNOWN"],
        ["routing-reviewers", "ROUTING-REVIEWERS"],
        [1],
    ):
        profile = _profile(rule)
        profile["capability_ownership"][0]["reviewers"] = reviewers
        profiles.append(profile)
    duplicate_capability = _profile(rule)
    duplicate_capability["capabilities"].append(
        copy.deepcopy(duplicate_capability["capabilities"][0])
    )
    profiles.append(duplicate_capability)
    duplicate_ownership = _profile(rule)
    duplicate_ownership["capability_ownership"].append(
        copy.deepcopy(duplicate_ownership["capability_ownership"][0])
    )
    profiles.append(duplicate_ownership)

    for profile in profiles:
        result = verify_generated_output_baseline(
            repo,
            profile,
            bundle,
            enforce_provenance=False,
        )
        assert result.verified_paths == frozenset()
        assert any(
            item.get("diagnostic_code")
            == "generated_output_baseline_owner_invalid"
            for item in result.findings
        )


def test_committed_pin_cannot_be_reinitialized_under_a_new_id(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.invalid")
    _git(repo, "config", "user.name", "PCR Test")
    (repo / ".project-change-router.yaml").write_text(
        "profile_id: test\n", encoding="utf-8"
    )
    _git(repo, "add", ".project-change-router.yaml")
    _git(repo, "commit", "-qm", "base")
    source_commit = _git(repo, "rev-parse", "HEAD")
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle, source_commit=source_commit)
    (repo / ".project-change-router.yaml").write_text(
        yaml.safe_dump(_profile(rule), sort_keys=False), encoding="utf-8"
    )
    _git(repo, "add", ".project-change-router.yaml")
    _git(repo, "commit", "-qm", "pin generated outputs")
    comparison_commit = _git(repo, "rev-parse", "HEAD")
    renamed = copy.deepcopy(rule)
    renamed["id"] = "PCR-GEN-RESET"
    renamed["fingerprint"] = generated_output_rule_fingerprint(renamed)

    result = verify_generated_output_baseline(
        repo,
        _profile(renamed),
        bundle,
        comparison_commit=comparison_commit,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code")
        == "generated_output_baseline_changed_since_comparison"
        for item in result.findings
    )


def test_committed_pin_allows_current_head_rebuild_with_pinned_provenance(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.invalid")
    _git(repo, "config", "user.name", "PCR Test")
    (repo / ".project-change-router.yaml").write_text(
        "profile_id: test\n", encoding="utf-8"
    )
    _git(repo, "add", ".project-change-router.yaml")
    _git(repo, "commit", "-qm", "base")
    source_commit = _git(repo, "rev-parse", "HEAD")
    bundle = _bundle()
    for payload in bundle.values():
        payload["source_commit"] = source_commit
    bundle["capability_catalog"]["capabilities"] = [
        {
            "id": "clocked-capability",
            "last_verified_at": "2026-07-23",
            "lifecycle": {
                "changelog": [
                    {
                        "date": "2026-07-23",
                        "event": "generated_from_repository_structure",
                    }
                ]
            },
        }
    ]
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle, source_commit=source_commit)
    profile = _profile(rule)
    (repo / ".project-change-router.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    _git(repo, "add", ".project-change-router.yaml", "project-change-router")
    _git(repo, "commit", "-qm", "pin generated outputs")
    comparison_commit = _git(repo, "rev-parse", "HEAD")
    rebuilt = copy.deepcopy(bundle)
    for payload in rebuilt.values():
        payload["source_commit"] = comparison_commit
    rebuilt_capability = rebuilt["capability_catalog"]["capabilities"][0]
    rebuilt_capability["last_verified_at"] = "2026-07-24"
    rebuilt_capability["lifecycle"]["changelog"][0]["date"] = "2026-07-24"

    result = verify_generated_output_baseline(
        repo,
        profile,
        rebuilt,
        comparison_commit=comparison_commit,
    )

    assert result.findings == ()
    assert result.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())
    assert {
        item["source_commit"] for item in result.evidence
    } == {source_commit}


def test_profile_note_alone_cannot_initialize_a_new_pin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.invalid")
    _git(repo, "config", "user.name", "PCR Test")
    (repo / ".project-change-router.yaml").write_text(
        "profile_id: test\n", encoding="utf-8"
    )
    _git(repo, "add", ".project-change-router.yaml")
    _git(repo, "commit", "-qm", "base")
    source_commit = _git(repo, "rev-parse", "HEAD")
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle, source_commit=source_commit)

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        comparison_commit=source_commit,
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code")
        == "generated_output_baseline_provenance_incomplete"
        for item in result.findings
    )

    authorized = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        comparison_commit=source_commit,
        initialization_fingerprint=str(rule["fingerprint"]),
    )

    assert authorized.findings == ()
    assert authorized.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())


def test_comparison_commit_with_both_canonical_profiles_fails_closed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.invalid")
    _git(repo, "config", "user.name", "PCR Test")
    for name in (".project-change-router.yaml", ".project-change-router.yml"):
        (repo / name).write_text("profile_id: test\n", encoding="utf-8")
    _git(repo, "add", ".project-change-router.yaml", ".project-change-router.yml")
    _git(repo, "commit", "-qm", "ambiguous profile base")
    source_commit = _git(repo, "rev-parse", "HEAD")
    (repo / ".project-change-router.yml").unlink()
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle, source_commit=source_commit)

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        comparison_commit=source_commit,
        initialization_fingerprint=str(rule["fingerprint"]),
    )

    assert result.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code")
        == "generated_output_baseline_provenance_incomplete"
        for item in result.findings
    )


def test_profile_suffix_rename_requires_exact_fingerprint_initialization(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.invalid")
    _git(repo, "config", "user.name", "PCR Test")
    yaml_profile = repo / ".project-change-router.yaml"
    yml_profile = repo / ".project-change-router.yml"
    yaml_profile.write_text("profile_id: test\n", encoding="utf-8")
    _git(repo, "add", ".project-change-router.yaml")
    _git(repo, "commit", "-qm", "canonical yaml profile")
    yaml_profile.rename(yml_profile)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "rename canonical profile suffix")
    source_commit = _git(repo, "rev-parse", "HEAD")
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle, source_commit=source_commit)
    profile = _profile(rule)

    unauthorized = verify_generated_output_baseline(
        repo,
        profile,
        bundle,
        comparison_commit=source_commit,
    )
    authorized = verify_generated_output_baseline(
        repo,
        profile,
        bundle,
        comparison_commit=source_commit,
        initialization_fingerprint=str(rule["fingerprint"]),
    )

    assert unauthorized.verified_paths == frozenset()
    assert any(
        item.get("diagnostic_code")
        == "generated_output_baseline_provenance_incomplete"
        for item in unauthorized.findings
    )
    assert authorized.findings == ()
    assert authorized.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())


def test_yml_canonical_profile_preserves_committed_pin_provenance(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.invalid")
    _git(repo, "config", "user.name", "PCR Test")
    profile_path = repo / ".project-change-router.yml"
    profile_path.write_text("profile_id: test\n", encoding="utf-8")
    _git(repo, "add", ".project-change-router.yml")
    _git(repo, "commit", "-qm", "base")
    source_commit = _git(repo, "rev-parse", "HEAD")
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle, source_commit=source_commit)
    assert rule["canonical_source"] == ".project-change-router.yml"
    profile = _profile(rule)
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    _git(repo, "add", ".project-change-router.yml")
    _git(repo, "commit", "-qm", "pin generated outputs")
    comparison_commit = _git(repo, "rev-parse", "HEAD")

    result = verify_generated_output_baseline(
        repo,
        profile,
        bundle,
        comparison_commit=comparison_commit,
    )

    assert result.findings == ()
    assert result.verified_paths == frozenset(PCR_BUNDLE_ARTIFACTS.values())


def test_pin_source_must_match_unique_active_canonical_profile(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".project-change-router.yml").write_text(
        "profile_id: test\n", encoding="utf-8"
    )
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)
    rule["canonical_source"] = ".project-change-router.yaml"
    rule["fingerprint"] = generated_output_rule_fingerprint(rule)

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        bundle,
        enforce_provenance=False,
    )

    assert result.verified_paths == frozenset()
    assert validate_generated_output_rules(
        _profile(rule), repo_root=repo
    )
    assert any(
        item.get("diagnostic_code") == "generated_output_baseline_invalid"
        for item in result.findings
    )


def test_rebuild_exception_uses_structured_blocking_diagnostic(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    bundle = _bundle()
    _write_bundle(repo, bundle)
    rule = _rule(repo, bundle)

    result = verify_generated_output_baseline(
        repo,
        _profile(rule),
        None,
        enforce_provenance=False,
        rebuild_error="ValueError: malformed curated input",
    )

    assert result.verified_paths == frozenset()
    assert result.findings[0]["diagnostic_code"] == "generated_output_rebuild_failed"
    assert result.findings[0]["blocking"] is True
