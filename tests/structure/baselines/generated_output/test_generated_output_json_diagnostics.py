from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import yaml

from generated_output_test_support import (
    SKILL_ROOT,
    build_and_write_bundle,
    create_real_router_repo,
    git,
    make_real_rule,
    profile_with_rule,
)

from router_support.generated_output_baseline import (
    ARTIFACT_FIELDS,
    PCR_BUNDLE_ARTIFACTS,
    RULE_FIELDS,
    generated_output_rule_fingerprint,
    validate_generated_output_rules,
)


def _valid_rule() -> dict[object, object]:
    rule: dict[object, object] = {
        "id": "PCR-GEN-JSON-001",
        "mode": "pinned-idempotent-v1",
        "generator_id": "pcr-router-bundle-v1",
        "canonical_source": ".project-change-router.yaml",
        "source_commit": "a" * 40,
        "owner": "router-governance",
        "reason": "Exercise JSON-safe diagnostics.",
        "exit_stage": "PCR-GEN-CANONICAL-INPUTS",
        "exit_condition": "Remove after canonical inputs converge.",
        "initialization_authorization": "Explicit test authorization.",
        "artifacts": [
            {
                "bundle_key": key,
                "source_commit": "a" * 40,
                "semantic_digest": "b" * 64,
                "canonical_text_digest": "c" * 64,
                "line_count": 1,
            }
            for key in PCR_BUNDLE_ARTIFACTS
        ],
        "fingerprint": "",
    }
    rule["fingerprint"] = generated_output_rule_fingerprint(rule)
    assert set(rule) == RULE_FIELDS
    assert all(set(item) == ARTIFACT_FIELDS for item in rule["artifacts"])
    return rule


def _profile(rule: dict[object, object]) -> dict[str, object]:
    return {
        "capabilities": [
            {
                "id": "router-governance",
                "status": "stable",
                "stage": "stable",
            }
        ],
        "capability_ownership": [
            {
                "target": "router-governance",
                "primary": "router-maintainers",
                "reviewers": ["router-reviewers"],
            }
        ],
        "guardrails": {"generated_output_baseline": [rule]},
    }


def _assert_json_safe_findings(rule: dict[object, object]) -> None:
    findings = validate_generated_output_rules(_profile(rule))

    assert findings
    assert all(finding["blocking"] is True for finding in findings)
    json.dumps(findings, allow_nan=False, ensure_ascii=False)


def test_non_json_yaml_scalar_is_reported_as_json_safe_diagnostic() -> None:
    rule = _valid_rule()
    rule["mode"] = dt.date(2026, 7, 23)

    _assert_json_safe_findings(rule)


def test_mixed_rule_keys_are_reported_as_json_safe_diagnostic() -> None:
    rule = _valid_rule()
    rule[7] = "unexpected"

    _assert_json_safe_findings(rule)


def test_mixed_artifact_keys_are_reported_as_json_safe_diagnostic() -> None:
    rule = _valid_rule()
    artifacts = copy.deepcopy(rule["artifacts"])
    artifacts[0][dt.date(2026, 7, 23)] = "unexpected"
    rule["artifacts"] = artifacts

    _assert_json_safe_findings(rule)


def test_non_json_artifact_key_value_is_json_safe() -> None:
    rule = _valid_rule()
    artifacts = copy.deepcopy(rule["artifacts"])
    artifacts[0]["bundle_key"] = dt.date(2026, 7, 23)
    rule["artifacts"] = artifacts

    _assert_json_safe_findings(rule)


def test_check_structure_cli_emits_json_for_yaml_date_scalar(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    bundle = build_and_write_bundle(repo)
    rule = make_real_rule(repo, bundle)
    rule["mode"] = dt.date(2026, 7, 23)
    profile = profile_with_rule(repo, rule)
    (repo / ".project-change-router.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "check_structure.py"),
            "--repo",
            str(repo),
            "--comparison-commit",
            git(repo, "rev-parse", "HEAD"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert any(
        finding["diagnostic_code"] == "generated_output_baseline_invalid"
        for finding in report["findings"]
    )
    json.dumps(report, allow_nan=False, ensure_ascii=False)


def test_check_structure_treats_falsy_malformed_pin_as_declared(
    tmp_path: Path,
) -> None:
    repo = create_real_router_repo(tmp_path)
    build_and_write_bundle(repo)
    profile = yaml.safe_load(
        (repo / ".project-change-router.yaml").read_text(encoding="utf-8")
    )
    profile["guardrails"] = {"generated_output_baseline": {}}
    (repo / ".project-change-router.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts/check_structure.py"),
            "--repo",
            str(repo),
            "--comparison-commit",
            git(repo, "rev-parse", "HEAD"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert any(
        item.get("diagnostic_code") == "generated_output_baseline_invalid"
        for item in report["findings"]
    )
    assert "Traceback" not in result.stderr
